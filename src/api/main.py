# =============================================================
# src/api/main.py
# =============================================================

import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger
from neo4j import GraphDatabase

from src.api.routes.etl import router as etl_router
from src.api.routes import ner
from src.api.routes.similarity import router as similarity_router
from src.api.routes.saw import router as saw_router
from src.core.ollama_client import OllamaClient
from src.modules.semantic_similarity.similarity_service import SemanticSimilarityService


async def _warmup_ollama(client: OllamaClient) -> None:
    """
    Memaksa Ollama me-load model ke VRAM sebelum request pertama.
    Gagal warmup tidak menghentikan aplikasi.
    """
    logger.info("Warming up Ollama model...")
    try:
        await client.generate(
            system="You are helpful.",
            prompt="hi",
        )
        logger.info("Ollama warm — model siap di VRAM")
    except Exception as exc:
        logger.warning(f"Warmup Ollama gagal (aplikasi tetap jalan): {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Dijalankan sekali saat startup dan sekali saat shutdown.
    Menginisialisasi Neo4j, similarity service, dan Ollama untuk NER.
    """
    # ── Startup ──────────────────────────────────────────────
    logger.info("Virgo API: startup ...")

    neo4j_driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
    )
    app.state.neo4j_driver = neo4j_driver

    max_retries = 30
    retry_delay = 2

    for attempt in range(max_retries):
        try:
            similarity_service = SemanticSimilarityService(
                driver=neo4j_driver,
                database=os.getenv("NEO4J_DATABASE", "neo4j"),
            )
            similarity_service.initialize()
            app.state.similarity_service = similarity_service
            break
        except Exception as exc:
            if attempt < max_retries - 1:
                logger.warning(
                    f"Neo4j belum siap (attempt {attempt + 1}/{max_retries}), "
                    f"retry dalam {retry_delay}s: {exc}"
                )
                time.sleep(retry_delay)
            else:
                logger.error(
                    f"Neo4j tidak siap setelah {max_retries} attempts. "
                    f"Startup gagal: {exc}"
                )
                raise

    ollama_client = OllamaClient()
    app.state.ollama_client = ollama_client
    ner._extractor.client = ollama_client
    await _warmup_ollama(ollama_client)

    logger.info("Virgo API: siap menerima request.")
    yield

    # ── Shutdown ─────────────────────────────────────────────
    logger.info("Virgo API: shutdown ...")
    oc = getattr(app.state, "ollama_client", None)
    if oc is not None:
        await oc.close()
        logger.info("OllamaClient ditutup")
    neo4j_driver.close()


app = FastAPI(
    title="Virgo Talent Recommendation System API",
    description=(
        "API untuk sistem rekomendasi talenta multi-kriteria: "
        "NER (Qwen/Ollama), ETL ontology, semantic similarity pada Neo4j, "
        "dan perankingan SAW."
    ),
    version="0.3.0",
    lifespan=lifespan,
)

app.include_router(etl_router)
app.include_router(similarity_router)
app.include_router(ner.router)
app.include_router(saw_router)


@app.get("/", tags=["Info"])
def root():
    return {
        "project": "Virgo Talent Recommendation System",
        "status": "Development",
        "current_increment": 3,
        "modules": ["NER", "ETL", "Semantic Similarity", "SAW"],
        "team": ["Geraldin", "Ikhsan", "Harish"],
        "docs": "/docs",
    }


@app.get("/health")
def health_check():
    return {"status": "healthy"}
