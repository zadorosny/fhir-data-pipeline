"""
Consumer: Lê mensagens do tópico Kafka 'fhir-patients'
e carrega os Resources Patient e Condition no HAPI FHIR.

Utiliza conditional create (If-None-Exist) para idempotência:
re-execuções não geram duplicatas.
"""

import json
import os
import time
from datetime import datetime

import requests
from kafka import KafkaConsumer

KAFKA_BROKER = os.getenv("KAFKA_BROKER", "kafka:9092")
FHIR_BASE = os.getenv("FHIR_BASE", "http://hapi-fhir:8080/fhir")
TOPIC = os.getenv("KAFKA_TOPIC", "fhir-patients")
CONSUMER_TIMEOUT_MS = int(os.getenv("CONSUMER_TIMEOUT_MS", "15000"))

HEADERS = {
    "Content-Type": "application/fhir+json",
    "Accept": "application/fhir+json",
}

BR_INDIVIDUO_PROFILE = (
    "http://www.saude.gov.br/fhir/r4/StructureDefinition/BRIndividuo-1.0"
)
CPF_SYSTEM = "http://rnds-fhir.saude.gov.br/fhir/r4/NamingSystem/cpf"

OBSERVATION_MAP = {
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


def parse_date(date_str: str) -> str:
    try:
        return datetime.strptime(date_str.strip(), "%d/%m/%Y").strftime("%Y-%m-%d")
    except (ValueError, AttributeError):
        return "1900-01-01"


def clean_cpf(cpf: str) -> str:
    return cpf.replace(".", "").replace("-", "").strip()


def map_gender(genero: str) -> str:
    g = genero.strip().lower()
    if g == "masculino":
        return "male"
    elif g == "feminino":
        return "female"
    return "unknown"


def build_patient(data: dict) -> dict:
    parts = data["nome"].strip().split()
    given = parts[:-1] if len(parts) > 1 else parts
    family = parts[-1] if len(parts) > 1 else ""

    return {
        "resourceType": "Patient",
        "meta": {"profile": [BR_INDIVIDUO_PROFILE]},
        "identifier": [
            {"use": "official", "system": CPF_SYSTEM, "value": clean_cpf(data["cpf"])}
        ],
        "active": True,
        "name": [{"use": "official", "family": family, "given": given}],
        "gender": map_gender(data["genero"]),
        "birthDate": parse_date(data["data_nascimento"]),
        "telecom": [{"system": "phone", "value": data["telefone"].strip(), "use": "mobile"}],
        "extension": [
            {
                "url": "http://hl7.org/fhir/StructureDefinition/patient-birthPlace",
                "valueAddress": {"country": data["pais"].strip()},
            }
        ],
    }


def build_condition(patient_ref: str, obs_key: str) -> dict | None:
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
                    "system": "http://snomed.info/sct",
                    "code": info["snomed_code"],
                    "display": info["snomed_display"],
                },
                {
                    "system": "http://hl7.org/fhir/sid/icd-10",
                    "code": info["icd10_code"],
                    "display": info["icd10_display"],
                },
            ],
            "text": info["text"],
        },
        "subject": {"reference": patient_ref},
    }


def wait_for_fhir():
    """Aguarda o servidor FHIR estar disponível."""
    for attempt in range(30):
        try:
            resp = requests.get(f"{FHIR_BASE}/metadata", timeout=5)
            if resp.status_code == 200:
                print(f"  FHIR disponível (tentativa {attempt + 1})")
                return
        except requests.ConnectionError:
            pass
        time.sleep(2)
    raise RuntimeError("Servidor FHIR não disponível após 60 segundos")


def post_resource(resource: dict, if_none_exist: str | None = None) -> tuple[dict | None, bool]:
    """Cria resource no FHIR. Retorna (resource, criado).

    Com if_none_exist (conditional create):
      - 201: recurso criado (novo)
      - 200: recurso já existia (skip)
    """
    rtype = resource["resourceType"]
    url = f"{FHIR_BASE}/{rtype}"
    headers = HEADERS.copy()
    if if_none_exist:
        headers["If-None-Exist"] = if_none_exist

    resp = requests.post(url, json=resource, headers=headers, timeout=30)
    if resp.status_code == 201:
        return resp.json(), True
    if resp.status_code == 200:
        return resp.json(), False
    print(f"  ERRO {resp.status_code} ao criar {rtype}: {resp.text[:300]}")
    return None, False


def main():
    print("=" * 60)
    print("CONSUMER — Kafka → HAPI FHIR")
    print(f"  KAFKA_BROKER : {KAFKA_BROKER}")
    print(f"  FHIR_BASE    : {FHIR_BASE}")
    print(f"  TOPIC        : {TOPIC}")
    print("=" * 60)

    wait_for_fhir()

    consumer = KafkaConsumer(
        TOPIC,
        bootstrap_servers=KAFKA_BROKER,
        auto_offset_reset="earliest",
        consumer_timeout_ms=CONSUMER_TIMEOUT_MS,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
    )

    patients_ok = 0
    patients_skip = 0
    conditions_ok = 0
    conditions_skip = 0
    errors = 0

    for message in consumer:
        data = message.value
        nome = data.get("nome", "?")
        cpf = clean_cpf(data.get("cpf", ""))
        print(f"\n[offset {message.offset}] {nome}")

        patient = build_patient(data)
        condition_criteria = f"identifier={CPF_SYSTEM}|{cpf}"
        result, created = post_resource(patient, if_none_exist=condition_criteria)
        if result is None:
            errors += 1
            continue
        patient_ref = f"Patient/{result['id']}"
        if created:
            patients_ok += 1
        else:
            patients_skip += 1
            print(f"  Paciente já existe: {patient_ref}")

        obs = data.get("observacao", "").strip()
        if obs:
            for obs_key in obs.split("|"):
                obs_key = obs_key.strip()
                if not obs_key:
                    continue
                info = OBSERVATION_MAP.get(obs_key)
                if not info:
                    continue
                cond = build_condition(patient_ref, obs_key)
                if cond:
                    cond_criteria = f"subject={patient_ref}&code=http://snomed.info/sct|{info['snomed_code']}"
                    r, cond_created = post_resource(cond, if_none_exist=cond_criteria)
                    if r:
                        if cond_created:
                            conditions_ok += 1
                        else:
                            conditions_skip += 1
                            print(f"  Condition já existe: {obs_key}")
                    else:
                        errors += 1

    consumer.close()

    print("\n" + "=" * 60)
    print("RESUMO DA CARGA")
    print("=" * 60)
    print(f"  Pacientes criados (Patient):    {patients_ok}")
    print(f"  Pacientes existentes (skip):    {patients_skip}")
    print(f"  Condições criadas (Condition):   {conditions_ok}")
    print(f"  Condições existentes (skip):     {conditions_skip}")
    print(f"  Erros:                           {errors}")
    print("=" * 60)


if __name__ == "__main__":
    main()
