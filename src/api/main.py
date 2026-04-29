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
from src.api.routes.similarity import router as similarity_router
from src.modules.semantic_similarity.similarity_service import SemanticSimilarityService


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Dijalankan sekali saat startup dan sekali saat shutdown.
    Menginisialisasi koneksi Neo4j dan similarity service.
    """
    # ── Startup ──────────────────────────────────────────────
    logger.info("Virgo API: startup ...")

    neo4j_driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
    )
    app.state.neo4j_driver = neo4j_driver

    # Tunggu Neo4j fully ready sebelum initialize similarity service
    max_retries = 30
    retry_delay = 2  # seconds
    
    for attempt in range(max_retries):
        try:
            similarity_service = SemanticSimilarityService(
                driver   = neo4j_driver,
                database = os.getenv("NEO4J_DATABASE", "neo4j"),
            )
            similarity_service.initialize()
            app.state.similarity_service = similarity_service
            logger.info("Virgo API: siap menerima request.")
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
    yield

    # ── Shutdown ─────────────────────────────────────────────
    logger.info("Virgo API: shutdown ...")
    neo4j_driver.close()


app = FastAPI(
    title       = "Virgo Talent Recommendation System API",
    description = "API untuk sistem rekomendasi talenta multi-kriteria.",
    version     = "0.2.0",
    lifespan    = lifespan,
)

app.include_router(etl_router)
app.include_router(similarity_router)


@app.get("/", tags=["Info"])
def read_root():
    return {
        "project"          : "Virgo Talent Recommendation System",
        "status"           : "Development",
        "current_increment": 2,
        "team"             : ["Geraldin", "Ikhsan", "Harish"],
        "docs"             : "/docs",
    }


@app.get("/health")
def health_check():
    return {"status": "healthy"}
