from fastapi import FastAPI

from src.api.routes.etl import router as etl_router

app = FastAPI(
    title = "Virgo Talent Recommendation System API",
    description = "API untuk sistem rekomendasi talenta multi-kriteria.",
    version = "0.1.0"
)

app.include_router(etl_router)

@app.get("/", tags=["Info"])
def read_root():
    return {
        "project": "Virgo Talent Recommendation System",
        "status": "Development",
        "current_increment": 1,
        "team": ["Geraldin", "Ikhsan", "Harish"],
        "docs": "/docs"
    }

@app.get("/health")
def health_check():
    return {"status": "healthy"}
