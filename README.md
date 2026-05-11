# FHIR Data Pipeline

[![CI](https://github.com/zadorosny/fhir-data-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/zadorosny/fhir-data-pipeline/actions/workflows/ci.yml)
[![Security](https://github.com/zadorosny/fhir-data-pipeline/actions/workflows/security.yml/badge.svg)](https://github.com/zadorosny/fhir-data-pipeline/actions/workflows/security.yml)

Pipeline ETL com Kafka + PySpark que carrega pacientes (CSV) em um servidor HAPI FHIR R4, orquestrado por Airflow e empacotado em Docker Compose.

- **Servidor FHIR R4** local (HAPI FHIR) com persistência em PostgreSQL
- **ETL** PySpark → Kafka → consumer Python → POST `/fhir`
- **Orquestração** com Airflow (DAG re-executável + idempotente)
- **Observabilidade**: métricas Prometheus + dashboard Grafana opcional
- **DLQ**: falhas definitivas vão para `fhir-patients-dlq` com diagnóstico em headers

## Documentação

| Documento                                | Conteúdo                                                  |
|------------------------------------------|------------------------------------------------------------|
| [docs/architecture.md](docs/architecture.md) | Diagrama, fluxo de dados, idempotência                 |
| [docs/setup.md](docs/setup.md)           | Configuração dos serviços                                  |
| [docs/deployment.md](docs/deployment.md) | Deploy em produção, backup, escalonamento                  |
| [docs/security.md](docs/security.md)     | Modelo de ameaças, rotação de segredos, docker.sock        |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Sintomas → causas → fixes                        |
| [docs/message-schema.json](docs/message-schema.json) | JSON Schema das mensagens Kafka                |

## Stack

| Serviço        | Imagem                              | Porta default | Descrição                                |
|----------------|-------------------------------------|---------------|------------------------------------------|
| PostgreSQL     | `postgres:15`                       | 5432          | HAPI (schema `public`) + Airflow (schema `airflow`, role dedicada) |
| HAPI FHIR      | `hapiproject/hapi:latest`           | 8080          | Servidor FHIR R4                         |
| Kafka (KRaft)  | `apache/kafka:3.8.0`                | 9092          | Tópicos: `fhir-patients` + `fhir-patients-dlq` |
| Kafka UI**     | `provectuslabs/kafka-ui`            | 9091          | Inspeção visual de tópicos (opcional)    |
| Airflow        | `apache/airflow:2.10.0-python3.12`  | 8081          | DAG `fhir_patient_etl`                   |
| Producer       | build local (`etl/`)                | —             | PySpark CSV → Kafka                      |
| Consumer       | build local (`etl/`)                | 8001 metrics  | Kafka → HAPI com retries + DLQ           |
| Prometheus*    | `prom/prometheus`                   | 9090          | Scrape do consumer (opcional)            |
| Grafana*       | `grafana/grafana`                   | 3000          | Dashboard provisionado (opcional)        |

`*` requer `--profile monitoring` + `docker-compose.observability.yml`.
`**` requer `--profile debug` — UI administrativa do Kafka sem autenticação, fora por default.

## Quickstart

```bash
git clone https://github.com/zadorosny/fhir-data-pipeline.git
cd fhir-data-pipeline

# 1. Configurar segredos (NUNCA commitar .env)
cp .env.example .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
openssl rand -hex 32
# Edite .env e substitua os 'change-me-*' (incluindo as duas chaves geradas acima).

# 2. Subir o stack
docker compose --env-file .env up -d --build

# 3. Verificar
curl -fsS http://localhost:8080/fhir/Patient?_summary=count   # total de Patients
curl -fsS http://localhost:8001/metrics | grep fhir_consumer  # métricas do consumer
```

⚠️ **As credenciais de `.env.example` são placeholders explícitos (`change-me-*`)**. O compose **falha intencionalmente** se você não trocar — todas as variáveis sensíveis usam a sintaxe `${VAR:?msg}`.

## Como funciona

```
CSV  →  PySpark (producer)  →  Kafka 'fhir-patients'  →  Consumer  →  POST /fhir/Patient + /fhir/Condition
                                                              │
                                                              └─ falha definitiva → Kafka 'fhir-patients-dlq'
```

1. **Producer** lê `data/patients.csv` (ISO-8859-1), normaliza cabeçalhos com acentos/BOM e publica uma mensagem JSON por linha. Aborta se faltar coluna (`ColumnMappingError`).
2. **Consumer** usa `If-None-Exist` para conditional create — re-executar o DAG não duplica recursos.
3. Falhas transientes (429/5xx/conn) reentregam até 5×; falhas definitivas vão para a DLQ com `reason`, `status_code`, `body_preview` nos headers.

## Idempotência (detalhes)

| Resource    | Critério de busca                                                |
|-------------|------------------------------------------------------------------|
| `Patient`   | `identifier=http://rnds-fhir.saude.gov.br/fhir/r4/NamingSystem/cpf\|<cpf>` |
| `Condition` | `subject=Patient/<id>&code=http://snomed.info/sct\|<snomed_code>` |

- HTTP 201 → criado; HTTP 200 → já existia. O consumer trata os dois casos.
- O CSV é considerado dataset-fonte estável: re-rodar o DAG sobre o mesmo CSV produz o mesmo conjunto de recursos.

## Mapeamento FHIR

### CSV → `Patient` (perfil BRIndivíduo)

| Coluna CSV           | Campo FHIR             | Observação                                       |
|----------------------|------------------------|--------------------------------------------------|
| Nome                 | `Patient.name`         | Última palavra como `family`, demais como `given`|
| CPF                  | `Patient.identifier`   | `NamingSystem/cpf` da RNDS                       |
| Gênero               | `Patient.gender`       | Masculino → `male`, Feminino → `female`, Outro → `other` |
| Data de Nascimento   | `Patient.birthDate`    | `DD/MM/AAAA` → `AAAA-MM-DD`                      |
| Telefone             | `Patient.telecom`      | `system=phone, use=mobile` (omitido se vazio)    |
| País de Nascimento   | `Patient.extension`    | `patient-birthPlace` (omitido se vazio)          |

### Observação → `Condition`

| Token        | SNOMED CT  | ICD-10 | Descrição                       |
|--------------|------------|--------|---------------------------------|
| Gestante     | 77386006   | Z33    | Pregnant (finding)              |
| Diabético    | 73211009   | E14    | Diabetes mellitus (disorder)    |
| Hipertenso   | 38341003   | I10    | Hypertensive disorder           |

Valores compostos (`Diabético|Hipertenso`) geram múltiplos `Condition` ligados ao mesmo `Patient`.

## Desenvolvimento

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pre-commit install

pytest -m "not integration"                     # unit tests (87% coverage em etl/lib)
ruff check . && black --check . && mypy etl/lib # lint + types

pytest -m integration                           # sobe compose e valida HAPI (~5min)
```

## Airflow

- UI: http://localhost:8081 (`$AIRFLOW_ADMIN_USER` / `$AIRFLOW_ADMIN_PASSWORD`).
- DAG `fhir_patient_etl`: dispara `kafka_producer` → `kafka_consumer` (re-executável).
- Falhas chamam `alert_on_failure` que POSTa para `ALERT_WEBHOOK_URL` (Slack/Teams), se configurado.

## Estrutura

```
.
├── airflow/dags/fhir_etl_dag.py        # DAG re-executável + on_failure_callback
├── data/patients.csv                    # 50 pacientes de exemplo (ISO-8859-1)
├── docs/                                # Arquitetura, deploy, segurança, troubleshooting
├── etl/
│   ├── Dockerfile                       # Python 3.12 slim + JRE + requirements pinados
│   ├── requirements.txt                 # pyspark, kafka-python-ng, requests, prometheus-client...
│   ├── kafka_producer.py                # CSV → Kafka (acks=all, retries=5)
│   ├── kafka_consumer.py                # Kafka → HAPI com retries e DLQ; expõe /metrics
│   └── lib/                             # config, transform, fhir, dlq, metrics, logging
├── hapi/application.yaml                # Configuração do HAPI (env placeholders)
├── observability/                       # Prometheus + dashboards Grafana
├── postgres/init-db.sh                  # Cria schema airflow + role airflow_user (menor privilégio)
├── tests/                               # 67 testes unit + 3 integration
├── docker-compose.yml                   # Stack core
├── docker-compose.observability.yml     # Prometheus + Grafana (profile monitoring)
├── pyproject.toml                       # ruff/black/mypy/pytest config
├── requirements-dev.txt                 # Lint + test + types
├── .env.example                         # Template de segredos (NÃO commitar .env)
├── .github/workflows/{ci,security}.yml  # GitHub Actions
├── .github/dependabot.yml               # Updates semanais
└── .pre-commit-config.yaml              # ruff, black, mypy, detect-secrets
```
