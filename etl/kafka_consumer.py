"""Consumer: le mensagens do topico Kafka e carrega Patient/Condition no HAPI FHIR.

Idempotente via If-None-Exist; falhas definitivas vao para a DLQ.
Metricas expostas em :METRICS_PORT/metrics.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any

from kafka import KafkaConsumer

from etl.lib.config import get_settings
from etl.lib.dlq import make_dlq_producer, publish_to_dlq
from etl.lib.fhir import (
    OBSERVATION_MAP,
    FHIRError,
    build_condition_resource,
    build_patient_resource,
    build_session,
    condition_search_criteria,
    patient_search_criteria,
    post_resource,
    wait_for_fhir,
)
from etl.lib.logging_setup import configure_logging
from etl.lib.metrics import dlq_total, messages_total, post_latency, start_metrics_server
from etl.lib.redaction import hash_cpf
from etl.lib.transform import split_observations


def process_patient(
    session: Any,
    base_url: str,
    data: dict[str, Any],
    logger: logging.Logger,
) -> str | None:
    """Cria/recupera o Patient. Retorna patient_ref ou None em erro definitivo."""
    patient = build_patient_resource(data)
    criteria = patient_search_criteria(data.get("cpf", ""))
    start = time.perf_counter()
    try:
        body, created = post_resource(session, base_url, patient, if_none_exist=criteria)
    except FHIRError as exc:
        logger.error(
            "Falha definitiva ao criar Patient",
            extra={
                "event": "patient_failed",
                "cpf_hash": hash_cpf(data.get("cpf")),
                "status": exc.status_code,
                "body": exc.body,
            },
        )
        messages_total.labels(resource="Patient", status="error").inc()
        return None
    finally:
        post_latency.labels(resource="Patient").observe(time.perf_counter() - start)

    status = "created" if created else "exists"
    messages_total.labels(resource="Patient", status=status).inc()
    logger.info(
        "Patient processado",
        extra={
            "event": "patient_ok",
            "cpf_hash": hash_cpf(data.get("cpf")),
            "status": status,
            "id": body.get("id"),
        },
    )
    return f"Patient/{body['id']}"


def process_conditions(
    session: Any,
    base_url: str,
    patient_ref: str,
    observations: list[str],
    logger: logging.Logger,
) -> int:
    """Cria Conditions vinculados ao Patient. Retorna numero de erros."""
    errors = 0
    for obs_key in observations:
        info = OBSERVATION_MAP.get(obs_key)
        if not info:
            logger.warning(
                "Observacao desconhecida",
                extra={"event": "obs_unknown", "obs": obs_key, "patient": patient_ref},
            )
            continue
        cond = build_condition_resource(patient_ref, obs_key)
        if cond is None:
            continue
        criteria = condition_search_criteria(patient_ref, info["snomed_code"])
        start = time.perf_counter()
        try:
            _, created = post_resource(session, base_url, cond, if_none_exist=criteria)
            status = "created" if created else "exists"
            messages_total.labels(resource="Condition", status=status).inc()
        except FHIRError as exc:
            errors += 1
            messages_total.labels(resource="Condition", status="error").inc()
            logger.error(
                "Falha ao criar Condition",
                extra={
                    "event": "condition_failed",
                    "obs": obs_key,
                    "patient": patient_ref,
                    "status": exc.status_code,
                },
            )
        finally:
            post_latency.labels(resource="Condition").observe(time.perf_counter() - start)
    return errors


def main() -> int:
    settings = get_settings()
    logger = configure_logging(settings.log_level, service="fhir-consumer")
    start_metrics_server(settings.metrics_port)

    logger.info(
        "Consumer iniciado",
        extra={
            "event": "consumer_start",
            "kafka_broker": settings.kafka_broker,
            "fhir_base": settings.fhir_base,
            "topic": settings.kafka_topic,
        },
    )

    session = build_session(
        max_retries=settings.fhir_post_max_retries,
        backoff_factor=settings.fhir_post_backoff,
    )
    wait_for_fhir(
        session,
        settings.fhir_base,
        attempts=settings.hapi_retry_attempts,
        delay=settings.hapi_retry_delay,
    )

    consumer = KafkaConsumer(
        settings.kafka_topic,
        bootstrap_servers=settings.kafka_broker,
        auto_offset_reset="earliest",
        consumer_timeout_ms=settings.consumer_timeout_ms,
        enable_auto_commit=False,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
    )
    dlq_producer = make_dlq_producer(settings.kafka_broker)

    totals = {"patient_ok": 0, "patient_dlq": 0, "condition_err": 0}
    try:
        for message in consumer:
            data = message.value
            logger.debug(
                "Mensagem recebida",
                extra={"event": "msg_received", "offset": message.offset},
            )
            patient_ref = process_patient(session, settings.fhir_base, data, logger)
            if patient_ref is None:
                publish_to_dlq(
                    dlq_producer,
                    settings.kafka_dlq_topic,
                    data,
                    reason="patient_post_failed",
                )
                dlq_total.inc()
                totals["patient_dlq"] += 1
                consumer.commit()
                continue

            totals["patient_ok"] += 1
            observations = split_observations(data.get("observacao"))
            cond_errors = process_conditions(
                session, settings.fhir_base, patient_ref, observations, logger
            )
            totals["condition_err"] += cond_errors
            consumer.commit()
    finally:
        consumer.close()
        dlq_producer.close(timeout=5)
        session.close()

    logger.info("Consumer concluido", extra={"event": "consumer_done", **totals})
    return 0


if __name__ == "__main__":
    sys.exit(main())
