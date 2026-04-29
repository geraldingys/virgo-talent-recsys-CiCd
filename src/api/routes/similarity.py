# =============================================================
# src/api/routes/similarity.py
# Endpoint FastAPI untuk semantic similarity ranking
#
# POST /similarity/rank
#   Input : list skill requirement (dari NER Increment 1)
#   Output: list talenta diurutkan berdasarkan skill score
# =============================================================

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from loguru import logger

router = APIRouter(prefix="/similarity", tags=["Semantic Similarity"])


# ----------------------------------------------------------
# Request & Response schema
# ----------------------------------------------------------

class RankRequest(BaseModel):
    required_skills: list[str] = Field(
        ...,
        min_length=1,
        description="Daftar label skill requirement dari hasil NER.",
        examples=[["React.js", "Node.js", "PostgreSQL"]],
    )


class SkillMatchDetailResponse(BaseModel):
    required_skill  : str
    best_match_skill: str
    similarity_score: float


class TalentScoreResponse(BaseModel):
    nip            : str
    nama_lengkap   : str
    skill_score    : float
    talent_skills  : list[str]
    match_details  : list[SkillMatchDetailResponse]


class RankResponse(BaseModel):
    total_talents   : int
    required_skills : list[str]
    ranked_talents  : list[TalentScoreResponse]


# ----------------------------------------------------------
# Dependency — akses service dari app state
# ----------------------------------------------------------

def get_similarity_service(request):
    service = getattr(request.app.state, "similarity_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Semantic similarity service belum diinisialisasi.",
        )
    return service


# ----------------------------------------------------------
# Endpoint
# ----------------------------------------------------------

@router.post(
    "/rank",
    response_model=RankResponse,
    summary="Ranking talenta berdasarkan kemiripan skill",
    description=(
        "Menerima daftar skill requirement dari NER, lalu menghitung "
        "skor kemiripan semantik (Sánchez Similarity) setiap talenta "
        "menggunakan strategi Best Match Average. "
        "Mengembalikan seluruh talenta diurutkan dari skor tertinggi."
    ),
)
async def rank_talents(body: RankRequest, request: Request) -> RankResponse:
    service = get_similarity_service(request)

    logger.info(
        f"POST /similarity/rank — {len(body.required_skills)} skill: "
        f"{body.required_skills}"
    )

    try:
        results = service.rank_talents(body.required_skills)
    except Exception as exc:
        logger.exception("Similarity ranking gagal.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Similarity error: {str(exc)}",
        )

    ranked = [
        TalentScoreResponse(
            nip           = r.nip,
            nama_lengkap  = r.nama_lengkap,
            skill_score   = r.skill_score,
            talent_skills = r.talent_skills,
            match_details = [
                SkillMatchDetailResponse(
                    required_skill   = d.required_skill,
                    best_match_skill = d.best_match_skill,
                    similarity_score = d.similarity_score,
                )
                for d in r.match_details
            ],
        )
        for r in results
    ]

    return RankResponse(
        total_talents   = len(ranked),
        required_skills = body.required_skills,
        ranked_talents  = ranked,
    )
