# =============================================================
# src/modules/saw/roc_weight_calculator.py
# Modul SAW — Increment 3: Simple Additive Weighting
#
# Tanggung Jawab:
#   Menghitung vektor bobot dari urutan kriteria menggunakan
#   metode Rank Order Centroid (ROC).
#
# Referensi:
#   Barron, F.H. & Barrett, B.E. (1996) 'Decision quality using
#   ranked attribute weights', Management Science, 42(11),
#   pp. 1515–1523.
#
# Keputusan Desain:
#   Bobot di-hardcode sebagai konstanta bernama karena merupakan
#   bagian logika bisnis yang sudah final (bukan konfigurasi
#   antar lingkungan). Method _compute_roc() tetap disediakan
#   untuk keperluan verifikasi dan dokumentasi formula.
# =============================================================

from __future__ import annotations

from loguru import logger


# ----------------------------------------------------------
# Bobot ROC — Hardcoded
# ----------------------------------------------------------

# Empat kriteria aktif (kueri menyebutkan pendidikan)
# Urutan prioritas: ketersediaan > pendidikan > skill > pengalaman
_WEIGHTS_4_CRITERIA: dict[str, float] = {
    "ketersediaan": 0.5208,
    "pendidikan": 0.2708,
    "skill": 0.1458,
    "pengalaman": 0.0625,
}

# Tiga kriteria aktif (kueri TIDAK menyebutkan pendidikan)
# Urutan prioritas: ketersediaan > skill > pengalaman
_WEIGHTS_3_CRITERIA: dict[str, float] = {
    "ketersediaan": 0.6111,
    "skill": 0.2778,
    "pengalaman": 0.1111,
}


class ROCWeightCalculator:
    """
    Menghitung vektor bobot berdasarkan metode Rank Order Centroid (ROC).

    Modul ini menyediakan bobot yang sudah dihitung untuk dua skenario
    (n=3 dan n=4) sesuai hasil communication Increment 3. Formula ROC
    tetap tersedia sebagai method verifikasi.

    Formula ROC:
        w_i = (1/n) × Σ(1/j) untuk j = i sampai n

    Contoh (n=4, i=1):
        w_1 = (1/4) × (1/1 + 1/2 + 1/3 + 1/4) = 0.5208
    """

    @staticmethod
    def get_weights(n_criteria: int) -> dict[str, float]:
        """
        Mengembalikan vektor bobot ROC berdasarkan jumlah kriteria aktif.

        Parameters
        ----------
        n_criteria : int
            Jumlah kriteria aktif (3 atau 4).

        Returns
        -------
        dict[str, float]
            Mapping nama kriteria → bobot ROC.

        Raises
        ------
        ValueError
            Jika n_criteria bukan 3 atau 4.
        """
        if n_criteria == 4:
            logger.debug(f"ROC: menggunakan bobot 4 kriteria — {_WEIGHTS_4_CRITERIA}")
            return _WEIGHTS_4_CRITERIA.copy()

        if n_criteria == 3:
            logger.debug(f"ROC: menggunakan bobot 3 kriteria — {_WEIGHTS_3_CRITERIA}")
            return _WEIGHTS_3_CRITERIA.copy()

        raise ValueError(
            f"Jumlah kriteria aktif harus 3 atau 4, diterima: {n_criteria}. "
            f"Saat ini hanya pendidikan yang bersifat kondisional."
        )

    @staticmethod
    def _compute_roc(n: int) -> list[float]:
        """
        Menghitung bobot ROC dari formula untuk n kriteria.
        Disediakan untuk verifikasi dan dokumentasi, bukan untuk runtime.

        Parameters
        ----------
        n : int
            Jumlah kriteria.

        Returns
        -------
        list[float]
            Daftar bobot w_1 sampai w_n.
        """
        weights: list[float] = []
        for i in range(1, n + 1):
            w_i = (1 / n) * sum(1 / j for j in range(i, n + 1))
            weights.append(round(w_i, 4))
        return weights
