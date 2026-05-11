"""Producer: PySpark le o CSV de pacientes e publica cada registro
como mensagem JSON no topico Kafka configurado.

Usa funcoes puras de etl.lib.transform para parsing e mapeamento de colunas
(testavel sem subir Spark/Kafka).
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from kafka import KafkaProducer
from kafka.errors import KafkaError
from pyspark.sql import SparkSession

from etl.lib.config import get_settings
from etl.lib.logging_setup import configure_logging
from etl.lib.transform import (
    ColumnMappingError,
    build_column_map,
    row_to_message,
)


def make_producer(broker: str) -> KafkaProducer:
    """Producer com semantica at-least-once + ordem preservada por particao."""
    return KafkaProducer(
        bootstrap_servers=broker,
        value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"),
        acks="all",
        retries=5,
        linger_ms=50,
        batch_size=32 * 1024,
        max_in_flight_requests_per_connection=1,
    )


def read_csv(spark: SparkSession, path: str, encoding: str) -> list[dict[str, Any]]:
    df = (
        spark.read.option("header", "true")
        .option("encoding", encoding)
        .option("sep", ",")
        .csv(path)
    )
    column_map = build_column_map(df.columns)
    for original, canonical in column_map.items():
        if original != canonical:
            df = df.withColumnRenamed(original, canonical)
    return [row.asDict(recursive=True) for row in df.collect()]


def main() -> int:
    settings = get_settings()
    logger = configure_logging(settings.log_level, service="fhir-producer")
    logger.info(
        "Producer iniciado",
        extra={
            "event": "producer_start",
            "kafka_broker": settings.kafka_broker,
            "topic": settings.kafka_topic,
            "csv_path": settings.csv_path,
        },
    )

    spark = (
        SparkSession.builder.appName("FHIR-Kafka-Producer")
        .master("local[*]")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")

    try:
        rows = read_csv(spark, settings.csv_path, settings.csv_encoding)
    except ColumnMappingError as exc:
        logger.error(
            "CSV invalido", extra={"event": "csv_invalid", "error": str(exc)}
        )
        spark.stop()
        return 2

    logger.info(
        "CSV carregado", extra={"event": "csv_loaded", "rows": len(rows)}
    )

    producer = make_producer(settings.kafka_broker)
    sent = 0
    try:
        for row in rows:
            message = row_to_message(row)
            producer.send(settings.kafka_topic, value=message)
            sent += 1
        producer.flush(timeout=30)
    except KafkaError as exc:
        logger.error(
            "Falha no envio Kafka",
            extra={"event": "kafka_send_failed", "sent": sent, "error": str(exc)},
        )
        producer.close(timeout=5)
        spark.stop()
        return 3
    finally:
        producer.close(timeout=5)
        spark.stop()

    logger.info(
        "Producer concluido",
        extra={"event": "producer_done", "sent": sent, "topic": settings.kafka_topic},
    )
    return 0


if __name__ == "__main__":
    logging.captureWarnings(True)
    sys.exit(main())
