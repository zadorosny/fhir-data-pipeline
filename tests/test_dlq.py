"""Testes do publisher de DLQ."""

from __future__ import annotations

from unittest.mock import MagicMock

from etl.lib.dlq import _serialize, publish_to_dlq


def test_publish_to_dlq_envia_com_headers() -> None:
    producer = MagicMock()
    publish_to_dlq(
        producer,
        "fhir-patients-dlq",
        {"cpf": "123"},
        reason="patient_post_failed",
        status_code=503,
        body="boom",
    )
    producer.send.assert_called_once()
    args, kwargs = producer.send.call_args
    assert args[0] == "fhir-patients-dlq"
    assert kwargs["value"] == {"cpf": "123"}
    headers = dict(kwargs["headers"])
    assert headers["reason"] == b"patient_post_failed"
    assert headers["status_code"] == b"503"
    assert headers["body_preview"] == b"boom"
    producer.flush.assert_called_once()


def test_publish_to_dlq_engole_excecao_e_loga() -> None:
    producer = MagicMock()
    producer.send.side_effect = RuntimeError("kafka down")
    publish_to_dlq(producer, "topic", {}, reason="x")


def test_publish_to_dlq_sem_body_nao_inclui_header() -> None:
    producer = MagicMock()
    publish_to_dlq(producer, "topic", {"a": 1}, reason="r")
    _, kwargs = producer.send.call_args
    headers = dict(kwargs["headers"])
    assert "body_preview" not in headers
    assert "status_code" not in headers


def test_serialize_dict_vira_json_e_bytes_passam_intactos() -> None:
    assert _serialize({"cpf": "123"}) == b'{"cpf": "123"}'
    assert _serialize(b"payload envenenado \xff") == b"payload envenenado \xff"
