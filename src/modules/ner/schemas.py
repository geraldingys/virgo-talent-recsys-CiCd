"""
schemas.py

ExtractionResult adalah kontrak output modul NER.
Dataclass murni — tidak ada logika bisnis, hanya struktur data.

Diteruskan ke modul Similarity (Increment 2) sebagai input.
"""

from __future__ import annotations
from pydantic import BaseModel, Field, field_validator


class ExtractionResult(BaseModel):
    """
    Hasil ekstraksi entitas dari satu kalimat query.

    Seluruh field entitas opsional — None kalau tidak disebutkan.

    Struktur skills (CNF — Conjunctive Normal Form):
        Outer array = AND  → semua slot harus terpenuhi
        Inner array = OR   → salah satu dalam slot cukup

        Contoh:
            [["React.js", "Vue.js"]]          → React ATAU Vue
            [["Python"], ["PostgreSQL"]]       → Python DAN PostgreSQL
            [["Python"], ["PostgreSQL","MySQL"]]→ Python DAN (Postgres ATAU MySQL)

    Struktur education (flat array = selalu OR):
        ["D3", "S1"]  → D3 atau S1
    """

    query: str = Field(
        ...,
        description="Kalimat asli dari pengguna.",
    )
    skills: list[list[str]] = Field(
        default_factory=list,
        description=(
            "CNF nested array. Outer=AND, Inner=OR. "
            "Contoh AND+OR: [['Python'],['PostgreSQL','MySQL']]"
        ),
    )
    seniority: str | None = Field(
        default=None,
        description="Tingkat senioritas: 'junior', 'mid', atau 'senior'.",
    )
    experience_years_min: float | None = Field(
        default=None,
        description="Durasi pengalaman minimum dalam tahun. Contoh: 3.0.",
    )
    location: str | None = Field(
        default=None,
        description="Kota penempatan (nama lengkap). Contoh: 'Bandung'.",
    )
    start_date: str | None = Field(
        default=None,
        description="Tanggal mulai proyek format dd/mm/yyyy. Contoh: '01/05/2026'.",
    )
    project_sector: str | None = Field(
        default=None,
        description="Sektor industri proyek. Contoh: 'perbankan', 'fintech'.",
    )
    education: list[str] | None = Field(
        default=None,
        description=(
            "Jenjang pendidikan minimum (flat array, selalu OR). "
            "Contoh: ['D3', 'S1']. null jika tidak disebutkan."
        ),
    )

    @field_validator("skills", mode="before")
    @classmethod
    def normalise_skills(cls, v: object) -> list[list[str]]:
        """
        Toleransi terhadap LLM yang mengembalikan flat array.

        Kalau LLM mengembalikan ["Python", "React"] (flat),
        konversi otomatis ke [["Python"], ["React"]] (AND semua).
        Ini fallback — prompt sudah menginstruksikan nested array.
        """
        if not v:
            return []
        if isinstance(v, list) and v and isinstance(v[0], str):
            # flat array dari LLM — wrap tiap elemen
            return [[skill] for skill in v]
        return v