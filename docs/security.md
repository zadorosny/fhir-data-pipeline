# Security

## Modelo de ameaças

| Ativo                 | Ameaça                                  | Mitigação atual                                |
|-----------------------|------------------------------------------|------------------------------------------------|
| Credenciais Postgres  | Vazamento via `git`                     | `.env` no `.gitignore`; `.env.example` apenas com placeholders |
| Credenciais Airflow   | Brute-force no painel                   | Senha obrigatória via env; reset rotativo recomendado |
| Token Fernet          | Cifragem fraca de connections          | Geração aleatória obrigatória; rotação documentada |
| Docker socket no host | Container Airflow vira root no host    | **Risco aceito** em dev; em prod use `KubernetesPodOperator` (ver abaixo) |
| Dados clínicos (CPF)  | Exfiltração via FHIR REST exposto       | Em prod, HAPI atrás de reverse proxy com auth e TLS |
| Logs de aplicação     | CPF/PHI em texto claro                  | `hash_cpf` (SHA-256) aplicado nos logs do consumer (`etl/lib/redaction.py`) — pesquisa por "cpf" em log aggregator = sinal de regressão |
| Kafka UI sem auth     | Operador hostil enumera/dropa tópicos   | Fora por default; opt-in via `docker compose --profile debug up` |

## Princípio de menor privilégio (Postgres)

- `POSTGRES_USER` (default `fhir`): owner do banco, usado pelo HAPI.
- `AIRFLOW_DB_USER` (default `airflow_user`): role separada, só CONNECT no DB e USAGE/CREATE no schema `airflow`. `search_path` fixado em `airflow`.
- Provisionamento automático em `postgres/init-db.sh` ao primeiro start.

## Docker socket no Airflow

A DAG atual (`airflow/dags/fhir_etl_dag.py`) usa `BashOperator` com `docker start -a` para reaproveitar os containers do compose. Para isso, `/var/run/docker.sock` é montado no Airflow — o que dá ao container privilégio equivalente a root no host.

**Risco**: comprometer o Airflow = comprometer o host inteiro.

**Alternativas para produção**:
- `KubernetesPodOperator` (recomendado): cada task vira um pod, sem socket compartilhado.
- `DockerOperator` apontando para um daemon remoto via TLS (`DOCKER_HOST=tcp://docker-api:2376` + cert).
- Reescrever as tasks como `PythonOperator` invocando diretamente `etl.kafka_producer.main()` e `etl.kafka_consumer.main()` (precisa instalar `etl` no ambiente do Airflow worker).

Se mantiver o socket em dev, **nunca exponha o painel Airflow na internet**.

## TLS / HAPI exposto

O `hapi-fhir` no compose escuta HTTP simples em `8080`. Para produção:

1. Coloque um reverse proxy (Caddy, Nginx, Traefik) na frente com cert via Let's Encrypt.
2. Habilite autenticação (Smart-on-FHIR ou Basic + IP allowlist).
3. Validação de payloads (`hapi.fhir.validation.requests_enabled`) está **temporariamente desligada** em `hapi/application.yaml`. Para reabilitar: carregar o StructureDefinition do perfil `BRIndividuo-1.0` no HAPI (via NpmPackage do RNDS ou IG do MS) — sem o perfil carregado, HAPI rejeita 100% dos POSTs com `VALIDATION_VAL_PROFILE_UNKNOWN_NOT_POLICY`. Tracked como follow-up.

## Logs e PHI

O consumer **nunca** emite CPF em texto claro. Os call sites em `etl/kafka_consumer.py:process_patient` aplicam `hash_cpf` de `etl/lib/redaction.py` no campo `extra.cpf_hash` (SHA-256 prefixado por `sha256:`).

Regras:
- Pesquisa por `"cpf"` (sem `_hash`) em log aggregator deve retornar **zero** hits — qualquer match é sinal de regressão.
- Para depuração local com humanos, use `mask_cpf` (`***.***.***-NN`) — preserva últimos 2 dígitos para correlação manual sem expor o identificador.
- Testes de regressão em `tests/test_consumer_logging.py` falham se alguém reintroduzir `"cpf": data.get("cpf")` nos `extra={...}`.

Em downstream (Loki/CloudWatch), aplique também redação de cabeçalhos HTTP (`Authorization`, `X-Forwarded-For`) e payloads de erro do HAPI antes da retenção longa.

## Dependências e CVEs

- `etl/requirements.txt` é varrido por `pip-audit` em `.github/workflows/security.yml` a cada push, PR e segunda-feira 06:00 UTC.
- A imagem `python:3.12-slim` é varrida por Trivy filesystem scan.
- `gitleaks` escaneia o histórico completo a cada push/PR.
- `dependabot.yml` abre PRs semanais para `pip`, `docker` e `github-actions`.

## Rotação de segredos

Periodicidade sugerida (ambiente sensível):

| Segredo                              | Cadência    | Procedimento                                  |
|--------------------------------------|-------------|-----------------------------------------------|
| `POSTGRES_PASSWORD`                  | 90d         | `ALTER USER fhir WITH PASSWORD '...'`; restart HAPI |
| `AIRFLOW_DB_PASSWORD`                | 90d         | `ALTER USER airflow_user WITH PASSWORD '...'`; restart Airflow |
| `AIRFLOW__CORE__FERNET_KEY`          | 365d / on-exposure | Ver runbook abaixo                       |
| `AIRFLOW__WEBSERVER__SECRET_KEY`     | 90d         | Invalida sessões ativas — coordene com usuários |
| `AIRFLOW_ADMIN_PASSWORD`             | 90d / on-leave | `airflow users reset-password`              |
| `GRAFANA_ADMIN_PASSWORD`             | 90d         | Edite `.env` e reinicie o container Grafana   |

### Runbook: rotação do Fernet key

O Fernet key cifra as connections e variables sensíveis no metadata DB do Airflow. **Sempre rotacionar quando**:
- a chave foi compartilhada com terceiros (inclusive logs de assistentes de IA, screenshots de `.env`, paste em chat);
- desligamento de membro com acesso ao `.env`;
- vencimento da cadência de 365d.

Como `.env` está gitignored, **não há remediação necessária no histórico git** — basta gerar e ativar uma nova chave:

```bash
# 1. Gere a nova chave
NEW_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

# 2. Adicione ao .env como segunda chave (sintaxe key1,key2 = re-encrypt aceito)
sed -i "s|^AIRFLOW__CORE__FERNET_KEY=.*|AIRFLOW__CORE__FERNET_KEY=${NEW_KEY},$(grep ^AIRFLOW__CORE__FERNET_KEY .env | cut -d= -f2)|" .env

# 3. Restart Airflow e re-encripte connections com a nova chave
docker compose up -d airflow
docker compose exec airflow airflow rotate-fernet-key

# 4. Remova a chave antiga do .env (mantenha somente a nova)
sed -i "s|^AIRFLOW__CORE__FERNET_KEY=${NEW_KEY},.*|AIRFLOW__CORE__FERNET_KEY=${NEW_KEY}|" .env
docker compose up -d airflow
```

Se houver suspeita de exfiltração do metadata DB junto com a chave antiga, tratar todas as connections/variables como comprometidas e rotacionar cada credencial referenciada nelas.

## Reportando vulnerabilidades

Abrir issue privada no GitHub ou enviar para o mantenedor do repositório. Não divulgar publicamente até que um fix esteja disponível.
