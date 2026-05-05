"""
main.py — FastAPI application entrypoint

Virgo Rekomendasi Talenta API
Increment 1: Modul NER aktif
"""

from fastapi import FastAPI
from loguru import logger

from src.api.routes import ner as ner_router
from src.core.ollama_client import OllamaClient

app = FastAPI(
    title="Virgo Talent Recommendation API",
    description=(
        "Sistem rekomendasi talenta multi-kriteria berbasis semantic similarity "
        "pada knowledge graph PT Padepokan Tujuh Sembilan."
    ),
    version="1.0.0-increment1",
)

app.include_router(ner_router.router)

# Instance client yang di-share antar request
# Dibuat sekali saat startup, ditutup saat shutdown
_ollama_client: OllamaClient | None = None


@app.on_event("startup")
async def on_startup() -> None:
    """
    Inisialisasi aplikasi saat startup:
    1. Buat persistent OllamaClient
    2. Warmup Ollama — load model ke VRAM sebelum request pertama user masuk
       sehingga cold start tidak dirasakan oleh user
    """
    global _ollama_client

    logger.info("Virgo API starting — Increment 1: NER")

    _ollama_client = OllamaClient()

    # Inject ke NERExtractor di router supaya pakai client yang sama
    ner_router._extractor.client = _ollama_client

    await _warmup_ollama(_ollama_client)


@app.on_event("shutdown")
async def on_shutdown() -> None:
    """Tutup HTTP client saat aplikasi berhenti."""
    if _ollama_client:
        await _ollama_client.close()
        logger.info("OllamaClient ditutup")


async def _warmup_ollama(client: OllamaClient) -> None:
    """
    Kirim request dummy ke Ollama saat startup.

    Tujuan: memaksa Ollama me-load model Qwen3:8b ke VRAM
    sebelum request pertama user masuk.
    Tanpa ini, user pertama akan merasakan cold start ~2-3 detik lebih lambat.
    """
    logger.info("Warming up Ollama model...")
    try:
        await client.generate(
            system="You are helpful.",
            prompt="hi",
        )
        logger.info("Ollama warm — model siap di VRAM")
    except Exception as exc:
        # Warmup gagal tidak menghentikan aplikasi —
        # hanya berarti request pertama user akan lebih lambat
        logger.warning(f"Warmup Ollama gagal (aplikasi tetap jalan): {exc}")


@app.get("/", tags=["Info"])
def root():
    return {
        "project": "Virgo Talent Recommendation System",
        "increment": 1,
        "modules": ["NER"],
        "docs": "/docs",
    }


@app.get("/health", tags=["Info"])
def health():
    return {"status": "healthy"}