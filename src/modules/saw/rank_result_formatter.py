# =============================================================
# src/modules/saw/rank_result_formatter.py
# Modul SAW — Increment 3: Simple Additive Weighting
#
# Tanggung Jawab:
#   Mengubah hasil perankingan SAW menjadi format output final:
#   - Menempelkan label constraint (lokasi, concern perbankan)
#   - Memotong top 5 untuk tampilan utama
#   - Menyiapkan flag has_more dan total_candidates
#   - Menangani kasus khusus (0 kandidat, kurang dari 5)
#
# Catatan:
#   Lokasi dan concern perbankan BUKAN kriteria berbobot,
#   melainkan label informatif pada output (keputusan
#   communication Increment 3).
# =============================================================

from __future__ import annotations

from loguru import logger

from src.modules.saw.schemas import (
    SAWCandidate,
    RankedCandidate,
    TalentRecommendation,
    RecommendationResult,
)

# Jumlah maksimal talenta pada tampilan utama
_TOP_N: int = 5

# Pesan ketika tidak ada kandidat yang memenuhi syarat
_EMPTY_MESSAGE: str = (
    "Tidak ditemukan talenta yang sesuai dengan kriteria. "
    "Coba perluas kriteria pencarian atau hubungi Tim Talent Development."
)


class RankResultFormatter:
    """
    Mengubah hasil perankingan SAW menjadi format response final.

    Tanggung jawab utama:
    1. Menempelkan label constraint pada talenta yang memiliki
       kendala lokasi atau concern perbankan.
    2. Memotong hasil menjadi top 5 untuk tampilan utama.
    3. Menangani kasus khusus (0 kandidat, < 5 kandidat).
    """

    @staticmethod
    def format(
        ranked_candidates: list[RankedCandidate],
        candidates_data: list[SAWCandidate],
        location_query: str | None = None,
        project_sector: str | None = None,
    ) -> RecommendationResult:
        """
        Memformat hasil ranking menjadi RecommendationResult.

        Parameters
        ----------
        ranked_candidates : list[RankedCandidate]
            Kandidat terurut descending dari SAWRanker.
        candidates_data : list[SAWCandidate]
            Data lengkap kandidat (untuk cek constraint).
        location_query : str | None
            Lokasi dari kueri NER.
        project_sector : str | None
            Sektor proyek dari kueri NER.

        Returns
        -------
        RecommendationResult
            Response final dengan top 5, flag has_more, dan labels.
        """
        # Kasus: tidak ada kandidat
        if not ranked_candidates:
            logger.info(
                "RankResultFormatter: tidak ada kandidat — return pesan kosong."
            )
            return RecommendationResult(
                message=_EMPTY_MESSAGE,
                top_talents=[],
                has_more=False,
                total_candidates=0,
            )

        # Bangun lookup cepat NIP → data kandidat
        candidate_lookup: dict[str, SAWCandidate] = {c.nip: c for c in candidates_data}

        # Bangun daftar rekomendasi dengan label constraint
        recommendations: list[TalentRecommendation] = []
        for ranked in ranked_candidates:
            candidate_data = candidate_lookup.get(ranked.nip)
            constraints = RankResultFormatter._build_constraints(
                candidate_data,
                location_query,
                project_sector,
            )

            recommendations.append(
                TalentRecommendation(
                    nip=ranked.nip,
                    nama_lengkap=ranked.nama_lengkap,
                    final_score=ranked.final_score,
                    score_breakdown=ranked.score_per_criteria,
                    constraints=constraints,
                )
            )

        total = len(recommendations)
        top_talents = recommendations[:_TOP_N]
        has_more = total > _TOP_N

        logger.info(
            f"RankResultFormatter: {total} kandidat total, "
            f"menampilkan top {len(top_talents)}, "
            f"has_more={has_more}."
        )

        return RecommendationResult(
            message=None,
            top_talents=top_talents,
            has_more=has_more,
            total_candidates=total,
        )

    # ----------------------------------------------------------
    # Private — Bangun label constraint
    # ----------------------------------------------------------

    @staticmethod
    def _build_constraints(
        candidate: SAWCandidate | None,
        location_query: str | None,
        project_sector: str | None,
    ) -> list[str]:
        """
        Membangun daftar label constraint untuk satu talenta.

        Label constraint adalah informasi tambahan (bukan kriteria berbobot)
        yang membantu tim Sales membuat keputusan.

        Returns
        -------
        list[str]
            Daftar label constraint. Kosong jika tidak ada kendala.
        """
        if candidate is None:
            return []

        constraints: list[str] = []

        # Cek concern perbankan
        if project_sector and RankResultFormatter._is_banking_sector(project_sector):
            if candidate.concern_perbankan:
                constraints.append("Concern: tidak bersedia untuk proyek perbankan")

        # Cek kesesuaian lokasi
        if location_query and candidate.lokasi_penempatan:
            if not RankResultFormatter._location_matches(
                candidate.lokasi_penempatan,
                location_query,
            ):
                constraints.append(
                    f"Lokasi: tidak memiliki preferensi penempatan '{location_query}'"
                )

        return constraints

    @staticmethod
    def _is_banking_sector(sector: str) -> bool:
        """Cek apakah sektor proyek terkait perbankan."""
        banking_keywords = {"perbankan", "banking", "bank", "fintech"}
        return sector.lower().strip() in banking_keywords

    @staticmethod
    def _location_matches(
        talent_locations: list[str],
        query_location: str,
    ) -> bool:
        """
        Cek apakah talenta memiliki preferensi penempatan yang cocok.
        'Tanpa Batasan' dianggap cocok dengan lokasi apapun.
        """
        query_lower = query_location.lower().strip()
        for loc in talent_locations:
            loc_lower = loc.lower().strip()
            if loc_lower == "tanpa batasan" or loc_lower == query_lower:
                return True
        return False
