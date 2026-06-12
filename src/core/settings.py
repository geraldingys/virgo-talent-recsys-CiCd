"""
settings.py

Konfigurasi terpusat aplikasi Virgo menggunakan pola Singleton.
Seluruh nilai dibaca dari file .env — tidak ada nilai sensitif
yang di-hardcode di sini.

Penggunaan:
    from src.core.settings import Settings
    cfg = Settings.get_instance()
    print(cfg.ollama_endpoint)
"""

from __future__ import annotations
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Singleton konfigurasi aplikasi.

    Dibaca satu kali dari .env saat pertama kali dipanggil,
    lalu di-cache untuk seluruh lifetime aplikasi.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Ollama ────────────────────────────────────────────────────────────
    ollama_endpoint: str
    jwt_token: str
    ollama_model: str = "qwen3:8b"
    ollama_timeout: int = 180
    ollama_max_retries: int = 1

    # ── Neo4j ─────────────────────────────────────────────────────────────
    neo4j_uri: str = "neo4j+s://localhost"
    neo4j_username: str = "neo4j"
    neo4j_password: str = "changeme"
    neo4j_database: str = "neo4j"

    # ── FastAPI ───────────────────────────────────────────────────────────
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Mengembalikan satu-satunya instance Settings (Singleton).

    lru_cache(maxsize=1) memastikan .env hanya dibaca sekali
    selama aplikasi berjalan — setara dengan pola getInstance().
    """
    return Settings()