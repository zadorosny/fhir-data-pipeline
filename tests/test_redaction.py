"""Testes do modulo etl.lib.redaction."""

from __future__ import annotations

import re

import pytest

from etl.lib.redaction import hash_cpf, mask_cpf

CPF_PLAINTEXT = "12345678901"
CPF_FORMATTED = "123.456.789-01"


def test_hash_cpf_retorna_prefixo_sha256() -> None:
    result = hash_cpf(CPF_PLAINTEXT)
    assert result is not None
    assert result.startswith("sha256:")
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", result)


def test_hash_cpf_e_deterministico() -> None:
    assert hash_cpf(CPF_PLAINTEXT) == hash_cpf(CPF_PLAINTEXT)


def test_hash_cpf_normaliza_pontuacao() -> None:
    # CPF com pontuacao deve gerar o mesmo hash que sem pontuacao
    assert hash_cpf(CPF_FORMATTED) == hash_cpf(CPF_PLAINTEXT)


def test_hash_cpf_nao_vaza_digitos_plaintext() -> None:
    result = hash_cpf(CPF_PLAINTEXT)
    assert result is not None
    assert CPF_PLAINTEXT not in result


@pytest.mark.parametrize("entrada", [None, "", "   "])
def test_hash_cpf_entrada_vazia_retorna_none(entrada: str | None) -> None:
    assert hash_cpf(entrada) is None


def test_mask_cpf_preserva_ultimos_dois_digitos() -> None:
    assert mask_cpf(CPF_PLAINTEXT) == "***.***.***-01"


def test_mask_cpf_aceita_formato_pontuado() -> None:
    assert mask_cpf(CPF_FORMATTED) == "***.***.***-01"


@pytest.mark.parametrize("entrada", [None, "", "   "])
def test_mask_cpf_entrada_vazia_retorna_none(entrada: str | None) -> None:
    assert mask_cpf(entrada) is None


def test_mask_cpf_curto_nao_quebra() -> None:
    # Defensivo: entrada com menos de 2 digitos
    assert mask_cpf("7") == "***.***.***-7"
