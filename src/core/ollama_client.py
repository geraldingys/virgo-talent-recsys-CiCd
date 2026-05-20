"""
ollama_client.py

OllamaClient mengirim prompt ke Ollama API dan mengembalikan respons teks.
Tidak ada logika bisnis di sini — hanya HTTP dan retry.

Menggunakan persistent httpx.AsyncClient untuk menghindari overhead
TCP handshake di setiap request.
"""

from __future__ import annotations

import httpx
from loguru import logger

from src.core.settings import get_settings


class OllamaClient:
    """
    HTTP client untuk Ollama API.

    Client di-share antar request (persistent) untuk menghindari
    overhead TCP handshake yang terjadi kalau dibuat baru setiap request.
    """

    def __init__(self) -> None:
        cfg = get_settings()
        # Persistent client — tidak dibuat ulang setiap request
        self._client = httpx.AsyncClient(timeout=cfg.ollama_timeout)
        self._endpoint = cfg.ollama_endpoint
        self._headers = {
            "Authorization": cfg.jwt_token,
            "Content-Type": "application/json",
        }
        self._model = cfg.ollama_model

    async def generate(self, system: str, prompt: str) -> str:
        """
        Kirim prompt ke Ollama dan kembalikan teks respons.

        Parameters
        ----------
        system : str
            Instruksi sistem untuk model.
        prompt : str
            Kalimat query dari pengguna.

        Returns
        -------
        str
            Teks JSON mentah dari respons model.

        Raises
        ------
        OllamaConnectionError
            Jika server tidak dapat dijangkau setelah retry.
        OllamaResponseError
            Jika respons tidak mengandung field yang diharapkan.
        """
        payload = {
            "model": self._model,
            "system": system,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.0},
        }

        logger.info(f"Request ke Ollama | endpoint={self._endpoint}")

        try:
            body = await self._post(payload)
            return self._extract_text(body)

        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            logger.warning(f"Request gagal, retry | alasan={exc}")
            return await self._retry(payload)

    async def _post(self, payload: dict) -> dict:
        """Kirim HTTP POST dan kembalikan body sebagai dict."""
        response = await self._client.post(
            self._endpoint,
            headers=self._headers,
            json=payload,
        )
        self._log_status(response.status_code)
        response.raise_for_status()
        return response.json()

    async def _retry(self, payload: dict) -> str:
        """Coba ulang request sekali. Lempar OllamaConnectionError kalau tetap gagal."""
        logger.info("Menjalankan retry")
        try:
            body = await self._post(payload)
            return self._extract_text(body)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as exc:
            logger.error(f"Retry gagal | {exc}")
            raise OllamaConnectionError(str(exc)) from exc

    def _extract_text(self, body: dict) -> str:
        """Ambil teks dari field 'response' body Ollama."""
        if "response" not in body:
            raise OllamaResponseError(f"Field 'response' tidak ada. Body: {body}")
        text = body["response"].strip()
        logger.info(f"Respons diterima | panjang={len(text)} karakter")
        return text

    def _log_status(self, status_code: int) -> None:
        if status_code >= 500:
            logger.error(f"Server error Ollama | status={status_code}")
        elif status_code >= 400:
            logger.warning(f"Request ditolak | status={status_code}")
        else:
            logger.debug(f"Response OK | status={status_code}")

    async def close(self) -> None:
        """Tutup HTTP client. Dipanggil saat aplikasi shutdown."""
        await self._client.aclose()


# ── Custom Exceptions ──────────────────────────────────────────────────────────

class OllamaConnectionError(Exception):
    """Server Ollama tidak dapat dijangkau setelah retry."""


class OllamaResponseError(Exception):
    """Respons dari Ollama tidak sesuai format yang diharapkan."""