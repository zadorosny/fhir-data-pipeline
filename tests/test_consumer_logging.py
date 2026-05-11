"""Testes de regressao: garante que CPF nunca vaza em texto claro nos logs.

Cobre os call sites em `etl.kafka_consumer.process_patient` (sucesso e erro).
Se alguem reintroduzir `"cpf": data.get("cpf")` nos `extra={...}`, estes
testes falham.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
import responses

from etl.kafka_consumer import process_patient
from etl.lib.fhir import build_session

CPF_PLAINTEXT = "12345678901"
PATIENT_DATA: dict[str, Any] = {
    "cpf": CPF_PLAINTEXT,
    "nome": "JOAO TESTE",
    "data_nascimento": "1990-01-15",
    "genero": "M",
}
FHIR_BASE = "http://hapi-test/fhir"


def _formatted(record: logging.LogRecord) -> str:
    """Renderiza o record do mesmo jeito que um agregador faria."""
    payload = " ".join(str(getattr(record, k, "")) for k in record.__dict__)
    return f"{record.getMessage()} {payload}"


@responses.activate
def test_log_de_sucesso_usa_cpf_hash_sem_vazar_plaintext(
    caplog: pytest.LogCaptureFixture,
) -> None:
    responses.post(
        f"{FHIR_BASE}/Patient",
        json={"resourceType": "Patient", "id": "abc-123"},
        status=201,
    )

    session = build_session(max_retries=0, backoff_factor=0)
    logger = logging.getLogger("test-consumer-ok")

    with caplog.at_level(logging.INFO, logger="test-consumer-ok"):
        patient_ref = process_patient(session, FHIR_BASE, PATIENT_DATA, logger)

    assert patient_ref == "Patient/abc-123"
    record = next(r for r in caplog.records if r.message == "Patient processado")
    assert getattr(record, "cpf_hash", "").startswith("sha256:")
    assert not hasattr(record, "cpf"), "campo `cpf` deve estar redacted"
    assert CPF_PLAINTEXT not in _formatted(record)


@responses.activate
def test_log_de_falha_usa_cpf_hash_sem_vazar_plaintext(
    caplog: pytest.LogCaptureFixture,
) -> None:
    responses.post(f"{FHIR_BASE}/Patient", json={"issue": []}, status=422)

    session = build_session(max_retries=0, backoff_factor=0)
    logger = logging.getLogger("test-consumer-err")

    with caplog.at_level(logging.ERROR, logger="test-consumer-err"):
        patient_ref = process_patient(session, FHIR_BASE, PATIENT_DATA, logger)

    assert patient_ref is None
    record = next(r for r in caplog.records if r.message == "Falha definitiva ao criar Patient")
    assert getattr(record, "cpf_hash", "").startswith("sha256:")
    assert not hasattr(record, "cpf"), "campo `cpf` deve estar redacted"
    assert CPF_PLAINTEXT not in _formatted(record)
