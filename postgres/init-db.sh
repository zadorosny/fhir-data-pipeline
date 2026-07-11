#!/bin/bash
# Inicializacao do Postgres: cria schema 'airflow' e role 'airflow_user'
# dedicada (separada do owner do HAPI FHIR).
#
# Variaveis lidas do ambiente do container postgres:
#   POSTGRES_USER, POSTGRES_DB              (ja definidos pela imagem oficial)
#   AIRFLOW_DB_USER, AIRFLOW_DB_PASSWORD    (passados via docker-compose)
#
# Este script roda apenas no primeiro start do container (volume vazio).
set -euo pipefail

: "${AIRFLOW_DB_USER:?AIRFLOW_DB_USER nao definido}"
: "${AIRFLOW_DB_PASSWORD:?AIRFLOW_DB_PASSWORD nao definido}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Role dedicada para o Airflow (principio de menor privilegio)
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${AIRFLOW_DB_USER}') THEN
            CREATE ROLE ${AIRFLOW_DB_USER} LOGIN PASSWORD '${AIRFLOW_DB_PASSWORD}';
        END IF;
    END
    \$\$;

    CREATE SCHEMA IF NOT EXISTS airflow AUTHORIZATION ${AIRFLOW_DB_USER};

    GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO ${AIRFLOW_DB_USER};
    GRANT USAGE, CREATE ON SCHEMA airflow TO ${AIRFLOW_DB_USER};
    ALTER ROLE ${AIRFLOW_DB_USER} SET search_path TO airflow;
EOSQL

echo "init-db.sh: schema 'airflow' e role '${AIRFLOW_DB_USER}' provisionados."
