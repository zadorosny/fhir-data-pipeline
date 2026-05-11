"""Transformacoes puras (sem I/O).

Funcoes aqui sao 100 por cento testaveis sem Spark/Kafka/HAPI.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Iterable

CANONICAL_COLUMNS = {
    "Nome": ("Nome",),
    "CPF": ("CPF",),
    "Genero": ("Gênero", "Genero", "gênero", "genero"),
    "DataNascimento": ("Data de Nascimento", "Data Nascimento", "DataNascimento"),
    "Telefone": ("Telefone",),
    "Pais": ("País de Nascimento", "Pais de Nascimento", "Pais", "País"),
    "Observacao": ("Observação", "Observacao", "observação"),
}

CPF_REGEX = re.compile(r"\D+")
DATE_FALLBACK = "1900-01-01"


class ColumnMappingError(ValueError):
    """Levantado quando o CSV nao contem todas as colunas esperadas."""


def _normalize_key(value: str) -> str:
    return value.strip().replace("﻿", "")


def build_column_map(csv_columns: Iterable[str]) -> dict[str, str]:
    """Mapeia colunas do CSV (com acentos/BOM) para nomes canonicos.

    Levanta ColumnMappingError se alguma coluna obrigatoria nao for encontrada.
    """
    available = {_normalize_key(c): c for c in csv_columns}
    mapping: dict[str, str] = {}

    for canonical, aliases in CANONICAL_COLUMNS.items():
        match: str | None = None
        for alias in aliases:
            alias_norm = _normalize_key(alias)
            if alias_norm in available:
                match = available[alias_norm]
                break
        if match is None:
            for alias_norm, original in available.items():
                if any(_loose_match(alias, alias_norm) for alias in aliases):
                    match = original
                    break
        if match is None:
            raise ColumnMappingError(
                f"Coluna obrigatoria '{canonical}' nao encontrada no CSV; "
                f"disponiveis: {sorted(available.keys())}"
            )
        mapping[match] = canonical
    return mapping


def _loose_match(expected: str, actual: str) -> bool:
    return _strip_accents(expected).lower() == _strip_accents(actual).lower()


def _strip_accents(s: str) -> str:
    import unicodedata

    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )


def parse_date(date_str: str | None) -> str:
    """Converte DD/MM/AAAA -> AAAA-MM-DD; aceita ja-ISO; fallback se invalido."""
    if not date_str:
        return DATE_FALLBACK
    s = date_str.strip()
    if not s:
        return DATE_FALLBACK
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return DATE_FALLBACK


def clean_cpf(cpf: str | None) -> str:
    """Remove pontos, hifens, espacos. NAO valida digitos verificadores."""
    if not cpf:
        return ""
    return CPF_REGEX.sub("", cpf)


def map_gender(genero: str | None) -> str:
    """CSV -> codigo FHIR (administrative-gender)."""
    if not genero:
        return "unknown"
    g = _strip_accents(genero).strip().lower()
    if g in {"masculino", "m", "male"}:
        return "male"
    if g in {"feminino", "f", "female"}:
        return "female"
    if g in {"outro", "other"}:
        return "other"
    return "unknown"


def split_observations(raw: str | None) -> list[str]:
    """Quebra a coluna Observacao em lista (separador '|'); remove vazios."""
    if not raw:
        return []
    return [obs.strip() for obs in raw.split("|") if obs.strip()]


def row_to_message(row: dict[str, Any]) -> dict[str, str]:
    """Linha (com colunas canonicas) -> dict serializavel pelo producer.

    Tudo string para evitar surpresas de serializacao JSON.
    """
    return {
        "nome": (row.get("Nome") or "").strip(),
        "cpf": (row.get("CPF") or "").strip(),
        "genero": (row.get("Genero") or "").strip(),
        "data_nascimento": (row.get("DataNascimento") or "").strip(),
        "telefone": (row.get("Telefone") or "").strip(),
        "pais": (row.get("Pais") or "").strip(),
        "observacao": (row.get("Observacao") or "").strip(),
    }
