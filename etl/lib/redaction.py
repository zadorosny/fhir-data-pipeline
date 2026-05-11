"""Utilidades para redacao de PHI em logs e eventos.

Centraliza mascaramento/hashing de identificadores sensiveis (CPF) para
nunca emitir digitos em texto claro pelo pipeline de logs estruturados.

- `hash_cpf`: SHA-256 hex prefixado por "sha256:". Deterministico, pseudonomi-
  zacao adequada para correlacionar eventos sem expor o identificador.
- `mask_cpf`: formato `***.***.***-NN` preservando apenas os 2 ultimos digi-
  tos. Util em mensagens humanas (alertas, debug controlado), nao em logs
  agregados.
"""

from __future__ import annotations

import hashlib

from etl.lib.transform import clean_cpf

_HASH_PREFIX = "sha256:"


def hash_cpf(cpf: str | None) -> str | None:
    """Retorna `sha256:<hex>` do CPF normalizado, ou None se entrada vazia."""
    digits = clean_cpf(cpf)
    if not digits:
        return None
    digest = hashlib.sha256(digits.encode("utf-8")).hexdigest()
    return f"{_HASH_PREFIX}{digest}"


def mask_cpf(cpf: str | None) -> str | None:
    """Retorna `***.***.***-NN` (ultimos 2 digitos), ou None se entrada vazia."""
    digits = clean_cpf(cpf)
    if not digits:
        return None
    tail = digits[-2:] if len(digits) >= 2 else digits
    return f"***.***.***-{tail}"
