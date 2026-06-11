# =============================================================
# src/modules/saw/schemas.py
# Modul SAW — Increment 3: Simple Additive Weighting
#
# Tanggung Jawab:
#   Mendefinisikan seluruh model data (Pydantic dan dataclass)
#   yang digunakan modul SAW, meliputi:
#   - Request/response schema untuk endpoint POST /saw/rank
#   - Domain object internal (TalentProfile, SAWCandidate, dll.)
#   - Konstanta mapping nilai kriteria
#
# Catatan:
#   - Ejaan status penugasan mengikuti data existing di Neo4j
#     ("irreplacable", "replacable" — tanpa huruf 'e')
#   - Skema penilaian pendidikan menggunakan opsi B (≥ threshold)
#     sesuai keputusan development; ditandai TODO jika berubah
# =============================================================

from __future__ import annotations

from dataclasses import dataclass, field
from pydantic import BaseModel, Field


# ----------------------------------------------------------
# Konstanta — Mapping nilai kriteria
# ----------------------------------------------------------

# Skor numerik untuk status ketersediaan talenta.
# Ejaan mengikuti data existing di Neo4j (lihat transformer.py:31)
_AVAILABILITY_SCORES: dict[str, float] = {
    "idle": 4.0,
    "replacable": 2.0,  # ejaan sesuai data Neo4j (tanpa 'e')
    "transferable": 1.0,
}

# Status yang di-filter sebelum SAW (hard exclusion)
_EXCLUDED_STATUS: str = "irreplacable"  # ejaan sesuai data Neo4j

# Urutan jenjang pendidikan dari terendah ke tertinggi.
# Digunakan untuk skema penilaian ≥ threshold.
_EDUCATION_RANK: dict[str, int] = {
    "SMA": 1,
    "SMK": 1,
    "D1": 2,
    "D2": 3,
    "D3": 4,
    "D4": 5,
    "S1": 6,
    "S2": 7,
    "S3": 8,
}

# Nilai valid pendidikan (untuk validasi)
_VALID_EDUCATION: set[str] = set(_EDUCATION_RANK.keys())


# ----------------------------------------------------------
# Request schema — input dari n8n
# ----------------------------------------------------------


class TalentScoreInput(BaseModel):
    """Satu talenta dari output endpoint /similarity/rank."""

    nip: str = Field(..., description="NIP unik talenta")
    nama_lengkap: str = Field(..., description="Nama lengkap talenta")
    skill_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Skor kemiripan skill dari Sánchez Similarity (0.0–1.0)",
    )


class SAWRankRequest(BaseModel):
    """
    Request body untuk POST /saw/rank.
    Dikirim oleh n8n setelah memanggil /ner/extract dan /similarity/rank.
    """

    talent_scores: list[TalentScoreInput] = Field(
        ...,
        min_length=1,
        description="Daftar talenta beserta skor skill dari /similarity/rank",
    )
    location: str | None = Field(
        default=None,
        description="Lokasi penempatan dari NER (mis. 'Bandung')",
    )
    project_sector: str | None = Field(
        default=None,
        description="Sektor proyek dari NER (mis. 'perbankan')",
    )
    education: list[str] | None = Field(
        default=None,
        description="Jenjang pendidikan dari NER (mis. ['S1', 'D4']), selalu OR",
    )


# ----------------------------------------------------------
# Domain objects — internal modul SAW
# ----------------------------------------------------------


@dataclass
class TalentProfile:
    """
    Profil talenta yang diambil dari Neo4j.
    Digunakan untuk menggabungkan data profil dengan skill_score.
    """

    nip: str
    nama_lengkap: str
    ketersediaan: str  # "idle" | "replacable" | "transferable" | "irreplacable"
    pendidikan: str | None
    pengalaman_tahun: float
    lokasi_penempatan: list[str] = field(default_factory=list)
    concern_perbankan: bool = False


@dataclass
class SAWCandidate:
    """
    Kandidat SAW setelah merge skill_score + profil Neo4j.
    Hanya berisi talenta yang lolos filter hard exclusion.
    """

    nip: str
    nama_lengkap: str
    skill_score: float
    ketersediaan: str
    pendidikan: str | None
    pengalaman_tahun: float
    lokasi_penempatan: list[str] = field(default_factory=list)
    concern_perbankan: bool = False


@dataclass
class RankedCandidate:
    """
    Hasil perankingan SAW per kandidat.
    Menyimpan skor akhir dan breakdown skor per kriteria.
    """

    nip: str
    nama_lengkap: str
    final_score: float
    score_per_criteria: dict[str, float] = field(default_factory=dict)


# ----------------------------------------------------------
# Response schema — output ke n8n
# ----------------------------------------------------------


class TalentRecommendation(BaseModel):
    """Satu talenta dalam hasil rekomendasi, beserta label constraint."""

    nip: str
    nama_lengkap: str
    final_score: float = Field(..., description="Skor akhir SAW (0.0–1.0)")
    score_breakdown: dict[str, float] = Field(
        default_factory=dict,
        description="Breakdown skor per kriteria (mis. {'ketersediaan': 0.52, 'skill': 0.14})",
    )
    constraints: list[str] = Field(
        default_factory=list,
        description="Label constraint informatif (mis. ['Concern: tidak mau proyek perbankan'])",
    )


class RecommendationResult(BaseModel):
    """
    Response envelope untuk POST /saw/rank.
    Mengembalikan top 5 talenta dengan opsi 'more'.
    """

    message: str | None = Field(
        default=None,
        description="Pesan informatif jika tidak ada kandidat yang memenuhi syarat",
    )
    top_talents: list[TalentRecommendation] = Field(
        default_factory=list,
        description="Maksimal 5 talenta teratas",
    )
    has_more: bool = Field(
        default=False,
        description="True jika masih ada kandidat di luar top 5",
    )
    total_candidates: int = Field(
        default=0,
        description="Total kandidat yang lolos filter (sebelum slicing top 5)",
    )
