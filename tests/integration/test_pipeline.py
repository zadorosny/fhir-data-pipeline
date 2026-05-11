"""Smoke test de integracao: sobe o stack via docker compose e valida HAPI.

Requer: docker, docker-compose, .env existente.
Marcado com @pytest.mark.integration; nao roda por default.

Execucao:  pytest -m integration
"""

from __future__ import annotations

import shutil
import subprocess
import time

import pytest
import requests

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def stack_up() -> None:
    if shutil.which("docker") is None:
        pytest.skip("docker nao disponivel no host")
    subprocess.run(
        ["docker", "compose", "up", "-d", "--build"],
        check=True,
        capture_output=True,
    )
    deadline = time.time() + 300
    while time.time() < deadline:
        try:
            r = requests.get("http://localhost:8080/fhir/metadata", timeout=3)
            if r.status_code == 200:
                break
        except requests.RequestException:
            pass
        time.sleep(3)
    else:
        pytest.fail("HAPI nao ficou pronto em 5min")
    yield
    subprocess.run(["docker", "compose", "down", "-v"], check=False)


def test_hapi_capability_statement(stack_up: None) -> None:
    r = requests.get("http://localhost:8080/fhir/metadata", timeout=10)
    assert r.status_code == 200
    assert r.json()["resourceType"] == "CapabilityStatement"


def test_patients_foram_ingeridos(stack_up: None) -> None:
    # Apos o stack subir, producer + consumer rodaram via depends_on.
    r = requests.get(
        "http://localhost:8080/fhir/Patient",
        params={"_summary": "count"},
        timeout=10,
    )
    assert r.status_code == 200
    total = r.json().get("total", 0)
    assert total >= 1, f"Nenhum Patient ingerido (total={total})"


def test_metrics_endpoint(stack_up: None) -> None:
    r = requests.get("http://localhost:8001/metrics", timeout=5)
    assert r.status_code == 200
    assert "fhir_consumer_messages_total" in r.text
