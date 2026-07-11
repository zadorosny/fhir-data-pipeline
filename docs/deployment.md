# Deployment

Este documento cobre o que muda entre rodar localmente (dev) e operar em produção. O `docker-compose.yml` continua sendo a fonte de verdade — para Kubernetes/ECS, traduza serviço a serviço.

## Pré-requisitos

| Item                          | Mínimo                              |
|-------------------------------|-------------------------------------|
| Docker Engine                 | 24+                                 |
| Docker Compose                | v2                                  |
| Memória disponível            | 6 GB (HAPI 2 GB, Spark 1 GB, Kafka 1 GB, Postgres 512 MB) |
| Portas locais                 | 5432, 8001, 8080, 8081, 9091, 9092  |
| (Monitoring opcional)         | + 3000 (Grafana), 9090 (Prometheus) |

## Passos de deploy

```bash
git clone <repo> && cd fhir-data-pipeline

# 1. Provisione segredos (NUNCA commitar .env)
cp .env.example .env
python -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"  # -> AIRFLOW__CORE__FERNET_KEY
openssl rand -hex 32                                                                       # -> AIRFLOW__WEBSERVER__SECRET_KEY
# Edite .env e substitua todos os 'change-me-*'

# 2. Suba o stack
docker compose --env-file .env up -d --build

# 3. Verifique
curl -fsS http://localhost:8080/fhir/metadata | jq '.fhirVersion'
curl -fsS http://localhost:8001/metrics | head -5
```

## Secrets management

- **Local/dev**: arquivo `.env` (já no `.gitignore`).
- **CI**: `secrets.*` do GitHub Actions. Veja `.github/workflows/ci.yml`.
- **Produção**: integrar com AWS Secrets Manager, Vault, GCP Secret Manager ou Doppler. Injete via `env_file:` ou `secrets:` block do compose, ou via `external_secrets` no Kubernetes.
- **Rotação**: trocar `AIRFLOW__CORE__FERNET_KEY` invalida senhas de connections; siga o [procedimento oficial](https://airflow.apache.org/docs/apache-airflow/stable/security/secrets/fernet.html) (re-encrypt com chave antiga + nova).

## Backup do Postgres

```bash
# Snapshot lógico (compatível entre versões)
docker compose exec postgres pg_dump -U "$POSTGRES_USER" -Fc -d "$POSTGRES_DB" > backup-$(date +%F).pgdump

# Restore
docker compose exec -T postgres pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists < backup-YYYY-MM-DD.pgdump
```

Volume `pgdata` é nomeado — para mover entre hosts use `docker volume create` + `docker run --rm -v pgdata:/from -v $(pwd):/to alpine tar czf /to/pgdata.tgz -C /from .`.

## Escalonamento

### HAPI FHIR
- Vertical: aumente `JAVA_OPTS=-Xmx4g` no serviço `hapi-fhir`.
- Horizontal: HAPI é stateless contra o Postgres; replique atrás de um load balancer e aponte todos para o mesmo banco. Use `hapi.fhir.subscription.resthook_enabled=false` se múltiplas réplicas (subscription state precisa de lock).

### Kafka
- Single broker no compose é OK até ~10k msg/s. Em produção, suba 3+ brokers e configure `replication.factor=3` no tópico.

### Consumer
- Para paralelizar, suba múltiplas réplicas do `etl-consumer` no mesmo `consumer_group` (kafka-python-ng usa `group.id`). Adicione partições ao tópico (`kafka-topics --alter --partitions 6`).
- Crie um `consumer_group` explícito em `etl/lib/config.py` (atualmente nenhum é definido — kafka-python-ng usa um random; em produção, fixe).

### Airflow
- `LocalExecutor` cabe em uma máquina. Para múltiplos workers, migre para `CeleryExecutor` com Redis broker, ou `KubernetesExecutor` (e remova o mount do docker.sock — veja `docs/security.md`).

## Health checks externos

| Endpoint                              | Espera-se                       |
|---------------------------------------|---------------------------------|
| `GET http://host:8080/fhir/metadata`  | 200 com `CapabilityStatement`   |
| `GET http://host:8001/metrics`        | 200 com `fhir_consumer_*`       |
| `GET http://host:8081/health`         | 200 do Airflow                  |
| `pg_isready -h host -U $POSTGRES_USER`| ready                           |

Aponte seu sistema de monitoramento (Pingdom, Datadog Synthetics) para esses endpoints.

## Stack de monitoring (opcional)

```bash
docker compose -f docker-compose.yml -f docker-compose.observability.yml \
               --profile monitoring up -d
```

- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000 (admin / `${GRAFANA_ADMIN_PASSWORD}`)
- Dashboard "FHIR Consumer" já provisionado.

## Migração de volumes

⚠️ A separação da role `airflow_user` (`postgres/init-db.sh`) só acontece no primeiro start do container Postgres (volume vazio). Para aplicar em ambientes já existentes:

```bash
docker compose down
docker compose exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "CREATE ROLE airflow_user LOGIN PASSWORD '${AIRFLOW_DB_PASSWORD}';
      ALTER SCHEMA airflow OWNER TO airflow_user;
      GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO airflow_user;
      GRANT USAGE, CREATE ON SCHEMA airflow TO airflow_user;
      ALTER ROLE airflow_user SET search_path TO airflow;"
docker compose up -d
```
