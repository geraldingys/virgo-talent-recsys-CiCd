"""
schemas.py

ExtractionResult adalah kontrak output modul NER.
Dataclass murni — tidak ada logika bisnis, hanya struktur data.

Diteruskan ke modul Similarity (Increment 2) sebagai input.
"""

from __future__ import annotations
from pydantic import BaseModel, Field


class ExtractionResult(BaseModel):
    """
    Hasil ekstraksi entitas dari satu kalimat query.

    Seluruh field entitas opsional — None kalau tidak disebutkan.
    """

    query: str = Field(..., description="Kalimat asli dari pengguna.")

    skills: list[str] = Field(
        default_factory=list,
        description="Daftar keahlian teknis. Contoh: ['JavaScript', 'React Js', 'Vue Js'].",
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
        description="Tanggal mulai proyek format dd/mm/yyyy. Contoh: '01/05/2025'.",
    )
    project_sector: str | None = Field(
        default=None,
        description="Sektor industri proyek. Contoh: 'perbankan', 'fintech'.",
    )