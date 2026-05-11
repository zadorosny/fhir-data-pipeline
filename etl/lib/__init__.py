"""Biblioteca interna do ETL FHIR.

Modulos:
    config       - configuracao via env vars (pydantic-settings)
    logging_setup - logging estruturado em JSON
    transform    - funcoes puras de transformacao (CSV row -> dict)
    fhir         - builders de Resources FHIR + cliente HTTP com retry
    metrics      - contadores e histogramas Prometheus
"""
