# =============================================================
# src/api/routes/etl.py
# Endpoint FastAPI untuk trigger ETL pipeline
#
# POST /etl/sync          — sinkronisasi Google Sheets → Neo4j
# POST /etl/recompute-ic  — hitung ulang IC + SKILL_SIMILARITY
# =============================================================

import os

from fastapi import APIRouter, HTTPException, Request, status
from loguru import logger
from pydantic import BaseModel

from src.modules.etl.pipeline import (
    ETLConfig,
    ETLPipeline,
    PipelineReport,
)

router = APIRouter(prefix="/etl", tags=["ETL"])


class SyncResponse(BaseModel):
    status           : str
    total_rows       : int
    transformed_ok   : int
    validated_ok     : int
    written_ok       : int
    validation_errors: list[dict]
    write_errors     : list[dict]
    inference_log    : list[dict]


class RecomputeICResponse(BaseModel):
    total_nodes       : int
    total_pairs       : int
    similarity_written: int
    errors            : list[dict]
    duration_seconds  : float


def _build_config() -> ETLConfig:
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
    return ETLConfig(
        credentials_path = os.environ["GOOGLE_CREDENTIALS_PATH"],
        spreadsheet_id   = os.environ["GOOGLE_SPREADSHEET_ID"],
        worksheet_name   = os.getenv("GOOGLE_WORKSHEET_NAME"),
        ttl_path         = os.environ["ONTOLOGY_TTL_PATH"],
        neo4j_uri        = os.environ["NEO4J_URI"],
        neo4j_user       = os.environ["NEO4J_USER"],
        neo4j_password   = os.environ["NEO4J_PASSWORD"],
        neo4j_database   = os.getenv("NEO4J_DATABASE", "neo4j"),
    )


def _get_similarity_service(request: Request):
    service = getattr(request.app.state, "similarity_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Semantic similarity service belum diinisialisasi.",
        )
    return service


@router.post(
    "/sync",
    response_model=SyncResponse,
    summary="Trigger sinkronisasi Google Sheets → Neo4j",
)
async def sync_etl() -> SyncResponse:
    config = _build_config()
    logger.info("POST /etl/sync — pipeline dimulai.")
    try:
        report: PipelineReport = ETLPipeline(config).run()
    except Exception as exc:
        logger.exception("ETL pipeline gagal.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pipeline error: {str(exc)}",
        )
    return SyncResponse(
        status            = "success" if not report.write_errors else "partial",
        total_rows        = report.total_rows,
        transformed_ok    = report.transformed_ok,
        validated_ok      = report.validated_ok,
        written_ok        = report.written_ok,
        validation_errors = report.validation_errors,
        write_errors      = report.write_errors,
        inference_log     = report.inference_log,
    )


@router.post(
    "/recompute-ic",
    response_model=RecomputeICResponse,
    summary="Hitung ulang relasi SKILL_SIMILARITY di Neo4j",
)
async def recompute_ic(request: Request) -> RecomputeICResponse:
    service = _get_similarity_service(request)
    logger.info("POST /etl/recompute-ic — mulai.")
    try:
        report = service.recompute_ic_similarity()
    except Exception as exc:
        logger.exception("recompute-ic gagal.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"recompute-ic error: {str(exc)}",
        )
    return RecomputeICResponse(
        total_nodes        = report.total_nodes,
        total_pairs        = report.total_pairs,
        similarity_written = report.similarity_written,
        errors             = report.errors,
        duration_seconds   = report.duration_seconds,
    )
