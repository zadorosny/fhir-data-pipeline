"""Testes dos builders de Resources FHIR."""

from __future__ import annotations

import pytest

from etl.lib.fhir import (
    BR_INDIVIDUO_PROFILE,
    CPF_SYSTEM,
    ICD10_SYSTEM,
    OBSERVATION_MAP,
    SNOMED_SYSTEM,
    build_condition_resource,
    build_patient_resource,
    condition_search_criteria,
    patient_search_criteria,
)


PATIENT_DATA = {
    "nome": "Maria Souza",
    "cpf": "987.654.321-01",
    "genero": "Feminino",
    "data_nascimento": "15/08/1992",
    "telefone": "(21) 9876-5432",
    "pais": "Brasil",
    "observacao": "Gestante",
}


def test_build_patient_resource_estrutura_basica() -> None:
    p = build_patient_resource(PATIENT_DATA)
    assert p["resourceType"] == "Patient"
    assert p["active"] is True
    assert p["meta"]["profile"] == [BR_INDIVIDUO_PROFILE]


def test_build_patient_identifier_cpf_normalizado() -> None:
    p = build_patient_resource(PATIENT_DATA)
    ident = p["identifier"][0]
    assert ident["system"] == CPF_SYSTEM
    assert ident["value"] == "98765432101"
    assert ident["use"] == "official"


def test_build_patient_name_split() -> None:
    p = build_patient_resource(PATIENT_DATA)
    name = p["name"][0]
    assert name["family"] == "Souza"
    assert name["given"] == ["Maria"]


def test_build_patient_gender_e_birthdate() -> None:
    p = build_patient_resource(PATIENT_DATA)
    assert p["gender"] == "female"
    assert p["birthDate"] == "1992-08-15"


def test_build_patient_telecom_quando_telefone_presente() -> None:
    p = build_patient_resource(PATIENT_DATA)
    assert p["telecom"] == [
        {"system": "phone", "value": "(21) 9876-5432", "use": "mobile"}
    ]


def test_build_patient_sem_telefone_nao_inclui_telecom() -> None:
    data = {**PATIENT_DATA, "telefone": ""}
    p = build_patient_resource(data)
    assert "telecom" not in p


def test_build_patient_birthplace_extension() -> None:
    p = build_patient_resource(PATIENT_DATA)
    ext = p["extension"][0]
    assert ext["url"] == "http://hl7.org/fhir/StructureDefinition/patient-birthPlace"
    assert ext["valueAddress"]["country"] == "Brasil"


def test_build_patient_sem_pais_nao_inclui_extension() -> None:
    data = {**PATIENT_DATA, "pais": ""}
    p = build_patient_resource(data)
    assert "extension" not in p


def test_patient_search_criteria() -> None:
    criteria = patient_search_criteria("123.456.789-00")
    assert criteria == f"identifier={CPF_SYSTEM}|12345678900"


# ---------------------------------------------------------------------------
# Condition
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("obs_key", list(OBSERVATION_MAP.keys()))
def test_build_condition_resource_para_cada_observacao_conhecida(obs_key: str) -> None:
    info = OBSERVATION_MAP[obs_key]
    cond = build_condition_resource("Patient/abc-123", obs_key)
    assert cond is not None
    assert cond["resourceType"] == "Condition"
    assert cond["subject"] == {"reference": "Patient/abc-123"}

    coding = cond["code"]["coding"]
    snomed = next(c for c in coding if c["system"] == SNOMED_SYSTEM)
    icd10 = next(c for c in coding if c["system"] == ICD10_SYSTEM)
    assert snomed["code"] == info["snomed_code"]
    assert icd10["code"] == info["icd10_code"]


def test_build_condition_obs_desconhecida_retorna_none() -> None:
    assert build_condition_resource("Patient/xyz", "Alergico") is None


def test_condition_status_e_categoria() -> None:
    cond = build_condition_resource("Patient/1", "Diabético")
    assert cond is not None
    assert cond["clinicalStatus"]["coding"][0]["code"] == "active"
    assert cond["verificationStatus"]["coding"][0]["code"] == "confirmed"
    assert cond["category"][0]["coding"][0]["code"] == "problem-list-item"


def test_condition_search_criteria() -> None:
    criteria = condition_search_criteria("Patient/abc", "77386006")
    assert criteria == f"subject=Patient/abc&code={SNOMED_SYSTEM}|77386006"
