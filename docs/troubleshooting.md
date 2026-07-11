# Troubleshooting

## Onde olhar primeiro

```bash
docker compose ps                 # status + healthchecks
docker compose logs --tail=100 hapi-fhir
docker compose logs --tail=100 etl-consumer
curl -fsS http://localhost:8001/metrics | grep fhir_consumer
```

## Sintoma → Causa → Fix

### `etl-producer` falha com `ColumnMappingError`
- **Causa**: O CSV mudou de cabeçalho (ex.: removeram acentos no template).
- **Fix**: Acrescente o novo alias em `CANONICAL_COLUMNS` em `etl/lib/transform.py:13-21` e adicione um teste em `tests/test_transform.py::test_build_column_map_*`.

### `etl-consumer` fica preso em "FHIR ainda nao pronto"
- **Causa**: HAPI demora mais que `HAPI_RETRY_ATTEMPTS * HAPI_RETRY_DELAY` (default 60s) para iniciar. Em máquina lenta, HAPI pode levar 90s+.
- **Fix**: Aumente `HAPI_RETRY_ATTEMPTS=60` no `.env`. Confirme com `docker compose logs hapi-fhir | grep "Started Application"`.

### `etl-consumer` reporta `patient_dlq` > 0
- **Causa**: Algum POST `/fhir/Patient` falhou em definitivo (4xx persistente, ex.: validação de perfil).
- **Diagnóstico**:
  ```bash
  docker compose exec kafka /opt/kafka/bin/kafka-console-consumer.sh \
    --bootstrap-server localhost:9092 --topic fhir-patients-dlq \
    --from-beginning --property print.headers=true
  ```
  Headers contêm `reason`, `status_code`, `body_preview` (até 500 chars do OperationOutcome).
- **Fix comum**: CPF malformado no CSV, ou perfil BRIndivíduo desabilitado no HAPI (`hapi.fhir.validation.requests_enabled` deve ser `false` se você não tem o pacote BR carregado).

### HAPI responde 500 em `POST /fhir/Patient`
- **Causa típica**: deadlock no Postgres por carga concorrente (`enforce_referential_integrity_on_write: true`).
- **Fix**: reduza o paralelismo do consumer (uma instância só) ou desabilite a checagem em `hapi/application.yaml` se aceitar referências quebradas momentaneamente.

### Pacientes duplicados aparecem
- **Causa**: O CSV tem CPFs com formatação inconsistente que `clean_cpf` deveria normalizar. Verifique se a coluna está vindo como `123.456.789-00` e não como `123456789-00` (já normalizado parcialmente, ainda dá match).
- **Diagnóstico**: `curl "http://localhost:8080/fhir/Patient?identifier=12345678900&_summary=count"`. Se `total > 1`, alguma identifier foi gravada com formato diferente. Cheque com `identifier:contains=...`.

### Kafka rejeita o producer com `NotLeaderForPartition`
- **Causa**: tópico ainda não foi criado e `KAFKA_AUTO_CREATE_TOPICS_ENABLE=true` está desligado.
- **Fix**: confirme no compose; ou crie manualmente:
  ```bash
  docker compose exec kafka /opt/kafka/bin/kafka-topics.sh \
    --bootstrap-server localhost:9092 --create --topic fhir-patients --partitions 3 --replication-factor 1
  ```

### Spark do producer falha com `OutOfMemoryError`
- **Causa**: CSV maior que a memória do executor.
- **Fix**: limite o paralelismo no `etl/kafka_producer.py:64` mudando `master("local[*]")` para `master("local[2]")`, ou aumente memória com `SparkSession.builder.config("spark.driver.memory", "2g")`.

### Airflow não consegue conectar no Postgres (`role "airflow_user" does not exist`)
- **Causa**: volume `pgdata` foi criado antes da introdução do `postgres/init-db.sh`. O init script só roda em volume vazio.
- **Fix**: Veja `docs/deployment.md` → seção *Migração de volumes*.

### Dashboard Grafana sem dados
- **Causa**: scrape do Prometheus não chegou ao consumer (rede ou endpoint).
- **Fix**:
  ```bash
  docker compose exec prometheus wget -q -O - http://etl-consumer:8001/metrics | head -5
  ```
  Se falhar, o consumer não está expondo. Verifique `METRICS_PORT` no `.env` e a porta exposta no `docker-compose.yml`.

### `pre-commit` reclama de secret em `.env.example`
- **Causa**: detect-secrets não respeitou o exclude.
- **Fix**: garanta que o path está em `.pre-commit-config.yaml:exclude`. Para um falso-positivo pontual, gere um baseline:
  ```bash
  detect-secrets scan > .secrets.baseline
  ```

### Build do `etl/Dockerfile` falha por `default-jre-headless`
- **Causa**: mirror Debian fora do ar.
- **Fix**: retentar; ou usar `--build-arg DEBIAN_MIRROR=http://outro-mirror`.
