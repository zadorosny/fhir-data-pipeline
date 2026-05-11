"""Builders de Resources FHIR + cliente HTTP idempotente com retry.

Os builders sao puros (input dict -> output dict).
O cliente usa requests.Session com backoff exponencial em 5xx/429/conn errors.
"""

from __future__ import annotations

import logging
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from etl.lib.transform import clean_cpf, map_gender, parse_date

BR_INDIVIDUO_PROFILE = "http://www.saude.gov.br/fhir/r4/StructureDefinition/BRIndividuo-1.0"
CPF_SYSTEM = "http://rnds-fhir.saude.gov.br/fhir/r4/NamingSystem/cpf"
SNOMED_SYSTEM = "http://snomed.info/sct"
ICD10_SYSTEM = "http://hl7.org/fhir/sid/icd-10"
PATIENT_BIRTHPLACE_EXT = "http://hl7.org/fhir/StructureDefinition/patient-birthPlace"

FHIR_HEADERS = {
    "Content-Type": "application/fhir+json",
    "Accept": "application/fhir+json",
}

OBSERVATION_MAP: dict[str, dict[str, str]] = {
    "Gestante": {
        "snomed_code": "77386006",
        "snomed_display": "Pregnant (finding)",
        "icd10_code": "Z33",
        "icd10_display": "Pregnant state",
        "text": "Gestante",
    },
    "Diabético": {
        "snomed_code": "73211009",
        "snomed_display": "Diabetes mellitus (disorder)",
        "icd10_code": "E14",
        "icd10_display": "Unspecified diabetes mellitus",
        "text": "Diabetes",
    },
    "Hipertenso": {
        "snomed_code": "38341003",
        "snomed_display": "Hypertensive disorder (disorder)",
        "icd10_code": "I10",
        "icd10_display": "Essential (primary) hypertension",
        "text": "Hipertensão",
    },
}


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Builders puros
# ---------------------------------------------------------------------------


def split_name(nome: str) -> tuple[list[str], str]:
    """Divide nome em (given, family). Ultima palavra vira family."""
    parts = [p for p in nome.strip().split() if p]
    if not parts:
        return [], ""
    if len(parts) == 1:
        return parts, ""
    return parts[:-1], parts[-1]


def build_patient_resource(data: dict[str, Any]) -> dict[str, Any]:
    """Constroi um Patient FHIR (perfil BRIndivíduo)."""
    given, family = split_name(data.get("nome", ""))
    cpf = clean_cpf(data.get("cpf", ""))

    resource: dict[str, Any] = {
        "resourceType": "Patient",
        "meta": {"profile": [BR_INDIVIDUO_PROFILE]},
        "identifier": [{"use": "official", "system": CPF_SYSTEM, "value": cpf}],
        "active": True,
        "name": [{"use": "official", "family": family, "given": given}],
        "gender": map_gender(data.get("genero")),
        "birthDate": parse_date(data.get("data_nascimento")),
    }

    telefone = (data.get("telefone") or "").strip()
    if telefone:
        resource["telecom"] = [{"system": "phone", "value": telefone, "use": "mobile"}]

    pais = (data.get("pais") or "").strip()
    if pais:
        resource["extension"] = [{"url": PATIENT_BIRTHPLACE_EXT, "valueAddress": {"country": pais}}]
    return resource


def patient_search_criteria(cpf_raw: str) -> str:
    """Criterio If-None-Exist para conditional create do Patient."""
    return f"identifier={CPF_SYSTEM}|{clean_cpf(cpf_raw)}"


def build_condition_resource(patient_ref: str, obs_key: str) -> dict[str, Any] | None:
    """Constroi um Condition FHIR; retorna None se obs_key nao for conhecido."""
    info = OBSERVATION_MAP.get(obs_key)
    if info is None:
        return None
    return {
        "resourceType": "Condition",
        "clinicalStatus": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                    "code": "active",
                    "display": "Active",
                }
            ]
        },
        "verificationStatus": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                    "code": "confirmed",
                    "display": "Confirmed",
                }
            ]
        },
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/condition-category",
                        "code": "problem-list-item",
                        "display": "Problem List Item",
                    }
                ]
            }
        ],
        "code": {
            "coding": [
                {
                    "system": SNOMED_SYSTEM,
                    "code": info["snomed_code"],
                    "display": info["snomed_display"],
                },
                {
                    "system": ICD10_SYSTEM,
                    "code": info["icd10_code"],
                    "display": info["icd10_display"],
                },
            ],
            "text": info["text"],
        },
        "subject": {"reference": patient_ref},
    }


def condition_search_criteria(patient_ref: str, snomed_code: str) -> str:
    return f"subject={patient_ref}&code={SNOMED_SYSTEM}|{snomed_code}"


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------


class FHIRError(RuntimeError):
    """Erro definitivo apos esgotar retries."""

    def __init__(self, message: str, status_code: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def build_session(max_retries: int = 5, backoff_factor: float = 0.5) -> requests.Session:
    """Cria uma Session com Retry policy para erros transientes.

    Retry em: 429, 500, 502, 503, 504 + ConnectionError.
    Backoff: backoff_factor * (2 ** attempt) com jitter via urllib3.
    """
    retry = Retry(
        total=max_retries,
        connect=max_retries,
        read=max_retries,
        backoff_factor=backoff_factor,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST", "PUT", "DELETE"]),
        raise_on_status=False,
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=20)
    session = requests.Session()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update(FHIR_HEADERS)
    return session


def post_resource(
    session: requests.Session,
    base_url: str,
    resource: dict[str, Any],
    *,
    if_none_exist: str | None = None,
    timeout: float = 30.0,
) -> tuple[dict[str, Any], bool]:
    """POST /fhir/{ResourceType} com optional conditional create.

    Retorna (body_json, created):
      - 201 created  -> (body, True)
      - 200 already  -> (body, False)
      - else         -> raise FHIRError (apos retries da Session)
    """
    rtype = resource["resourceType"]
    url = f"{base_url.rstrip('/')}/{rtype}"
    headers = dict(FHIR_HEADERS)
    if if_none_exist:
        headers["If-None-Exist"] = if_none_exist

    resp = session.post(url, json=resource, headers=headers, timeout=timeout)

    if resp.status_code == 201:
        return resp.json(), True
    if resp.status_code == 200:
        return resp.json(), False

    body_preview = resp.text[:500] if resp.text else ""
    raise FHIRError(
        f"POST {rtype} falhou: HTTP {resp.status_code}",
        status_code=resp.status_code,
        body=body_preview,
    )


def wait_for_fhir(
    session: requests.Session,
    base_url: str,
    *,
    attempts: int = 30,
    delay: float = 2.0,
    timeout: float = 5.0,
) -> None:
    """Polling em /metadata ate ficar 200 OK ou esgotar tentativas."""
    import time

    url = f"{base_url.rstrip('/')}/metadata"
    for attempt in range(1, attempts + 1):
        try:
            resp = session.get(url, timeout=timeout)
            if resp.status_code == 200:
                logger.info(
                    "FHIR server pronto",
                    extra={"event": "fhir_ready", "attempt": attempt, "url": url},
                )
                return
        except requests.RequestException as exc:
            logger.debug("FHIR ainda nao pronto", extra={"attempt": attempt, "error": str(exc)})
        time.sleep(delay)
    raise FHIRError(f"Servidor FHIR indisponivel apos {attempts} tentativas em {url}")
