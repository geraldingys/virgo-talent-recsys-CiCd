"""
extractor.py

NERExtractor mengekstrak entitas kebutuhan talenta dari kalimat natural.

Alur:
  1. buildPrompt  — bangun system prompt dengan konteks tanggal WIB
  2. generate     — panggil OllamaClient untuk inferensi LLM
  3. parseResponse — parse JSON dan validasi ke ExtractionResult
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime

from loguru import logger

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("Asia/Jakarta")
except Exception:
    _TZ = None

from src.core.ollama_client import OllamaClient
from src.modules.ner.schemas import ExtractionResult


# ── System Prompt ──────────────────────────────────────────────────────────────
# Prinsip: singkat, padat, berbasis contoh.
# LLM belajar dari contoh lebih efisien dari deskripsi panjang.

_SYSTEM_PROMPT_TEMPLATE = """\
Ekstrak entitas dari kalimat kebutuhan talenta IT ke JSON.
Tanggal hari ini: {today}.

Output JSON wajib berisi field berikut (null jika tidak disebutkan):
skills, seniority, experience_years_min, location, start_date, project_sector

Aturan:
- skills: array string, normalisasi nama (typo/singkatan → nama resmi). Kata "atau" / "/" = alternatif, masukkan SEMUA opsi
- seniority: "junior" | "mid" | "senior" | null. fresh grad = junior
- experience_years_min: angka desimal, bukan string. fresh grad = 0.0
- location: nama kota lengkap (normalisasi: bdg→Bandung, jkt→Jakarta, sby→Surabaya)
- start_date: format dd/mm/yyyy. Jika hanya bulan → 01/mm/yyyy. jika mulai minggu pertama mei = 01/05/2026. Jika mulai minggu kedua = 08/05/2026, jika mulai minggu ketiga = 15/05/2026, jika mulai minggu keempat = 22/05/2026. jika mulai april/mei maka yang diambil adalah bulan pertama yaitu april maka response nya 01/04/2026, null jika tidak ada
- project_sector: sektor industri atau null

Contoh:
Q: "senior react min 3 thn, bdg, fintech, mulai 1 mei 2025"
A: {{"skills":["React.js"],"seniority":"senior","experience_years_min":3.0,"location":"Bandung","start_date":"01/05/2025","project_sector":"fintech"}}

Q: "butuh japa developer, jkt, pengalaman 5 tahun"
A: {{"skills":["Java"],"seniority":null,"experience_years_min":5.0,"location":"Jakarta","start_date":null,"project_sector":null}}

Q: "1 BE mid golang, 1 FE mid reakt, start 10 april 2026"
A: {{"skills":["Golang","React.js"],"seniority":"mid","experience_years_min":null,"location":null,"start_date":"10/04/2026","project_sector":null}}

Q: "fresh grad python, proyek perbankan"
A: {{"skills":["Python"],"seniority":"junior","experience_years_min":0.0,"location":null,"start_date":null,"project_sector":"perbankan"}}

Q: "saya butuh Js, react atau vue"
A: {{"skills":["JavaScript","React.js | Vue.js"],"seniority":null,"experience_years_min":null,"location":null,"start_date":null,"project_sector":null}}

Q: "ada talent available?"
A: {{"skills":[],"seniority":null,"experience_years_min":null,"location":null,"start_date":null,"project_sector":null}}

Kembalikan HANYA objek JSON, tanpa teks lain.\
"""


class NERExtractor:
    """
    Mengekstrak entitas kebutuhan talenta dari kalimat natural.

    Dependency injection pada constructor memudahkan unit testing —
    OllamaClient bisa diganti dengan mock tanpa menyentuh HTTP.
    """

    def __init__(self, client: OllamaClient | None = None) -> None:
        self.client = client or OllamaClient()

    async def extract(self, query: str) -> ExtractionResult:
        """
        Ekstrak entitas dari satu kalimat query.

        Parameters
        ----------
        query : str
            Kalimat kebutuhan talenta dari pengguna.

        Returns
        -------
        ExtractionResult
            Objek terstruktur berisi keenam slot entitas.
        """
        logger.info(f"Memulai ekstraksi | query='{query}'")

        today = self._get_today()
        system_prompt = self._build_prompt(today)

        raw_json = await self.client.generate(system_prompt, query)
        result = self._parse_response(raw_json, query)

        logger.info(
            f"Ekstraksi selesai | skills={result.skills} "
            f"seniority={result.seniority} location={result.location} "
            f"start_date={result.start_date}"
        )
        return result

    def _build_prompt(self, today: date) -> str:
        """Inject tanggal hari ini ke dalam system prompt."""
        return _SYSTEM_PROMPT_TEMPLATE.format(today=today.strftime("%d/%m/%Y"))

    def _parse_response(self, raw_json: str, query: str) -> ExtractionResult:
        """
        Parse teks JSON dari Ollama menjadi ExtractionResult.

        Menangani markdown code fence yang kadang muncul
        meski format:json sudah diset.
        """
        cleaned = self._clean_json_string(raw_json)

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            logger.error(f"Gagal parse JSON | error={exc} | raw={raw_json[:200]}")
            raise ValueError(f"Respons Ollama bukan JSON valid: {exc}") from exc

        # Log raw start_date dari LLM untuk debugging
        raw_date = data.get("start_date")
        logger.debug(f"Raw start_date dari LLM: {raw_date!r}")

        start_date = self._validate_start_date(raw_date)

        return ExtractionResult(
            query=query,
            skills=data.get("skills") or [],
            seniority=data.get("seniority"),
            experience_years_min=data.get("experience_years_min"),
            location=data.get("location"),
            start_date=start_date,
            project_sector=data.get("project_sector"),
        )

    def _validate_start_date(self, raw: str | None) -> str | None:
        """
        Validasi format start_date dari LLM.

        LLM sudah diinstruksikan untuk mengembalikan dd/mm/yyyy.
        Fungsi ini hanya memvalidasi dan memastikan formatnya benar.
        Kalau format tidak sesuai, kembalikan None daripada data salah.
        """
        if not raw or not isinstance(raw, str):
            return None

        raw = raw.strip()

        # Format yang diharapkan: dd/mm/yyyy
        if re.match(r"^\d{2}/\d{2}/\d{4}$", raw):
            # Validasi tanggal benar-benar valid (misal: 31/02 tidak ada)
            try:
                datetime.strptime(raw, "%d/%m/%Y")
                return raw
            except ValueError:
                logger.warning(f"Tanggal tidak valid: {raw!r}")
                return None

        # Fallback: coba parse ISO format kalau LLM mengembalikan YYYY-MM-DD
        if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
            try:
                parsed = date.fromisoformat(raw)
                converted = parsed.strftime("%d/%m/%Y")
                logger.debug(f"Konversi ISO ke dd/mm/yyyy: {raw} → {converted}")
                return converted
            except ValueError:
                pass

        logger.warning(f"Format start_date tidak dikenali: {raw!r}")
        return None

    @staticmethod
    def _clean_json_string(text: str) -> str:
        """Hapus markdown code fence kalau ada."""
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            cleaned = "\n".join(lines[1:-1]).strip()
        return cleaned

    @staticmethod
    def _get_today() -> date:
        """Kembalikan tanggal hari ini dalam timezone WIB."""
        if _TZ is not None:
            try:
                return datetime.now(_TZ).date()
            except Exception:
                pass
        return date.today()