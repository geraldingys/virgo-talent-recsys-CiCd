# =============================================================
# src/api/routes/etl.py
# Endpoint FastAPI untuk trigger ETL pipeline
#
# Dipanggil oleh N8N via HTTP Request node setiap kali
# ada perubahan di Google Sheets.
#
# POST /etl/sync
#   — Tidak butuh body (konfigurasi diambil dari .env)
#   — Mengembalikan PipelineReport sebagai JSON
# =============================================================

import os

from fastapi import APIRouter, HTTPException, status
from loguru import logger
from pydantic import BaseModel

from src.modules.semantic_similarity.etl.pipeline import (
    ETLConfig,
    PipelineReport,
    run_etl_pipeline,
)

router = APIRouter(prefix="/etl", tags=["ETL"])


# ----------------------------------------------------------
# Response schema
# ----------------------------------------------------------

class SyncResponse(BaseModel):
    status            : str
    total_rows        : int
    transformed_ok    : int
    validated_ok      : int
    written_ok        : int
    validation_errors : list[dict]
    write_errors      : list[dict]


# ----------------------------------------------------------
# Endpoint
# ----------------------------------------------------------

@router.post(
    "/sync",
    response_model=SyncResponse,
    summary="Trigger sinkronisasi Google Sheets → Neo4j",
    description=(
        "Menjalankan pipeline ETL secara lengkap: "
        "baca Google Sheets, validasi ontologi (Owlready2 + HermiT), "
        "lalu tulis ke Neo4j. "
        "Endpoint ini dipanggil oleh N8N setiap ada perubahan di spreadsheet."
    ),
)
async def sync_etl() -> SyncResponse:
    """
    Entry point ETL yang dipanggil oleh N8N.
    Konfigurasi koneksi diambil dari environment variables.
    """
    # Validasi env vars wajib sebelum mulai
    required_env = [
        "GOOGLE_CREDENTIALS_PATH",
        "GOOGLE_SPREADSHEET_ID",
        "NEO4J_URI",
        "NEO4J_USER",
        "NEO4J_PASSWORD",
        "ONTOLOGY_TTL_PATH",
    ]
    missing = [k for k in required_env if not os.getenv(k)]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Environment variable belum diset: {missing}",
        )

    config = ETLConfig(
        credentials_path = os.environ["GOOGLE_CREDENTIALS_PATH"],
        spreadsheet_id   = os.environ["GOOGLE_SPREADSHEET_ID"],
        worksheet_name   = os.getenv("GOOGLE_WORKSHEET_NAME"),       # opsional
        ttl_path         = os.environ["ONTOLOGY_TTL_PATH"],
        neo4j_uri        = os.environ["NEO4J_URI"],
        neo4j_user       = os.environ["NEO4J_USER"],
        neo4j_password   = os.environ["NEO4J_PASSWORD"],
        neo4j_database   = os.getenv("NEO4J_DATABASE", "neo4j"),
    )

    logger.info("POST /etl/sync — pipeline dimulai.")
    try:
        report: PipelineReport = run_etl_pipeline(config)
    except Exception as exc:
        logger.exception("ETL pipeline gagal dengan exception tidak terduga.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pipeline error: {str(exc)}",
        )

    return SyncResponse(
        status            = "success" if report.write_errors == [] else "partial",
        total_rows        = report.total_rows,
        transformed_ok    = report.transformed_ok,
        validated_ok      = report.validated_ok,
        written_ok        = report.written_ok,
        validation_errors = report.validation_errors,
        write_errors      = report.write_errors,
    )
