# FHIR Data Pipeline

O projeto implementa:
- **Servidor FHIR R4** local (HAPI FHIR) com persistência em PostgreSQL
- **Pipeline ETL com PySpark e Kafka** para carga dos dados de pacientes no servidor FHIR
- **Orquestração** com Docker Compose e Airflow

---

## Arquitetura

```
                              docker-compose
  ┌──────────────────────────────────────────────────────────────────┐
  │                                                                  │
  │  ┌──────────┐    ┌──────────────┐    ┌───────────────────────┐  │
  │  │PostgreSQL │◄──►│  HAPI FHIR   │    │        Kafka          │  │
  │  │  :5432    │    │  :8080       │    │  :9092  (UI :9091)    │  │
  │  └──────────┘    └──────┬───────┘    └───────┬───────────────┘  │
  │       ▲                 ▲                    │  ▲                │
  │       │                 │  POST /fhir/*      │  │ publish       │
  │  ┌────┴─────┐    ┌─────┴──────────┐   ┌─────┴──┴────────┐     │
  │  │ Airflow  │    │   Consumer     │   │   Producer       │     │
  │  │  :8081   │    │  (kafka→fhir)  │   │ (csv→kafka)      │     │
  │  │          │    │                │   │   PySpark         │     │
  │  └──────────┘    └────────────────┘   └──────────────────┘     │
  │                                                                  │
  └──────────────────────────────────────────────────────────────────┘
```

### Fluxo do pipeline

```
CSV  →  PySpark (Producer)  →  Kafka (tópico fhir-patients)  →  Consumer  →  HAPI FHIR
```

1. O **Producer** (PySpark) lê o CSV e publica cada paciente como mensagem JSON no tópico Kafka
2. O **Consumer** lê as mensagens do Kafka, constrói os Resources FHIR e envia via POST para o HAPI

## Stack

| Serviço    | Imagem                             | Porta | Descrição                               |
|------------|------------------------------------|-------|-----------------------------------------|
| PostgreSQL | `postgres:15`                      | 5432  | Banco de dados do HAPI e do Airflow     |
| HAPI FHIR  | `hapiproject/hapi:latest`          | 8080  | Servidor FHIR R4                        |
| Kafka      | `apache/kafka:3.8.0`               | 9092  | Broker de mensagens (modo KRaft)        |
| Kafka UI   | `provectuslabs/kafka-ui:latest`    | 9091  | Interface web para visualização do Kafka|
| Airflow    | `apache/airflow:2.10.0-python3.12` | 8081  | Orquestrador de workflows               |
| Producer   | Build local (`etl/Dockerfile`)     | —     | PySpark: CSV → Kafka                    |
| Consumer   | Build local (`etl/Dockerfile`)     | —     | Kafka → HAPI FHIR                       |
| hapi-ready | `curlimages/curl:8.10.1`           | —     | Aguarda o HAPI ficar disponível         |

## Pré-requisitos

- [Docker](https://docs.docker.com/get-docker/) e [Docker Compose](https://docs.docker.com/compose/install/) instalados
- Portas **5432**, **8080**, **8081**, **9091** e **9092** disponíveis

## Como executar

```bash
# 1. Clonar o repositório
git clone https://github.com/zadorosny/fhir-data-pipeline.git
cd fhir-data-pipeline

# 2. Subir todos os serviços (build + start)
docker-compose up -d --build

# 3. Acompanhar o Producer (CSV → Kafka)
docker logs -f fhir_producer

# 4. Acompanhar o Consumer (Kafka → HAPI FHIR)
docker logs -f fhir_consumer
```

O container `hapi-ready` faz polling até o HAPI responder em `/fhir/metadata`. Só então o Producer inicia, publica as 50 mensagens no Kafka, e em seguida o Consumer consome e carrega no HAPI FHIR.

## Verificando o pipeline

### Kafka UI

Acesse http://localhost:9091 para ver o tópico `fhir-patients` com as 50 mensagens publicadas pelo Producer.

### HAPI FHIR

```bash
# Total de pacientes (deve ser 50)
curl http://localhost:8080/fhir/Patient?_summary=count

# Total de condições clínicas (deve ser 15)
curl http://localhost:8080/fhir/Condition?_summary=count

# Buscar paciente por CPF
curl "http://localhost:8080/fhir/Patient?identifier=12345678900"

# Listar condições clínicas
curl http://localhost:8080/fhir/Condition
```

### Logs dos containers

```bash
# Producer: deve mostrar "Publicadas 50 mensagens no tópico 'fhir-patients'"
docker logs fhir_producer

# Consumer: deve mostrar "Pacientes criados: 50 / Condições criadas: 15 / Erros: 0"
docker logs fhir_consumer
```

## Mapeamento FHIR

### CSV → Resource Patient (perfil BRIndivíduo)

| Coluna CSV           | Campo FHIR                     | Observação                                 |
|----------------------|--------------------------------|--------------------------------------------|
| Nome                 | `Patient.name`                 | Último sobrenome como `family`, demais como `given` |
| CPF                  | `Patient.identifier`           | System: `NamingSystem/cpf` da RNDS         |
| Gênero               | `Patient.gender`               | Masculino → `male`, Feminino → `female`    |
| Data de Nascimento   | `Patient.birthDate`            | Convertido de DD/MM/AAAA para AAAA-MM-DD   |
| Telefone             | `Patient.telecom`              | `system: phone`, `use: mobile`             |
| País de Nascimento   | `Patient.extension`            | Extensão `patient-birthPlace`              |

### Coluna Observação → Resource Condition

| Valor          | SNOMED CT  | ICD-10 | Descrição                        |
|----------------|-----------|--------|----------------------------------|
| Gestante       | 77386006  | Z33    | Pregnant (finding)               |
| Diabético      | 73211009  | E14    | Diabetes mellitus (disorder)     |
| Hipertenso     | 38341003  | I10    | Hypertensive disorder (disorder) |

Valores compostos (ex: `Diabético|Hipertenso`) geram múltiplos Resources `Condition` vinculados ao mesmo `Patient`.

## Perfil BRIndivíduo (Bônus)

O pipeline utiliza o perfil **BRIndivíduo** da RNDS (Rede Nacional de Dados em Saúde):

- **Profile**: `http://www.saude.gov.br/fhir/r4/StructureDefinition/BRIndividuo-1.0`
- **CPF System**: `http://rnds-fhir.saude.gov.br/fhir/r4/NamingSystem/cpf`
- **Referência**: https://simplifier.net/redenacionaldedadosemsaude/brindividuo

## Airflow

Acesse o painel em http://localhost:8081 com as credenciais:

- **Usuário**: `admin`
- **Senha**: `admin`

A DAG `fhir_patient_etl` é disparada manualmente via UI ou CLI (`airflow dags trigger fhir_patient_etl`). O pipeline inicial roda automaticamente via Docker Compose; o Airflow permite **re-execuções sob demanda**. O Consumer é **idempotente**: verifica se o paciente (por CPF) e as condições já existem antes de criar, evitando duplicatas.

Tasks em sequência:
1. `kafka_producer` — executa o Producer (CSV → Kafka)
2. `kafka_consumer` — executa o Consumer (Kafka → HAPI FHIR)

## Estrutura do repositório

```
.
├── airflow/
│   └── dags/
│       └── fhir_etl_dag.py            # DAG do Airflow (producer → consumer)
├── data/
│   └── patients.csv                    # Dados de entrada (50 pacientes)
├── docs/
│   └── setup.md                        # Documentação detalhada da solução
├── etl/
│   ├── Dockerfile                      # Imagem Python + PySpark + JRE + kafka-python
│   ├── kafka_producer.py               # PySpark: CSV → Kafka
│   └── kafka_consumer.py               # Kafka → HAPI FHIR
├── hapi/
│   └── application.yaml                # Configuração do HAPI FHIR
├── postgres/
│   └── init-airflow.sql                # Script de inicialização do banco
├── docker-compose.yml                  # Orquestração de todos os serviços
├── .gitignore
└── README.md
```

## Decisões técnicas

1. **HAPI FHIR** — Implementação open-source mais madura para servidores FHIR R4.
2. **PostgreSQL 15** — Persistência robusta; compartilhado entre HAPI e Airflow com schemas separados.
3. **PySpark** — Leitura e transformação do CSV com processamento distribuído.
4. **Kafka** — Desacopla a produção (leitura do CSV) do consumo (carga no FHIR), permitindo reprocessamento e escalabilidade.
5. **Kafka UI** — Interface web para visualização de tópicos e mensagens.
6. **Condition para observações** — Resource FHIR adequado para diagnósticos e condições clínicas.
7. **Codificação dupla (SNOMED CT + ICD-10)** — Cada Condition inclui ambos os sistemas de codificação, garantindo interoperabilidade.
8. **Idempotência no Consumer** — Antes de criar Patient ou Condition, o Consumer verifica se o recurso já existe, permitindo re-execuções seguras via Airflow.
9. **hapi-ready sidecar** — Container auxiliar com `curl --retry` que garante que o pipeline só inicia quando o HAPI está de fato respondendo.
