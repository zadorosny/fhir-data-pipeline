"""Testes do parse de mensagens do consumer (poison messages -> DLQ, nao crash)."""

from __future__ import annotations

import pytest

from etl.kafka_consumer import parse_message


def test_parse_message_json_valido() -> None:
    assert parse_message(b'{"cpf": "123", "nome": "Ana"}') == {"cpf": "123", "nome": "Ana"}


@pytest.mark.parametrize(
    "raw",
    [
        b"nao-e-json",
        b"",
        b"\xff\xfe invalido",  # bytes nao decodificaveis
        b'"string json"',  # JSON valido mas nao-objeto
        b"[1, 2, 3]",
        b"42",
        b"null",
        None,  # tombstone
    ],
)
def test_parse_message_invalido_levanta_valueerror(raw: bytes | None) -> None:
    with pytest.raises(ValueError):
        parse_message(raw)
