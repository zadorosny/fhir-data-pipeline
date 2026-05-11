"""Testes da configuracao via env vars."""

from __future__ import annotations

import pytest

from etl.lib.config import ETLSettings, get_settings, reset_settings_for_tests


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_settings_for_tests()
    yield
    reset_settings_for_tests()


def test_defaults() -> None:
    s = ETLSettings()
    assert s.kafka_broker == "kafka:9092"
    assert s.kafka_topic == "fhir-patients"
    assert s.kafka_dlq_topic == "fhir-patients-dlq"
    assert s.fhir_post_max_retries == 5
    assert s.metrics_port == 8001


def test_override_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KAFKA_BROKER", "broker:1234")
    monkeypatch.setenv("KAFKA_TOPIC", "outro-topico")
    monkeypatch.setenv("HAPI_BASE_URL", "http://hapi:9999/fhir")
    monkeypatch.setenv("METRICS_PORT", "9090")
    s = ETLSettings()
    assert s.kafka_broker == "broker:1234"
    assert s.kafka_topic == "outro-topico"
    assert s.fhir_base == "http://hapi:9999/fhir"
    assert s.metrics_port == 9090


def test_metrics_port_fora_da_faixa(monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import ValidationError

    monkeypatch.setenv("METRICS_PORT", "80")
    with pytest.raises(ValidationError):
        ETLSettings()


def test_get_settings_cacheia() -> None:
    a = get_settings()
    b = get_settings()
    assert a is b
