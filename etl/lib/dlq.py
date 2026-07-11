"""Dead-letter queue publisher.

Quando um POST FHIR falha definitivamente (apos retries), a mensagem
original e empurrada para um topico Kafka separado com headers indicando
a razao da falha. Outro consumer pode investigar/replay essas mensagens.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from kafka import KafkaProducer

logger = logging.getLogger(__name__)


def _serialize(value: dict[str, Any] | bytes) -> bytes:
    """Dicts viram JSON; bytes (payload envenenado) seguem intactos para replay."""
    if isinstance(value, bytes):
        return value
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def make_dlq_producer(broker: str) -> KafkaProducer:
    return KafkaProducer(
        bootstrap_servers=broker,
        value_serializer=_serialize,
        acks="all",
        retries=5,
        linger_ms=10,
    )


def publish_to_dlq(
    producer: KafkaProducer,
    topic: str,
    message: dict[str, Any] | bytes,
    *,
    reason: str,
    status_code: int | None = None,
    body: str | None = None,
) -> None:
    """Publica a mensagem original na DLQ com headers de diagnostico.

    Falha silenciosamente apenas como log de erro: nao queremos
    matar o consumer principal por causa de uma falha de DLQ.
    """
    headers: list[tuple[str, bytes]] = [("reason", reason.encode("utf-8"))]
    if status_code is not None:
        headers.append(("status_code", str(status_code).encode("utf-8")))
    if body:
        headers.append(("body_preview", body[:500].encode("utf-8", errors="replace")))
    try:
        producer.send(topic, value=message, headers=headers)
        producer.flush(timeout=10)
        logger.warning(
            "Mensagem enviada para DLQ",
            extra={"event": "dlq_send", "topic": topic, "reason": reason},
        )
    except Exception as exc:  # noqa: BLE001 — log e segue
        logger.error(
            "Falha ao publicar na DLQ",
            extra={"event": "dlq_send_failed", "topic": topic, "error": str(exc)},
        )
