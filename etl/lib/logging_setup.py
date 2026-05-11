"""Logging estruturado JSON.

Cada linha de log e um JSON com timestamp, level, message e extras.
Util para coleta por Loki/ELK/CloudWatch.
"""

from __future__ import annotations

import logging
import sys

from pythonjsonlogger import jsonlogger


def configure_logging(level: str = "INFO", *, service: str = "fhir-etl") -> logging.Logger:
    """Configura o root logger para emitir JSON em stdout.

    Idempotente: chamadas repetidas substituem o handler ao inves de empilhar.
    """
    root = logging.getLogger()
    root.setLevel(level.upper())
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    # python-json-logger nao publica py.typed/stubs - mypy strict trata
    # JsonFormatter como Any e dispara `no-untyped-call`.
    fmt = jsonlogger.JsonFormatter(  # type: ignore[no-untyped-call]
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        rename_fields={"asctime": "ts", "levelname": "level", "name": "logger"},
    )
    handler.setFormatter(fmt)
    root.addHandler(handler)

    return logging.getLogger(service)
