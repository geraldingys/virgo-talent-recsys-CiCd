# =============================================================
# sanchez.py
# Modul Semantic Similarity — Increment 2
#
# Tanggung Jawab:
#   Mengimplementasikan formula Information Content (IC)
#   versi Sánchez et al. (2011) dan fungsi kemiripan semantik
#   berbasis Lin dengan IC Sánchez.
#
# Referensi:
#   Sánchez, D., Batet, M., Isern, D. and Valls, A. (2012)
#   'Ontology-based semantic similarity: A new feature-based
#   approach', Expert Systems with Applications, 39(9),
#   pp. 7718-7728.
#
# Formula IC:
#   IC(c) = -log₂( |leaves(c)| / (|leaves(c)| + |subsumers(c)|) )
#
# Formula Similarity:
#   sim(a, b) = (2 × IC(LCA(a,b))) / (IC(a) + IC(b))
#
# Catatan implementasi:
#   - Kode ini tidak menggunakan library eksternal untuk
#     perhitungan IC maupun similarity (dikoding sendiri
#     sesuai keputusan desain sistem).
#   - SkillGraph digunakan sebagai sumber data hierarki.
# =============================================================

from __future__ import annotations

import math
from typing import Optional

from loguru import logger

from .skill_graph import SkillGraph


class SanchezSimilarity:
    """
    Menghitung kemiripan semantik dua skill menggunakan
    metode Sánchez berbasis struktur ontologi.

    Parameters
    ----------
    skill_graph : SkillGraph
        Graf hierarki skill yang sudah dimuat dari Neo4j.
    """

    def __init__(self, skill_graph: SkillGraph) -> None:
        self._graph = skill_graph
        self._ic_cache: dict[str, float] = {}

    # ----------------------------------------------------------
    # Public
    # ----------------------------------------------------------

    def ic(self, uri: str) -> float:
        """
        Menghitung Information Content sebuah skill node.

        IC(c) = -log₂( |leaves(c)| / (|leaves(c)| + |subsumers(c)|) )

        Nilai IC mendekati 0 untuk konsep umum (root),
        dan meningkat untuk konsep yang lebih spesifik.

        Parameters
        ----------
        uri : str
            URI node skill di ontologi.

        Returns
        -------
        float
            Nilai IC. Mengembalikan 0.0 jika node tidak ditemukan.
        """
        if uri in self._ic_cache:
            return self._ic_cache[uri]

        leaves_count    = len(self._graph.leaves(uri))
        subsumers_count = len(self._graph.subsumers(uri))

        if leaves_count == 0 or subsumers_count == 0:
            self._ic_cache[uri] = 0.0
            return 0.0

        # Formula Sánchez: argumen log selalu (0, 1] → IC selalu ≥ 0
        ratio = leaves_count / (leaves_count + subsumers_count)
        ic_value = -math.log2(ratio)

        self._ic_cache[uri] = ic_value
        return ic_value

    def similarity(self, label_a: str, label_b: str) -> float:
        """
        Menghitung kemiripan semantik dua skill berdasarkan label.

        sim(a, b) = (2 × IC(LCA(a, b))) / (IC(a) + IC(b))

        Menggunakan formula Lin (1998) dengan IC versi Sánchez.

        Parameters
        ----------
        label_a : str
            Label skill pertama (sesuai rdfs:label di ontologi).
        label_b : str
            Label skill kedua.

        Returns
        -------
        float
            Nilai kemiripan antara 0.0 (tidak mirip) dan 1.0 (identik).
        """
        # Kasus identik — kembalikan langsung tanpa traversal
        if label_a.lower() == label_b.lower():
            return 1.0

        # Resolve label ke URI
        node_a = self._graph.get_by_label(label_a)
        node_b = self._graph.get_by_label(label_b)

        if node_a is None:
            logger.warning(f"SanchezSimilarity: label '{label_a}' tidak ada di ontologi.")
            return 0.0
        if node_b is None:
            logger.warning(f"SanchezSimilarity: label '{label_b}' tidak ada di ontologi.")
            return 0.0

        ic_a = self.ic(node_a.uri)
        ic_b = self.ic(node_b.uri)
        denominator = ic_a + ic_b

        # Jika keduanya IC = 0 (root atau tidak ditemukan)
        if denominator == 0.0:
            return 0.0

        # Cari LCA
        lca_uri = self._graph.lca(node_a.uri, node_b.uri)
        if lca_uri is None:
            return 0.0

        ic_lca = self.ic(lca_uri)

        sim = (2 * ic_lca) / denominator

        # Clamp ke [0, 1] untuk keamanan numerik
        return max(0.0, min(1.0, sim))

    def similarity_by_uri(self, uri_a: str, uri_b: str) -> float:
        """
        Versi similarity yang menerima URI langsung.
        Digunakan secara internal oleh BestMatchAggregator.
        """
        if uri_a == uri_b:
            return 1.0

        ic_a = self.ic(uri_a)
        ic_b = self.ic(uri_b)
        denominator = ic_a + ic_b

        if denominator == 0.0:
            return 0.0

        lca_uri = self._graph.lca(uri_a, uri_b)
        if lca_uri is None:
            return 0.0

        sim = (2 * self.ic(lca_uri)) / denominator
        return max(0.0, min(1.0, sim))

    def precompute_all_ic(self) -> None:
        """
        Menghitung IC seluruh node skill sekaligus dan menyimpannya
        di cache. Dipanggil saat startup untuk mempercepat query
        pertama.
        """
        logger.info("SanchezSimilarity: precomputing IC untuk semua skill ...")
        for uri in self._graph.all_uris():
            self.ic(uri)
        logger.info(
            f"SanchezSimilarity: IC untuk {len(self._ic_cache)} node selesai dihitung."
        )
