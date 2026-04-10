FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends default-jre-headless && \
    rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/default-java

RUN pip install --no-cache-dir pyspark==3.5.3 requests==2.31.0 kafka-python-ng==2.2.3

COPY kafka_producer.py kafka_consumer.py /opt/app/

WORKDIR /opt/app
