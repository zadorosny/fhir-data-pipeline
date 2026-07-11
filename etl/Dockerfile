FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends default-jre-headless && \
    rm -rf /var/lib/apt/lists/*

# Usuario nomeado com entrada em /etc/passwd: requisito do Hadoop UGI
# (Spark) que consulta user.name via getpwuid_r. Sem isso o producer
# falha no startup com `KerberosAuthException: invalid null input: name`.
RUN groupadd -g 1000 etl && useradd -m -u 1000 -g 1000 -s /usr/sbin/nologin etl

ENV JAVA_HOME=/usr/lib/jvm/default-java \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/opt/app \
    HOME=/home/etl

WORKDIR /opt/app

COPY requirements.txt /opt/app/requirements.txt
RUN pip install --no-cache-dir -r /opt/app/requirements.txt

COPY __init__.py /opt/app/etl/__init__.py
COPY lib /opt/app/etl/lib
COPY kafka_producer.py kafka_consumer.py /opt/app/etl/

USER etl
