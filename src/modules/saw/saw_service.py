# =============================================================
# src/modules/saw/saw_service.py
# Modul SAW — Increment 3: Simple Additive Weighting
#
# Tanggung Jawab:
#   Orchestrator utama modul SAW (GRASP Controller).
#   Mengkoordinasi seluruh langkah perankingan multi-kriteria:
#   1. Query profil talenta dari Neo4j
#   2. Merge skill_score dari input n8n dengan profil Neo4j
#   3. Filter hard exclusion (irreplaceable)
#   4. Tentukan kriteria aktif (n=3 atau n=4)
#   5. Hitung bobot ROC
#   6. Jalankan SAW ranking
#   7. Format hasil dengan label constraint
#
# Catatan:
#   - SAWService bersifat read-only terhadap Neo4j
#   - Stateless — diinstansiasi per request di router
#   - Mengikuti pola dependency injection (driver via constructor)
# =============================================================

from __future__ import annotations

from loguru import logger
from neo4j import Driver

from src.modules.saw.schemas import (
    SAWRankRequest,
    TalentProfile,
    SAWCandidate,
    RecommendationResult,
    _EXCLUDED_STATUS,
)
from src.modules.saw.roc_weight_calculator import ROCWeightCalculator
from src.modules.saw.saw_ranker import SAWRanker
from src.modules.saw.rank_result_formatter import RankResultFormatter


class SAWService:
    """
    Orchestrator utama modul SAW (GRASP Controller).

    Menerima TalentScoreInput[] dari n8n (output /similarity/rank),
    mengambil profil lengkap dari Neo4j, lalu menjalankan SAW
    multi-kriteria dengan bobot ROC.

    Parameters
    ----------
    driver : neo4j.Driver
        Neo4j driver instance (dari app.state).
    database : str
        Nama database Neo4j (default: "neo4j").
    """

    def __init__(self, driver: Driver, database: str = "neo4j") -> None:
        self._driver = driver
        self._database = database

    def rank(self, request: SAWRankRequest) -> RecommendationResult:
        """
        Menjalankan seluruh alur perankingan SAW.

        Parameters
        ----------
        request : SAWRankRequest
            Request body dari endpoint POST /saw/rank.

        Returns
        -------
        RecommendationResult
            Hasil rekomendasi dengan top 5 talenta dan label constraint.
        """
        # ── 1. Ambil daftar NIP dari input ────────────────────
        nip_list = [ts.nip for ts in request.talent_scores]
        logger.info(
            f"SAWService: menerima {len(nip_list)} talenta untuk diranking."
        )

        # ── 2. Query profil talenta dari Neo4j ────────────────
        profiles = self._get_talent_profiles(nip_list)
        logger.info(
            f"SAWService: {len(profiles)} profil ditemukan di Neo4j "
            f"dari {len(nip_list)} NIP yang diminta."
        )

        # ── 3. Merge skill_score + profil → SAWCandidate ──────
        skill_score_map: dict[str, float] = {
            ts.nip: ts.skill_score for ts in request.talent_scores
        }
        candidates = self._merge_candidates(profiles, skill_score_map)

        # ── 4. Filter hard exclusion (irreplaceable) ──────────
        before_filter = len(candidates)
        candidates = [
            c for c in candidates
            if c.ketersediaan != _EXCLUDED_STATUS
        ]
        filtered_count = before_filter - len(candidates)
        if filtered_count > 0:
            logger.info(
                f"SAWService: {filtered_count} talenta dikeluarkan "
                f"(status '{_EXCLUDED_STATUS}')."
            )

        # ── 5. Cek apakah ada kandidat tersisa ────────────────
        if not candidates:
            logger.warning(
                "SAWService: tidak ada kandidat tersisa setelah filter. "
                "Mengembalikan pesan informatif."
            )
            return RankResultFormatter.format(
                ranked_candidates=[],
                candidates_data=[],
                location_query=request.location,
                project_sector=request.project_sector,
            )

        # ── 6. Tentukan kriteria aktif ────────────────────────
        education_query = request.education
        has_education = (
            education_query is not None and len(education_query) > 0
        )
        n_criteria = 4 if has_education else 3
        logger.info(
            f"SAWService: {n_criteria} kriteria aktif "
            f"({'dengan' if has_education else 'tanpa'} pendidikan)."
        )

        # ── 7. Hitung bobot ROC ───────────────────────────────
        weights = ROCWeightCalculator.get_weights(n_criteria)

        # ── 8. Jalankan SAW ranking ───────────────────────────
        ranked = SAWRanker.rank(
            candidates=candidates,
            weights=weights,
            education_query=education_query,
        )

        # ── 9. Format hasil dengan label constraint ───────────
        result = RankResultFormatter.format(
            ranked_candidates=ranked,
            candidates_data=candidates,
            location_query=request.location,
            project_sector=request.project_sector,
        )

        logger.info(
            f"SAWService: selesai. "
            f"{result.total_candidates} kandidat diranking, "
            f"menampilkan top {len(result.top_talents)}."
        )
        return result

    # ----------------------------------------------------------
    # Private — Query profil talenta dari Neo4j
    # ----------------------------------------------------------

    def _get_talent_profiles(self, nip_list: list[str]) -> list[TalentProfile]:
        """
        Mengambil profil talenta dari Neo4j berdasarkan daftar NIP.

        Query mengembalikan data ketersediaan, pendidikan, pengalaman,
        lokasi penempatan, dan concern perbankan untuk setiap talenta.

        Parameters
        ----------
        nip_list : list[str]
            Daftar NIP yang akan di-query.

        Returns
        -------
        list[TalentProfile]
            Profil talenta dari Neo4j. Talenta yang tidak ditemukan
            akan di-skip dengan warning log.
        """
        query = """
        MATCH (t:Talent)
        WHERE t.nip IN $nip_list
        OPTIONAL MATCH (t)-[:PREFERS_PLACEMENT]->(p:Placement)
        RETURN t.nip AS nip,
               t.namaLengkap AS nama_lengkap,
               t.statusPenugasan AS ketersediaan,
               t.pendidikan AS pendidikan,
               t.pengalamanTahun AS pengalaman_tahun,
               t.concernPerbankan AS concern_perbankan,
               collect(p.namaLokasi) AS lokasi_penempatan
        """

        profiles: list[TalentProfile] = []

        with self._driver.session(
            database=self._database,
        ) as session:
            result = session.run(query, nip_list=nip_list)

            for record in result:
                nip = record["nip"]
                if nip is None:
                    continue

                # Tangani nilai null dari Neo4j
                pengalaman_raw = record["pengalaman_tahun"]
                pengalaman = float(pengalaman_raw) if pengalaman_raw is not None else 0.0

                concern_raw = record["concern_perbankan"]
                concern = bool(concern_raw) if concern_raw is not None else False

                ketersediaan_raw = record["ketersediaan"]
                ketersediaan = str(ketersediaan_raw).strip().lower() if ketersediaan_raw else "idle"

                lokasi_raw = record["lokasi_penempatan"]
                lokasi = [loc for loc in lokasi_raw if loc is not None] if lokasi_raw else []

                profiles.append(
                    TalentProfile(
                        nip=nip,
                        nama_lengkap=record["nama_lengkap"] or nip,
                        ketersediaan=ketersediaan,
                        pendidikan=record["pendidikan"],
                        pengalaman_tahun=pengalaman,
                        lokasi_penempatan=lokasi,
                        concern_perbankan=concern,
                    )
                )

        not_found = set(nip_list) - {p.nip for p in profiles}
        if not_found:
            logger.warning(
                f"SAWService: {len(not_found)} NIP tidak ditemukan di Neo4j: "
                f"{sorted(not_found)[:5]}{'...' if len(not_found) > 5 else ''}"
            )

        return profiles

    # ----------------------------------------------------------
    # Private — Merge skill_score + profil
    # ----------------------------------------------------------

    @staticmethod
    def _merge_candidates(
        profiles: list[TalentProfile],
        skill_score_map: dict[str, float],
    ) -> list[SAWCandidate]:
        """
        Menggabungkan profil Neo4j dengan skill_score dari input n8n.

        Parameters
        ----------
        profiles : list[TalentProfile]
            Profil talenta dari Neo4j.
        skill_score_map : dict[str, float]
            Mapping NIP → skill_score dari TalentScoreInput.

        Returns
        -------
        list[SAWCandidate]
            Kandidat SAW yang siap untuk diranking.
        """
        candidates: list[SAWCandidate] = []

        for profile in profiles:
            skill_score = skill_score_map.get(profile.nip, 0.0)

            candidates.append(
                SAWCandidate(
                    nip=profile.nip,
                    nama_lengkap=profile.nama_lengkap,
                    skill_score=skill_score,
                    ketersediaan=profile.ketersediaan,
                    pendidikan=profile.pendidikan,
                    pengalaman_tahun=profile.pengalaman_tahun,
                    lokasi_penempatan=profile.lokasi_penempatan,
                    concern_perbankan=profile.concern_perbankan,
                )
            )

        return candidates
