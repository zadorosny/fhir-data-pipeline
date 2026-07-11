"""DAG Airflow para orquestrar o pipeline ETL de carga FHIR.

Fluxo:
  1. Producer (PySpark): le o CSV e publica no Kafka
  2. Consumer: le do Kafka e carrega no HAPI FHIR

schedule=None - a DAG e disparada manualmente via UI/CLI.
O consumer e idempotente (If-None-Exist por CPF/SNOMED), entao re-execucoes sao seguras.

Em caso de falha de qualquer task, um POST e enviado para ALERT_WEBHOOK_URL
(se configurada) com diagnostico. Sem URL, o callback so loga warning.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

from airflow import DAG
from airflow.operators.bash import BashOperator

logger = logging.getLogger(__name__)


def alert_on_failure(context: dict[str, Any]) -> None:
    """Notifica falha via webhook. Nao levanta excecao para nao mascarar o erro real."""
    webhook = os.getenv("ALERT_WEBHOOK_URL", "").strip()
    task = context.get("task_instance")
    dag_id = context.get("dag").dag_id if context.get("dag") else "unknown"
    task_id = task.task_id if task else "unknown"
    log_url = getattr(task, "log_url", "")
    payload = {
        "event": "airflow_task_failed",
        "dag_id": dag_id,
        "task_id": task_id,
        "execution_date": str(context.get("execution_date")),
        "log_url": log_url,
        "exception": str(context.get("exception", "")),
    }
    if not webhook:
        logger.warning(
            "Task falhou sem webhook configurado",
            extra={"alert_payload": payload},
        )
        return
    try:
        req = urlrequest.Request(
            webhook,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlrequest.urlopen(req, timeout=5) as resp:  # noqa: S310 — URL controlada
            logger.info("Alerta enviado", extra={"status": resp.status})
    except (urlerror.URLError, OSError) as exc:
        logger.warning("Falha ao enviar alerta", extra={"error": str(exc)})


default_args = {
    "owner": "airflow",
    "retries": 1,
    "retry_delay": timedelta(minutes=2),
    "on_failure_callback": alert_on_failure,
}

with DAG(
    dag_id="fhir_patient_etl",
    default_args=default_args,
    description="Pipeline CSV -> Kafka -> HAPI FHIR via PySpark",
    schedule=None,
    start_date=datetime(2025, 1, 1),
    catchup=False,
    tags=["fhir", "etl", "kafka"],
) as dag:

    producer = BashOperator(
        task_id="kafka_producer",
        bash_command="docker start -a fhir_producer",
    )

    consumer = BashOperator(
        task_id="kafka_consumer",
        bash_command="docker start -a fhir_consumer",
    )

    producer >> consumer
