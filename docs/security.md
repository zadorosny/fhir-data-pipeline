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
3. Habilite `hapi.fhir.validation.requests_enabled: true` para forçar conformidade com perfis e barrar payloads malformados.

## Logs e PHI

O consumer registra `cpf` em alguns logs (campo `extra.cpf`). Em prod, considere:
- mascarar no agregador (Loki promtail pipeline; CloudWatch metric filter).
- ou trocar para `cpf_hash = sha256(cpf)` no `etl/lib/fhir.py` e propagar.

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
| `AIRFLOW__CORE__FERNET_KEY`          | 365d        | Re-encrypt connections (ver `docs/deployment.md`) |
| `AIRFLOW__WEBSERVER__SECRET_KEY`     | 90d         | Invalida sessões ativas — coordene com usuários |
| `AIRFLOW_ADMIN_PASSWORD`             | 90d / on-leave | `airflow users reset-password`              |
| `GRAFANA_ADMIN_PASSWORD`             | 90d         | Edite `.env` e reinicie o container Grafana   |

## Reportando vulnerabilidades

Abrir issue privada no GitHub ou enviar para o mantenedor do repositório. Não divulgar publicamente até que um fix esteja disponível.
