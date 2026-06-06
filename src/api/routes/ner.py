"""
ner.py — NERRouter

NERRouter adalah controller layer aplikasi untuk modul NER.
Tanggung jawabnya:
  1. Menerima HTTP request dari n8n / Telegram
  2. Mendelegasikan ke NERExtractor
  3. Mengembalikan respons JSON beserta latency_ms

Tidak ada logika bisnis di sini — hanya HTTP dan error handling.

Endpoint:
    POST /api/v1/ner/extract
"""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, status
from loguru import logger
from pydantic import BaseModel, Field

from src.core.ollama_client import OllamaConnectionError, OllamaResponseError
from src.modules.ner.extractor import NERExtractor
from src.modules.ner.schemas import ExtractionResult

router = APIRouter(prefix="/api/v1/ner", tags=["NER"])

# Satu instance extractor dipakai ulang untuk seluruh request
# (Dependency Injection — mudah diganti saat testing)
_extractor = NERExtractor()


# ── Request / Response Models ──────────────────────────────────────────────────

class NERRequest(BaseModel):
    """Body request untuk endpoint ekstraksi entitas."""
    query: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Kalimat kebutuhan talenta dari Tim Sales / Tim TD.",
        examples=["Butuh senior React.js min 3 tahun di Bandung"],
    )


class NERResponse(BaseModel):
    """Response envelope endpoint NER."""
    success: bool
    data: ExtractionResult | None = None
    latency_ms: float
    error: str | None = None


# ── Endpoint ───────────────────────────────────────────────────────────────────

@router.post(
    "/extract",
    response_model=NERResponse,
    status_code=status.HTTP_200_OK,
    summary="Ekstraksi entitas kebutuhan talenta",
    description=(
        "Menerima kalimat natural kebutuhan talenta dan mengekstrak "
        "enam slot entitas: skill, seniority, pengalaman, lokasi, "
        "sektor proyek, dan pendidikan."
    ),
)
async def extract_entities(request: NERRequest) -> NERResponse:
    """
    Endpoint utama NER — UC-NER-01.

    Mendelegasikan ke NERExtractor dan mengembalikan
    ExtractionResult beserta latency_ms pemrosesan.
    """
    logger.info(f"Request NER diterima | query='{request.query}'")
    start_time = time.perf_counter()

    try:
        result = await _extractor.extract(request.query)
        latency_ms = _calc_latency(start_time)
        return NERResponse(success=True, data=result, latency_ms=latency_ms)

    except OllamaConnectionError as exc:
        latency_ms = _calc_latency(start_time)
        logger.error(f"Ollama tidak dapat dijangkau | {exc}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Layanan Ollama tidak dapat dijangkau. Pastikan VPN aktif dan coba lagi.",
        )

    except OllamaResponseError as exc:
        latency_ms = _calc_latency(start_time)
        logger.error(f"Respons Ollama tidak valid | {exc}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Respons dari Ollama tidak dapat diproses.",
        )

    except Exception as exc:
        latency_ms = _calc_latency(start_time)
        logger.error(f"Error tidak terduga | tipe={type(exc).__name__} | {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Terjadi kesalahan internal periksa token dan url Ollama. Error: {type(exc).__name__}",
        )


def _calc_latency(start_time: float) -> float:
    """Hitung durasi pemrosesan dalam milidetik."""
    return round((time.perf_counter() - start_time) * 1000, 2)