"""Testes do cliente HTTP FHIR (Session + Retry + FHIRError)."""

from __future__ import annotations

import responses

from etl.lib.fhir import FHIRError, build_session, post_resource, wait_for_fhir

BASE_URL = "http://fhir.test/fhir"
PATIENT_RESOURCE = {"resourceType": "Patient", "id": "test"}


@responses.activate
def test_post_resource_retorna_created_em_201() -> None:
    responses.add(
        responses.POST,
        f"{BASE_URL}/Patient",
        json={"id": "abc-123", "resourceType": "Patient"},
        status=201,
    )
    session = build_session(max_retries=0)
    body, created = post_resource(session, BASE_URL, PATIENT_RESOURCE)
    assert created is True
    assert body["id"] == "abc-123"


@responses.activate
def test_post_resource_retorna_exists_em_200() -> None:
    responses.add(
        responses.POST,
        f"{BASE_URL}/Patient",
        json={"id": "abc-123", "resourceType": "Patient"},
        status=200,
    )
    session = build_session(max_retries=0)
    body, created = post_resource(
        session, BASE_URL, PATIENT_RESOURCE, if_none_exist="identifier=foo|bar"
    )
    assert created is False
    assert body["id"] == "abc-123"


@responses.activate
def test_post_resource_levanta_em_4xx_sem_retry() -> None:
    responses.add(
        responses.POST,
        f"{BASE_URL}/Patient",
        json={"error": "invalid"},
        status=422,
    )
    session = build_session(max_retries=3, backoff_factor=0.0)
    try:
        post_resource(session, BASE_URL, PATIENT_RESOURCE)
    except FHIRError as exc:
        assert exc.status_code == 422
    else:
        raise AssertionError("FHIRError nao foi levantado")
    # 422 nao esta em status_forcelist -> 1 unica tentativa
    assert len(responses.calls) == 1


@responses.activate
def test_post_resource_retenta_em_5xx_e_eventualmente_succede() -> None:
    responses.add(responses.POST, f"{BASE_URL}/Patient", json={}, status=503)
    responses.add(responses.POST, f"{BASE_URL}/Patient", json={}, status=503)
    responses.add(
        responses.POST,
        f"{BASE_URL}/Patient",
        json={"id": "ok", "resourceType": "Patient"},
        status=201,
    )
    session = build_session(max_retries=5, backoff_factor=0.0)
    body, created = post_resource(session, BASE_URL, PATIENT_RESOURCE)
    assert created is True
    assert body["id"] == "ok"
    assert len(responses.calls) == 3


@responses.activate
def test_post_resource_falha_apos_esgotar_retries() -> None:
    for _ in range(6):
        responses.add(responses.POST, f"{BASE_URL}/Patient", json={}, status=500)
    session = build_session(max_retries=2, backoff_factor=0.0)
    try:
        post_resource(session, BASE_URL, PATIENT_RESOURCE)
    except FHIRError as exc:
        assert exc.status_code is None or exc.status_code >= 500
    else:
        raise AssertionError("FHIRError esperado apos retries")


@responses.activate
def test_wait_for_fhir_succede_imediato() -> None:
    responses.add(responses.GET, f"{BASE_URL}/metadata", json={"x": 1}, status=200)
    session = build_session(max_retries=0)
    wait_for_fhir(session, BASE_URL, attempts=1, delay=0)


@responses.activate
def test_wait_for_fhir_levanta_apos_atingir_attempts() -> None:
    responses.add(responses.GET, f"{BASE_URL}/metadata", json={}, status=500)
    session = build_session(max_retries=0)
    try:
        wait_for_fhir(session, BASE_URL, attempts=2, delay=0)
    except FHIRError:
        pass
    else:
        raise AssertionError("wait_for_fhir deveria levantar FHIRError")
