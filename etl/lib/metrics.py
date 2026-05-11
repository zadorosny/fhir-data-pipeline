"""Metricas Prometheus expostas em /metrics (porta METRICS_PORT)."""

from __future__ import annotations

import logging

from prometheus_client import Counter, Histogram, start_http_server

logger = logging.getLogger(__name__)

messages_total = Counter(
    "fhir_consumer_messages_total",
    "Total de mensagens consumidas, agrupadas por resource e status",
    labelnames=("resource", "status"),
)

post_latency = Histogram(
    "fhir_consumer_post_latency_seconds",
    "Latencia do POST para o HAPI FHIR",
    labelnames=("resource",),
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

dlq_total = Counter(
    "fhir_consumer_dlq_total",
    "Mensagens enviadas para o dead-letter topic",
)


def start_metrics_server(port: int) -> None:
    """Sobe o endpoint HTTP /metrics. Idempotente o suficiente para retries de boot."""
    try:
        start_http_server(port)
        logger.info("Metrics server iniciado", extra={"port": port})
    except OSError as exc:
        logger.warning(
            "Falha ao iniciar metrics server",
            extra={"port": port, "error": str(exc)},
        )
