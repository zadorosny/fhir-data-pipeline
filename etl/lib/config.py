"""Configuracao centralizada do ETL, lida de variaveis de ambiente.

Usa pydantic-settings para validar tipos e oferecer defaults seguros.
Todas as constantes sensiveis (broker, URLs, retries) ficam aqui.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Encodings comuns para CSVs do SUS/IBGE/Datasus. Mantemos uma allowlist
# explicita para travar erros de configuracao no startup e prevenir
# manipulacao maliciosa via env var.
CsvEncoding = Literal["ISO-8859-1", "UTF-8", "UTF-8-SIG", "Windows-1252"]


class ETLSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    kafka_broker: str = Field(default="kafka:9092")
    kafka_topic: str = Field(default="fhir-patients")
    kafka_dlq_topic: str = Field(default="fhir-patients-dlq")

    fhir_base: str = Field(default="http://hapi-fhir:8080/fhir", alias="HAPI_BASE_URL")

    csv_path: str = Field(default="/opt/app/data/patients.csv")
    csv_encoding: CsvEncoding = Field(default="ISO-8859-1")

    consumer_timeout_ms: int = Field(default=15000, ge=1000)
    hapi_retry_attempts: int = Field(default=30, ge=1, le=300)
    hapi_retry_delay: float = Field(default=2.0, ge=0.1, le=30.0)
    fhir_post_max_retries: int = Field(default=5, ge=0, le=20)
    fhir_post_backoff: float = Field(default=0.5, ge=0.0, le=10.0)

    metrics_port: int = Field(default=8001, ge=1024, le=65535)
    log_level: str = Field(default="INFO")


_settings: ETLSettings | None = None


def get_settings() -> ETLSettings:
    """Cache de settings - le env uma unica vez por processo."""
    global _settings
    if _settings is None:
        _settings = ETLSettings()
    return _settings


def reset_settings_for_tests() -> None:
    """Forca releitura das envs (uso exclusivo de testes)."""
    global _settings
    _settings = None
