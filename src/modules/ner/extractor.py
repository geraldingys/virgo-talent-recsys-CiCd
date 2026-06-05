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


# Prompt

_SYSTEM_PROMPT_TEMPLATE = """\
Ekstrak entitas dari kalimat kebutuhan talenta IT ke JSON.
Tanggal hari ini: {today}.

Output JSON wajib berisi field berikut (null jika tidak disebutkan):
skills, seniority, experience_years_min, location, start_date, project_sector, education

Aturan:
- skills: nested array (CNF). Outer=AND, Inner=OR.
  "A dan B"        → [["A"],["B"]]
  "A atau B"       → [["A","B"]]
  "A dan (B atau C)"→ [["A"],["B","C"]]
  Normalisasi nama (typo/singkatan → nama resmi): japa→Java, reakt→React.js, bdg-skill→sesuai
  Kata "atau" / "/" dalam satu skill group → masuk inner array yang sama
- seniority: "junior" | "mid" | "senior" | null. fresh grad = junior, expert = senior, ga jago jago amat = junior
- experience_years_min: angka desimal, bukan string. fresh grad = 0.0
- location: nama kota lengkap (normalisasi: bdg→Bandung, jkt→Jakarta, sby→Surabaya)
- start_date: format dd/mm/yyyy. Jika hanya bulan → 01/mm/yyyy. jika mulai minggu pertama mei = 01/05/2026. Jika mulai minggu kedua = 08/05/2026, jika mulai minggu ketiga = 15/05/2026, jika mulai minggu keempat = 22/05/2026. jika mulai april/mei maka yang diambil adalah bulan pertama yaitu april maka response nya 01/04/2026, Jika disebutkan rentang bulan, gunakan tanggal pertama dari bulan pertama yang disebutkan.null jika tidak ada
- project_sector: sektor industri atau null
- education: flat array jenjang pendidikan seperti SMK, ahli madya = D3, Sarjana = S1, Sarjana Terapan = D4, Magister = S2, null jika tidak. jika OR, atau, "/" artinya OR → ["SMK","D3"], 

Contoh:
Q: "senior react min 3 thn, bdg, fintech, mulai 1 mei 2026"
A: {{"skills":[["React.js"]],"seniority":"senior","experience_years_min":3,"location":"Bandung","start_date":"01/05/2026","project_sector":"fintech","education":null}}

Q: "butuh japa developer, jkt, pengalaman 5 tahun"
A: {{"skills":[["Java"]],"seniority":null,"experience_years_min":5,"location":"Jakarta","start_date":null,"project_sector":null,"education":null}}

Q: "butuh React atau Vue, D3/S1, min 3 tahun"
A: {{"skills":[["React.js","Vue.js"]],"seniority":null,"experience_years_min":3,"location":null,"start_date":null,"project_sector":null,"education":["D3","S1"]}}

Q: "Python dan (Postgres atau MySQL), S1, senior, mulai minggu pertama april 2026"
A: {{"skills":[["Python"],["PostgreSQL","MySQL"]],"seniority":"senior","experience_years_min":null,"location":null,"start_date":"01/04/2026","project_sector":null,"education":["S1"]}}

Q: "1 BE mid golang, 1 FE mid reakt, start 10 april 2026"
A: {{"skills":[["Golang"],["React.js"]],"seniority":"mid","experience_years_min":null,"location":null,"start_date":"10/04/2026","project_sector":null,"education":null}}

Q: "fresh grad python, perbankan"
A: {{"skills":[["Python"]],"seniority":"junior","experience_years_min":0.0,"location":null,"start_date":null,"project_sector":"perbankan","education":null}}

Q: "ada talent available?"
A: {{"skills":[],"seniority":null,"experience_years_min":null,"location":null,"start_date":null,"project_sector":null,"education":null}}

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
            Objek terstruktur berisi ketujuh slot entitas.
        """
        logger.info(f"Memulai ekstraksi | query='{query}'")

        today = self._get_today()
        system_prompt = self._build_prompt(today)

        raw_json = await self.client.generate(system_prompt, query)
        result = self._parse_response(raw_json, query)

        logger.info(
            f"Ekstraksi selesai | skills={result.skills} "
            f"seniority={result.seniority} location={result.location} "
            f"education={result.education}"
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

        raw_date = data.get("start_date")
        logger.debug(f"Raw start_date dari LLM: {raw_date!r}")

        start_date   = self._validate_start_date(raw_date)
        education    = self._parse_education(data.get("education"))
        experience   = self._parse_experience(data.get("experience_years_min"))

        return ExtractionResult(
            query=query,
            skills=data.get("skills") or [],
            seniority=data.get("seniority"),
            experience_years_min=experience,
            location=data.get("location"),
            start_date=start_date,
            project_sector=data.get("project_sector"),
            education=education,
        )

    def _parse_experience(self, raw: object) -> float | None:
        """
        Konversi experience_years_min ke float.

        LLM kadang mengembalikan float (3.0) meski diinstruksikan integer.
        Konversi ke float untuk konsistensi skema.
        """
        if raw is None:
            return None
        try:
            return float(str(raw))
        except (ValueError, TypeError):
            logger.warning(f"experience_years_min tidak valid: {raw!r}")
            return None

    def _parse_education(self, raw: object) -> list[str] | None:
        """
        Validasi dan normalisasi field education.

        Menerima list string atau null dari LLM.
        List kosong dikonversi ke null — tidak ada bedanya secara semantik.
        """
        if not raw:
            return None
        if not isinstance(raw, list):
            logger.warning(f"Education bukan list: {raw!r}")
            return None
        cleaned = [str(e).strip() for e in raw if e]
        return cleaned if cleaned else None

    def _validate_start_date(self, raw: str | None) -> str | None:
        """
        Validasi format start_date dari LLM (dd/mm/yyyy).

        Fallback: konversi ISO YYYY-MM-DD kalau LLM mengembalikan format itu.
        """
        if not raw or not isinstance(raw, str):
            return None

        raw = raw.strip()

        if re.match(r"^\d{2}/\d{2}/\d{4}$", raw):
            try:
                datetime.strptime(raw, "%d/%m/%Y")
                return raw
            except ValueError:
                logger.warning(f"Tanggal tidak valid: {raw!r}")
                return None

        if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
            try:
                parsed = date.fromisoformat(raw)
                converted = parsed.strftime("%d/%m/%Y")
                logger.debug(f"Konversi ISO → dd/mm/yyyy: {raw} → {converted}")
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