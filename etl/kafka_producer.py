"""
Producer: PySpark lê o CSV de pacientes e publica cada registro
como mensagem JSON no tópico Kafka 'fhir-patients'.
"""

import json
import os

from kafka import KafkaProducer
from pyspark.sql import SparkSession

KAFKA_BROKER = os.getenv("KAFKA_BROKER", "kafka:9092")
TOPIC = os.getenv("KAFKA_TOPIC", "fhir-patients")
CSV_PATH = os.getenv("CSV_PATH", "/opt/app/data/patients.csv")
CSV_ENCODING = os.getenv("CSV_ENCODING", "ISO-8859-1")


def normalize_columns(df):
    """Normaliza nomes de colunas (remove acentos, BOM)."""
    col_map = {}
    for c in df.columns:
        clean = c.strip().replace("\ufeff", "")
        if "Nome" in clean:
            col_map[c] = "Nome"
        elif "CPF" in clean:
            col_map[c] = "CPF"
        elif "nero" in clean or "Genero" in clean or "Gênero" in clean:
            col_map[c] = "Genero"
        elif "Nascimento" in clean and "Data" in clean:
            col_map[c] = "DataNascimento"
        elif "Telefone" in clean:
            col_map[c] = "Telefone"
        elif "Pa" in clean and "s" in clean:
            col_map[c] = "Pais"
        elif "Observa" in clean:
            col_map[c] = "Observacao"
        else:
            col_map[c] = clean
    for old, new in col_map.items():
        df = df.withColumnRenamed(old, new)
    return df


def main():
    print("=" * 60)
    print("PRODUCER — PySpark → Kafka")
    print(f"  KAFKA_BROKER : {KAFKA_BROKER}")
    print(f"  TOPIC        : {TOPIC}")
    print(f"  CSV_PATH     : {CSV_PATH}")
    print("=" * 60)

    spark = (
        SparkSession.builder
        .appName("FHIR-Kafka-Producer")
        .master("local[*]")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")

    df = (
        spark.read
        .option("header", "true")
        .option("encoding", CSV_ENCODING)
        .option("sep", ",")
        .csv(CSV_PATH)
    )
    df = normalize_columns(df)

    rows = df.collect()
    print(f"\nTotal de registros no CSV: {len(rows)}")

    producer = KafkaProducer(
        bootstrap_servers=KAFKA_BROKER,
        value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"),
    )

    for row in rows:
        message = {
            "nome": row["Nome"],
            "cpf": row["CPF"],
            "genero": row["Genero"],
            "data_nascimento": row["DataNascimento"],
            "telefone": row["Telefone"],
            "pais": row["Pais"],
            "observacao": row["Observacao"] or "",
        }
        producer.send(TOPIC, value=message)

    producer.flush()
    producer.close()
    spark.stop()

    print(f"Publicadas {len(rows)} mensagens no tópico '{TOPIC}'")
    print("=" * 60)


if __name__ == "__main__":
    main()
