# =============================================================
# src/api/routes/saw.py
# Endpoint FastAPI untuk perankingan SAW multi-kriteria
#
# POST /saw/rank
#   Input : TalentScoreInput[] + metadata kueri (location, sector, education)
#   Output: RecommendationResult (top 5 + constraint labels)
# =============================================================

import os

from fastapi import APIRouter, HTTPException, Request, status
from loguru import logger

from src.modules.saw.schemas import SAWRankRequest, RecommendationResult
from src.modules.saw.saw_service import SAWService

router = APIRouter(prefix="/saw", tags=["SAW Ranking"])


# ----------------------------------------------------------
# Endpoint
# ----------------------------------------------------------


@router.post(
    "/rank",
    response_model=RecommendationResult,
    summary="Perankingan talenta multi-kriteria (SAW + ROC)",
    description=(
        "Menerima daftar talenta beserta skor skill dari /similarity/rank, "
        "mengambil profil lengkap dari Neo4j, lalu menjalankan perankingan "
        "Simple Additive Weighting (SAW) dengan bobot Rank Order Centroid (ROC). "
        "Mengembalikan top 5 talenta dengan label constraint informatif."
    ),
)
async def rank_talents(body: SAWRankRequest, request: Request) -> RecommendationResult:
    # Ambil Neo4j driver dari app state
    neo4j_driver = getattr(request.app.state, "neo4j_driver", None)
    if neo4j_driver is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Neo4j driver belum diinisialisasi.",
        )

    logger.info(
        f"POST /saw/rank — {len(body.talent_scores)} talenta, "
        f"location={body.location}, sector={body.project_sector}, "
        f"education={body.education}"
    )

    try:
        service = SAWService(
            driver=neo4j_driver,
            database=os.getenv("NEO4J_DATABASE", "neo4j"),
        )
        result = service.rank(body)
    except Exception as exc:
        logger.exception("SAW ranking gagal.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"SAW ranking error: {str(exc)}",
        )

    return result
