# =============================================================
# sanchez.py
# Modul Semantic Similarity — Increment 2
#
# Tanggung Jawab:
#   Mengimplementasikan semantic similarity feature-based
#   ala Sánchez dari himpunan subsumers (tanpa IC / LCA).
#
# Formula:
#   φ(a)      = himpunan subsumers dari a (termasuk dirinya)
#   union     = φ(a) ∪ φ(b)
#   sym_diff  = φ(a) Δ φ(b)
#   disnorm   = log2(1 + |sym_diff| / |union|)
#   sim(a, b) = 1 - disnorm
# =============================================================

from __future__ import annotations

import math
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

    # ----------------------------------------------------------
    # Public
    # ----------------------------------------------------------

    def similarity(self, label_a: str, label_b: str) -> float:
        """
        Menghitung kemiripan semantik dua skill berdasarkan label.

        Menggunakan feature-based similarity ala Sánchez
        dari himpunan subsumers.

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

        node_a = self._graph.get_by_label(label_a)
        node_b = self._graph.get_by_label(label_b)

        if node_a is None:
            logger.warning(f"SanchezSimilarity: label '{label_a}' tidak ada di ontologi.")
            return 0.0
        if node_b is None:
            logger.warning(f"SanchezSimilarity: label '{label_b}' tidak ada di ontologi.")
            return 0.0

        return self.similarity_by_uri(node_a.uri, node_b.uri)

    def similarity_by_uri(self, uri_a: str, uri_b: str) -> float:
        """
        Versi similarity yang menerima URI langsung.
        Digunakan secara internal oleh BestMatchAggregator.
        """
        if uri_a == uri_b:
            return 1.0

        phi_a = self._graph.subsumers(uri_a)
        phi_b = self._graph.subsumers(uri_b)

        union = phi_a | phi_b
        if not union:
            return 0.0

        sym_diff = phi_a.symmetric_difference(phi_b)
        disnorm = math.log2(1 + len(sym_diff) / len(union))
        return max(0.0, min(1.0, 1 - disnorm))
