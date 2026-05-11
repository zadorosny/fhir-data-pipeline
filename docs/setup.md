# Setup detalhado

> Este documento descreve cada componente do `docker-compose.yml`. Para visão de mais alto nível, veja [architecture.md](architecture.md). Para deploy em produção, [deployment.md](deployment.md). Para problemas comuns, [troubleshooting.md](troubleshooting.md).

## Pré-requisitos

- Docker Engine 24+ e Docker Compose v2
- Portas livres: 5432, 8001, 8080, 8081, 9091, 9092 (e 3000/9090 com profile `monitoring`)

## Configuração inicial (`.env`)

```bash
cp .env.example .env
```

Variáveis **obrigatórias** (compose falha sem elas):

| Variável                            | O que é                                       |
|-------------------------------------|-----------------------------------------------|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Owner do banco; usado pelo HAPI |
| `AIRFLOW_DB_USER` / `AIRFLOW_DB_PASSWORD`             | Role dedicada para o Airflow (menor privilégio) |
| `AIRFLOW_ADMIN_USER` / `AIRFLOW_ADMIN_PASSWORD`       | Login do painel Airflow                       |
| `AIRFLOW__CORE__FERNET_KEY`                           | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `AIRFLOW__WEBSERVER__SECRET_KEY`                      | `openssl rand -hex 32`                        |

Variáveis **opcionais** (têm defaults razoáveis): portas, retries, timeouts, level de log, webhook de alerta. Veja `.env.example`.

## Componentes

### PostgreSQL

- Imagem: `postgres:15`.
- Volume nomeado `pgdata` mantém os dados entre restarts.
- O script `postgres/init-db.sh` roda **uma única vez** no primeiro start (volume vazio):
  - Cria a role `airflow_user` com senha do `.env`
  - Cria o schema `airflow` com `AUTHORIZATION airflow_user`
  - Define `search_path` da role para `airflow`
- HAPI usa o schema `public` (auto-DDL via Hibernate); Airflow usa o schema `airflow` via `airflow_user`.

### HAPI FHIR

- Imagem: `hapiproject/hapi:latest`.
- Config: `hapi/application.yaml` montado em `/app/config/application.yaml`.
- Conexão JDBC: `SPRING_DATASOURCE_URL/USERNAME/PASSWORD` vêm do compose via env (Spring placeholders no YAML).
- Flyway desabilitado (`spring.flyway.enabled: false`); schema é criado pelo Hibernate auto-DDL.
- Healthcheck `curl -sf /fhir/metadata` com `start_period: 60s`.

### Kafka

- Imagem: `apache/kafka:3.8.0` em modo KRaft (sem ZooKeeper).
- Tópicos auto-criados (`KAFKA_AUTO_CREATE_TOPICS_ENABLE=true`).
- Healthcheck via `kafka-topics --list`.

### Kafka UI

- Imagem: `provectuslabs/kafka-ui`, porta 9091.
- Útil para inspecionar a `fhir-patients-dlq` em caso de falhas.

### Airflow

- Imagem: `apache/airflow:2.10.0-python3.12`, `LocalExecutor`.
- Webserver e scheduler no mesmo container (OK para dev; ver `docs/deployment.md` para escalar).
- Bootstrap: `airflow db init` + `airflow users create` (lê `AIRFLOW_ADMIN_*` do env).
- DAG `fhir_patient_etl` é re-executável via UI/CLI; falhas chamam `alert_on_failure` (POST para `ALERT_WEBHOOK_URL`).
- ⚠️ Monta `/var/run/docker.sock` para acionar os ETLs via `docker start -a` — veja `docs/security.md`.

### ETL — Producer

- Build: `etl/Dockerfile` (Python 3.12 slim + JRE + `requirements.txt` pinado).
- Entry: `python -m etl.kafka_producer`.
- Lê `CSV_PATH` (`/opt/app/data/patients.csv` por default), normaliza colunas, publica em `KAFKA_TOPIC` com `acks=all`, `retries=5`, `max_in_flight=1`.
- Falha rápido se colunas obrigatórias não existirem (`ColumnMappingError`, exit 2).

### ETL — Consumer

- Mesma imagem do producer; entry: `python -m etl.kafka_consumer`.
- Polling em `/fhir/metadata` (parâmetros `HAPI_RETRY_ATTEMPTS`/`HAPI_RETRY_DELAY`).
- `requests.Session` + `urllib3.Retry` com backoff exponencial (5xx/429/conn errors).
- Conditional create com `If-None-Exist` para idempotência.
- Falha definitiva → publica no `KAFKA_DLQ_TOPIC` com headers `reason`, `status_code`, `body_preview`.
- Expõe `/metrics` em `METRICS_PORT` (8001 por default) com `fhir_consumer_messages_total`, `fhir_consumer_post_latency_seconds`, `fhir_consumer_dlq_total`.

## Como subir / parar

```bash
# Stack core
docker compose --env-file .env up -d --build
docker compose --env-file .env down            # mantém volumes
docker compose --env-file .env down -v         # zera volumes (Postgres + Kafka)

# Stack core + monitoring (Prometheus + Grafana)
docker compose -f docker-compose.yml -f docker-compose.observability.yml \
               --env-file .env --profile monitoring up -d
```

## Verificação rápida

```bash
docker compose ps                                   # status + healthchecks
docker compose logs --tail=50 etl-consumer          # carga concluída?
curl -fsS http://localhost:8080/fhir/Patient?_summary=count
curl -fsS http://localhost:8080/fhir/Condition?_summary=count
curl -fsS http://localhost:8001/metrics | grep fhir_consumer_messages_total
```

Resultado esperado para o CSV de exemplo:

```
Patient   total: 50
Condition total: 15
DLQ       total: 0
```

## Re-executar via Airflow

1. Abra http://localhost:8081 (login com `AIRFLOW_ADMIN_USER` / `AIRFLOW_ADMIN_PASSWORD`).
2. Acione a DAG `fhir_patient_etl`.
3. Tasks `kafka_producer` → `kafka_consumer` rodam em sequência. Como o consumer é idempotente, os totais não mudam — apenas linhas "exists" aparecem nos logs.

## Próximos passos

- Em produção: leia `docs/deployment.md` (secrets, backup, escala).
- Para entender o fluxo: `docs/architecture.md`.
- Para PHI / compliance: `docs/security.md`.
