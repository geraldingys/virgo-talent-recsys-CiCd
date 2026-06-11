# =============================================================
# src/modules/saw/saw_ranker.py
# Modul SAW — Increment 3: Simple Additive Weighting
#
# Tanggung Jawab:
#   Membangun matriks keputusan dari kandidat SAW, melakukan
#   normalisasi benefit, dan menghitung skor preferensi akhir.
#
# Langkah Algoritma SAW:
#   1. Build decision matrix — mapping nilai mentah ke numerik
#   2. Normalize (benefit) — hybrid:
#        bounded criteria → r_ij = x_ij / max_teoritis
#        unbounded criteria → r_ij = x_ij / max(x_j)
#   3. Compute preference — S_i = Σ(w_j × r_ij)
#   4. Sort descending
#
# Catatan:
#   - Seluruh kriteria bersifat benefit (tidak ada cost)
#   - Skema pendidikan: ≥ threshold
#     TODO: konfirmasi final skema penilaian pendidikan
# =============================================================

from __future__ import annotations

from loguru import logger

from src.modules.saw.schemas import (
    SAWCandidate,
    RankedCandidate,
    _AVAILABILITY_SCORES,
    _EDUCATION_RANK,
)


class SAWRanker:
    """
    Melakukan perankingan SAW terhadap daftar kandidat.

    Menerima kandidat yang sudah lolos filter hard exclusion
    beserta vektor bobot ROC, lalu menghitung skor preferensi
    akhir dan mengurutkan secara descending.

    Semua kriteria bersifat benefit. Normalisasi menggunakan pendekatan Hybrid:
    - Bounded criteria (ketersediaan, skill, pendidikan) menggunakan batas maksimum teoritis.
    - Unbounded criteria (pengalaman) menggunakan nilai maksimum aktual di pool.
    """

    @staticmethod
    def rank(
        candidates: list[SAWCandidate],
        weights: dict[str, float],
        education_query: list[str] | None = None,
    ) -> list[RankedCandidate]:
        """
        Menghitung skor SAW dan mengurutkan kandidat.

        Parameters
        ----------
        candidates : list[SAWCandidate]
            Kandidat yang sudah lolos filter hard exclusion.
        weights : dict[str, float]
            Bobot ROC per kriteria dari ROCWeightCalculator.
        education_query : list[str] | None
            Jenjang pendidikan dari kueri NER (mis. ["S1"]).
            None jika kueri tidak menyebutkan pendidikan.

        Returns
        -------
        list[RankedCandidate]
            Kandidat terurut descending berdasarkan skor akhir.
        """
        if not candidates:
            logger.warning("SAWRanker: tidak ada kandidat untuk diranking.")
            return []

        active_criteria = list(weights.keys())
        logger.info(
            f"SAWRanker: ranking {len(candidates)} kandidat "
            f"dengan {len(active_criteria)} kriteria: {active_criteria}"
        )

        # 1. Bangun matriks keputusan (nilai numerik per kriteria)
        matrix = SAWRanker._build_decision_matrix(
            candidates,
            active_criteria,
            education_query,
        )

        # 2. Normalisasi benefit: r_ij = x_ij / max(x_j)
        normalized = SAWRanker._normalize_benefit(matrix, active_criteria)

        # 3. Hitung skor preferensi: S_i = Σ(w_j × r_ij)
        results = SAWRanker._compute_preference_scores(
            candidates,
            normalized,
            weights,
            active_criteria,
        )

        # 4. Urutkan descending; tiebreaker: NIP ascending (deterministik)
        results.sort(key=lambda r: (-r.final_score, r.nip))

        logger.info(
            f"SAWRanker: perankingan selesai. "
            f"Skor tertinggi: {results[0].final_score:.4f} "
            f"({results[0].nama_lengkap})"
        )
        return results

    # ----------------------------------------------------------
    # Private — Bangun matriks keputusan
    # ----------------------------------------------------------

    @staticmethod
    def _build_decision_matrix(
        candidates: list[SAWCandidate],
        active_criteria: list[str],
        education_query: list[str] | None,
    ) -> list[dict[str, float]]:
        """
        Mengubah nilai mentah setiap kandidat menjadi nilai numerik
        untuk setiap kriteria aktif.

        Returns
        -------
        list[dict[str, float]]
            Satu dict per kandidat, key = nama kriteria, value = skor numerik.
        """
        matrix: list[dict[str, float]] = []

        for candidate in candidates:
            row: dict[str, float] = {}

            if "ketersediaan" in active_criteria:
                row["ketersediaan"] = _AVAILABILITY_SCORES.get(
                    candidate.ketersediaan,
                    0.0,
                )

            if "skill" in active_criteria:
                row["skill"] = candidate.skill_score

            if "pengalaman" in active_criteria:
                row["pengalaman"] = max(candidate.pengalaman_tahun, 0.0)

            if "pendidikan" in active_criteria:
                row["pendidikan"] = SAWRanker._score_education(
                    candidate.pendidikan,
                    education_query,
                )

            matrix.append(row)

        return matrix

    # ----------------------------------------------------------
    # Private — Skor pendidikan (≥ threshold)
    # ----------------------------------------------------------

    @staticmethod
    def _score_education(
        talent_education: str | None,
        education_query: list[str] | None,
    ) -> float:
        """
        Menghitung skor pendidikan menggunakan skema ≥ threshold.

        Logika:
        - Jika pendidikan talenta ≥ jenjang tertinggi dalam kueri → 1.0
        - Jika tidak memenuhi → 0.0

        TODO: konfirmasi final skema penilaian pendidikan dengan
        pemangku kepentingan. Opsi lain: exact match, proporsional.

        Parameters
        ----------
        talent_education : str | None
            Pendidikan talenta (mis. "S1").
        education_query : list[str] | None
            Jenjang pendidikan yang diminta kueri (mis. ["S1", "D4"]).

        Returns
        -------
        float
            1.0 jika memenuhi syarat, 0.0 jika tidak.
        """
        if not education_query or not talent_education:
            return 0.0

        talent_rank = _EDUCATION_RANK.get(talent_education, 0)

        # Ambil jenjang tertinggi dari kueri sebagai threshold minimum
        query_max_rank = max(
            (_EDUCATION_RANK.get(edu, 0) for edu in education_query),
            default=0,
        )

        # Opsi B: talenta memenuhi jika pendidikan ≥ threshold
        return 1.0 if talent_rank >= query_max_rank else 0.0

    # ----------------------------------------------------------
    # Private — Normalisasi benefit
    # ----------------------------------------------------------

    @staticmethod
    def _normalize_benefit(
        matrix: list[dict[str, float]],
        active_criteria: list[str],
    ) -> list[dict[str, float]]:
        """
        Normalisasi benefit dengan pendekatan Hybrid:
        - Bounded criteria (ketersediaan, skill, pendidikan) dinormalisasi
          secara absolut terhadap batas atas teoritisnya.
        - Unbounded criteria (pengalaman) dinormalisasi secara relatif
          terhadap nilai maksimum aktual dari kandidat di dalam pool.

        Returns
        -------
        list[dict[str, float]]
            Matriks ternormalisasi (0.0–1.0 per kriteria).
        """
        # Cari nilai maksimum untuk kriteria relatif (pengalaman)
        max_exp = 0.0
        if "pengalaman" in active_criteria:
            exp_values = [row.get("pengalaman", 0.0) for row in matrix]
            max_exp = max(exp_values) if exp_values else 0.0
            if max_exp == 0.0:
                logger.warning(
                    "SAWRanker: max(pengalaman) = 0 — seluruh kandidat "
                    "mendapat skor 0 untuk kriteria pengalaman."
                )

        # Normalisasi setiap sel
        normalized: list[dict[str, float]] = []
        for row in matrix:
            norm_row: dict[str, float] = {}
            for criterion in active_criteria:
                raw_val = row.get(criterion, 0.0)
                if criterion == "ketersediaan":
                    # Batas maksimum teoritis untuk status 'idle' adalah 4.0
                    norm_row["ketersediaan"] = raw_val / 4.0
                elif criterion == "skill":
                    # Batas maksimum teoritis Sánchez similarity adalah 1.0
                    norm_row["skill"] = raw_val / 1.0
                elif criterion == "pendidikan":
                    # Batas maksimum teoritis biner (Opsi B) adalah 1.0
                    norm_row["pendidikan"] = raw_val / 1.0
                elif criterion == "pengalaman":
                    norm_row["pengalaman"] = (
                        (raw_val / max_exp) if max_exp > 0.0 else 0.0
                    )
                else:
                    # Fallback jika ada kriteria lain di masa depan
                    norm_row[criterion] = raw_val
            normalized.append(norm_row)

        return normalized

    # ----------------------------------------------------------
    # Private — Hitung skor preferensi
    # ----------------------------------------------------------

    @staticmethod
    def _compute_preference_scores(
        candidates: list[SAWCandidate],
        normalized: list[dict[str, float]],
        weights: dict[str, float],
        active_criteria: list[str],
    ) -> list[RankedCandidate]:
        """
        Menghitung skor preferensi akhir: S_i = Σ(w_j × r_ij).

        Returns
        -------
        list[RankedCandidate]
            Belum diurutkan; pengurutan dilakukan di method rank().
        """
        results: list[RankedCandidate] = []

        for i, candidate in enumerate(candidates):
            norm_row = normalized[i]
            score_per_criteria: dict[str, float] = {}
            total_score = 0.0

            for criterion in active_criteria:
                weighted = weights[criterion] * norm_row.get(criterion, 0.0)
                score_per_criteria[criterion] = round(weighted, 4)
                total_score += weighted

            results.append(
                RankedCandidate(
                    nip=candidate.nip,
                    nama_lengkap=candidate.nama_lengkap,
                    final_score=round(total_score, 4),
                    score_per_criteria=score_per_criteria,
                )
            )

        return results
