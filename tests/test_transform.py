"""Testes das funcoes puras de transformacao."""

from __future__ import annotations

import pytest

from etl.lib.fhir import split_name
from etl.lib.transform import (
    ColumnMappingError,
    build_column_map,
    clean_cpf,
    map_gender,
    parse_date,
    row_to_message,
    split_observations,
)

# ---------------------------------------------------------------------------
# parse_date
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("10/05/1980", "1980-05-10"),
        ("01/01/2000", "2000-01-01"),
        ("1980-05-10", "1980-05-10"),
        ("10-05-1980", "1980-05-10"),
        ("  15/08/1992  ", "1992-08-15"),
    ],
)
def test_parse_date_formatos_validos(entrada: str, esperado: str) -> None:
    assert parse_date(entrada) == esperado


@pytest.mark.parametrize("entrada", ["", "   ", "nao-e-data", "32/13/2000", None])
def test_parse_date_invalido_usa_fallback(entrada: str | None) -> None:
    assert parse_date(entrada) == "1900-01-01"


# ---------------------------------------------------------------------------
# clean_cpf
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("123.456.789-00", "12345678900"),
        ("12345678900", "12345678900"),
        ("123 456 789 00", "12345678900"),
        ("", ""),
        (None, ""),
    ],
)
def test_clean_cpf(entrada: str | None, esperado: str) -> None:
    assert clean_cpf(entrada) == esperado


# ---------------------------------------------------------------------------
# map_gender
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("Masculino", "male"),
        ("masculino", "male"),
        ("MASCULINO", "male"),
        ("M", "male"),
        ("male", "male"),
        ("Feminino", "female"),
        ("Outro", "other"),
        ("", "unknown"),
        ("alien", "unknown"),
        (None, "unknown"),
    ],
)
def test_map_gender(entrada: str | None, esperado: str) -> None:
    assert map_gender(entrada) == esperado


# ---------------------------------------------------------------------------
# split_observations
# ---------------------------------------------------------------------------


def test_split_observations_simples() -> None:
    assert split_observations("Gestante") == ["Gestante"]


def test_split_observations_multipla() -> None:
    assert split_observations("Diabético|Hipertenso") == ["Diabético", "Hipertenso"]


def test_split_observations_vazios_sao_ignorados() -> None:
    assert split_observations("Diabético||  |Hipertenso") == ["Diabético", "Hipertenso"]


def test_split_observations_none() -> None:
    assert split_observations(None) == []


# ---------------------------------------------------------------------------
# build_column_map
# ---------------------------------------------------------------------------


def test_build_column_map_acentos_e_bom() -> None:
    cols = [
        "﻿Nome",
        "CPF",
        "Gênero",
        "Data de Nascimento",
        "Telefone",
        "País de Nascimento",
        "Observação",
    ]
    mapping = build_column_map(cols)
    assert mapping["﻿Nome"] == "Nome"
    assert mapping["Gênero"] == "Genero"
    assert mapping["Data de Nascimento"] == "DataNascimento"
    assert mapping["País de Nascimento"] == "Pais"
    assert mapping["Observação"] == "Observacao"


def test_build_column_map_sem_acento() -> None:
    cols = ["Nome", "CPF", "Genero", "DataNascimento", "Telefone", "Pais", "Observacao"]
    mapping = build_column_map(cols)
    assert set(mapping.values()) == {
        "Nome",
        "CPF",
        "Genero",
        "DataNascimento",
        "Telefone",
        "Pais",
        "Observacao",
    }


def test_build_column_map_coluna_faltando() -> None:
    cols = ["Nome", "CPF", "Genero"]  # falta varias
    with pytest.raises(ColumnMappingError) as exc:
        build_column_map(cols)
    assert "DataNascimento" in str(exc.value) or "Telefone" in str(exc.value)


# ---------------------------------------------------------------------------
# row_to_message
# ---------------------------------------------------------------------------


def test_row_to_message_completo() -> None:
    row = {
        "Nome": "  João da Silva ",
        "CPF": "123.456.789-00",
        "Genero": "Masculino",
        "DataNascimento": "10/05/1980",
        "Telefone": "(11) 1234-5678",
        "Pais": "Brasil",
        "Observacao": "Diabético|Hipertenso",
    }
    msg = row_to_message(row)
    assert msg == {
        "nome": "João da Silva",
        "cpf": "123.456.789-00",
        "genero": "Masculino",
        "data_nascimento": "10/05/1980",
        "telefone": "(11) 1234-5678",
        "pais": "Brasil",
        "observacao": "Diabético|Hipertenso",
    }


def test_row_to_message_campos_nulos() -> None:
    msg = row_to_message({"Nome": "Ana", "Observacao": None})
    assert msg["nome"] == "Ana"
    assert msg["observacao"] == ""
    assert msg["pais"] == ""


# ---------------------------------------------------------------------------
# split_name (re-export via fhir)
# ---------------------------------------------------------------------------


def test_split_name_dois_termos() -> None:
    given, family = split_name("João Silva")
    assert given == ["João"]
    assert family == "Silva"


def test_split_name_um_termo() -> None:
    given, family = split_name("Madonna")
    assert given == ["Madonna"]
    assert family == ""


def test_split_name_varios_termos() -> None:
    given, family = split_name("Maria Eduarda de Souza Lima")
    assert given == ["Maria", "Eduarda", "de", "Souza"]
    assert family == "Lima"


def test_split_name_vazio() -> None:
    given, family = split_name("   ")
    assert given == []
    assert family == ""
