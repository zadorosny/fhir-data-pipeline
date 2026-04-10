# Documentação Detalhada — Configuração e Carga FHIR

## Parte 1 — Configuração do Servidor FHIR

### Componentes da infraestrutura

O ambiente é orquestrado por um único `docker-compose.yml` com os seguintes serviços:

| Serviço         | Papel                                                                   |
|-----------------|-------------------------------------------------------------------------|
| **postgres**    | Banco de dados compartilhado entre HAPI FHIR e Airflow                 |
| **hapi-fhir**   | Servidor FHIR R4 (API REST em `/fhir`)                                |
| **hapi-ready**  | Sidecar que faz polling até o HAPI responder — garante ordem de início |
| **kafka**       | Broker de mensagens (modo KRaft) — intermedia o fluxo CSV → FHIR      |
| **kafka-ui**    | Interface web para visualização de tópicos e mensagens do Kafka        |
| **airflow**     | Orquestrador de workflows — DAG para re-execução sob demanda          |
| **etl-producer**| PySpark: lê o CSV e publica mensagens JSON no Kafka                    |
| **etl-consumer**| Consome mensagens do Kafka e carrega no HAPI FHIR                      |

### PostgreSQL

- Imagem: `postgres:15`
- O script `postgres/init-airflow.sql` cria um schema separado para o Airflow não misturar tabelas com o HAPI FHIR.
- O healthcheck (`pg_isready`) garante que o banco está pronto antes de iniciar o HAPI e o Airflow.

### HAPI FHIR

- Imagem: `hapiproject/hapi:latest`
- Configurado via `hapi/application.yaml` montado em `/app/config/application.yaml`.
- Conecta ao PostgreSQL via JDBC (`jdbc:postgresql://postgres:5432/fhir`).
- A conexão com o banco e as credenciais também são passadas via variáveis de ambiente no `docker-compose.yml` para garantir que o Spring Boot as utilize.
- O Flyway foi **desabilitado** no `application.yaml` (`spring.flyway.enabled: false`) para evitar incompatibilidade com a versão do PostgreSQL. O HAPI gerencia o schema via Hibernate auto-DDL.

### Kafka

- Imagem: `apache/kafka:3.8.0`
- Configurado em modo KRaft (sem Zookeeper).
- O Producer publica cada paciente como mensagem JSON no tópico `fhir-patients`.
- O Consumer lê as mensagens do tópico, constrói os Resources FHIR e envia via POST para o HAPI.
- Esse desacoplamento permite reprocessamento, escalabilidade e observabilidade via Kafka UI.

### Kafka UI

- Imagem: `provectuslabs/kafka-ui:latest`
- Porta: `9091`
- Permite visualizar tópicos, mensagens, offsets e consumer groups.
- Acesse http://localhost:9091 para verificar as mensagens publicadas no tópico `fhir-patients`.

### Airflow

- Imagem: `apache/airflow:2.10.0-python3.12`
- Executor: `LocalExecutor` (usa o PostgreSQL como backend).
- A DAG `fhir_patient_etl` (`airflow/dags/fhir_etl_dag.py`) é disparada manualmente via UI ou CLI.
- O pipeline inicial roda automaticamente via Docker Compose; a DAG permite re-execuções sob demanda.
- A DAG executa `docker start -a` nos containers `fhir_producer` e `fhir_consumer` em sequência.
- O Consumer é idempotente (verifica duplicatas por CPF e código SNOMED CT), permitindo re-execuções seguras.
- Credenciais padrão: `admin` / `admin`.

### Passo a passo para subir o ambiente

```bash
# 1. Clonar o repositório
git clone https://github.com/zadorosny/fhir-data-pipeline.git
cd fhir-data-pipeline

# 2. Subir tudo (build da imagem ETL + start dos serviços)
docker-compose up -d --build

# 3. Verificar que o HAPI está respondendo
curl http://localhost:8080/fhir/metadata

# 4. Acompanhar o Producer (CSV → Kafka)
docker logs -f fhir_producer

# 5. Acompanhar o Consumer (Kafka → HAPI FHIR)
docker logs -f fhir_consumer

# 6. Parar o ambiente
docker-compose down

# 7. Parar e remover volumes (limpa os dados)
docker-compose down -v
```

---

## Parte 2 — Pipeline de Carga de Dados

### Fluxo do ETL

```
CSV  →  PySpark (Producer)  →  Kafka (tópico fhir-patients)  →  Consumer  →  HAPI FHIR
```

1. O container `hapi-ready` faz polling com `curl --retry 90` até o HAPI responder em `/fhir/metadata`.
2. Quando o `hapi-ready` termina com sucesso (exit 0) e o Kafka está saudável (healthcheck), o container `etl-producer` é iniciado.
3. O **Producer** (PySpark) lê o arquivo `data/patients.csv` (encoding ISO-8859-1).
4. Os nomes das colunas são normalizados (remoção de acentos e BOM).
5. Para cada linha, uma mensagem JSON é publicada no tópico Kafka `fhir-patients`.
6. Quando o Producer finaliza, o container `etl-consumer` é iniciado.
7. O **Consumer** lê as mensagens do Kafka e, para cada uma, constrói um Resource **Patient** (perfil BRIndivíduo) e envia via `POST /fhir/Patient`.
8. Se a coluna "Observação" tiver valor, cada observação (separada por `|`) gera um Resource **Condition** vinculado ao Patient recém-criado.

### Mapeamento CSV → FHIR Patient

O Resource Patient utiliza o perfil **BRIndivíduo** da RNDS:
- **Profile**: `http://www.saude.gov.br/fhir/r4/StructureDefinition/BRIndividuo-1.0`
- **CPF**: Identificador oficial com system `http://rnds-fhir.saude.gov.br/fhir/r4/NamingSystem/cpf`

| Coluna CSV           | Campo FHIR                       |
|----------------------|----------------------------------|
| Nome                 | `Patient.name.given` + `family`  |
| CPF                  | `Patient.identifier`             |
| Gênero               | `Patient.gender`                 |
| Data de Nascimento   | `Patient.birthDate`              |
| Telefone             | `Patient.telecom`                |
| País de Nascimento   | `Patient.extension` (birthPlace) |

### Mapeamento Observação → FHIR Condition

| Observação   | SNOMED CT  | ICD-10 |
|-------------|-----------|--------|
| Gestante    | 77386006  | Z33    |
| Diabético   | 73211009  | E14    |
| Hipertenso  | 38341003  | I10    |

Cada Condition inclui codificação dupla (SNOMED CT + ICD-10), `clinicalStatus: active`, `verificationStatus: confirmed` e referência ao Patient via `subject`.

### Dockerfile do ETL

```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends default-jre-headless
ENV JAVA_HOME=/usr/lib/jvm/default-java
RUN pip install pyspark==3.5.3 requests==2.31.0 kafka-python-ng==2.2.3
COPY kafka_producer.py kafka_consumer.py /opt/app/
```

A imagem base é Python 3.12 slim com JRE headless (necessário para o Spark). As dependências são PySpark, requests e kafka-python-ng (fork mantido do kafka-python).

### Resultado esperado da carga

```
Pacientes criados (Patient):   50
Condições criadas (Condition):  15
Erros:                          0
```

### Verificação via Kafka UI

Acesse http://localhost:9091 para visualizar o tópico `fhir-patients` com as 50 mensagens publicadas pelo Producer. Cada mensagem contém o JSON de um paciente com os campos: nome, cpf, gênero, data_nascimento, telefone, país e observação.

### Verificação via HAPI FHIR

```bash
# Total de pacientes (deve ser 50)
curl http://localhost:8080/fhir/Patient?_summary=count

# Total de condições clínicas (deve ser 15)
curl http://localhost:8080/fhir/Condition?_summary=count

# Buscar paciente por CPF
curl "http://localhost:8080/fhir/Patient?identifier=12345678900"
```
