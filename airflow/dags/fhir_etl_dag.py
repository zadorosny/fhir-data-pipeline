"""
DAG Airflow para orquestrar o pipeline ETL de carga FHIR.

Fluxo:
  1. Producer (PySpark): lê o CSV e publica no Kafka
  2. Consumer: lê do Kafka e carrega no HAPI FHIR

schedule_interval=None — a DAG é disparada manualmente via UI ou CLI.
O consumer é idempotente (verifica duplicatas por CPF e código SNOMED CT),
então re-execuções são seguras.

Os containers fhir_producer e fhir_consumer são definidos no
docker-compose.yml com todos os volumes, variáveis de ambiente
e rede já configurados. O 'docker start -a' reinicia o container
e acompanha a saída (stdout/stderr).
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

default_args = {
    "owner": "airflow",
    "retries": 1,
    "retry_delay": timedelta(minutes=2),
}

with DAG(
    dag_id="fhir_patient_etl",
    default_args=default_args,
    description="Pipeline CSV → Kafka → HAPI FHIR via PySpark",
    schedule_interval=None,
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
