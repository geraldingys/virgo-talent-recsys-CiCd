# =============================================================
# skill_graph.py
# Modul Semantic Similarity — Increment 2
#
# Tanggung Jawab:
#   Mengambil data struktur hierarki skill dari Neo4j dan
#   menyimpannya sebagai graf lokal di memori (cache).
#   Data ini digunakan oleh SanchezIC untuk menghitung
#   leaves dan subsumers setiap node tanpa query berulang.
#
# Strategi:
#   Satu kali load saat aplikasi startup, disimpan sebagai
#   dict Python. Refresh manual via endpoint /etl/sync.
# =============================================================

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from loguru import logger
from neo4j import Driver, GraphDatabase


@dataclass
class SkillNode:
    """Representasi satu node skill dari ontologi."""
    uri     : str
    label   : str
    parents : list[str] = field(default_factory=list)   # URI parent langsung
    children: list[str] = field(default_factory=list)   # URI child langsung


class SkillGraph:
    """
    Graf hierarki skill yang dimuat dari Neo4j ke memori.

    Menyediakan:
    - lookup node via URI atau label
    - daftar semua ancestors (subsumers) sebuah node
    - daftar semua leaf descendants sebuah node
    - LCA (Least Common Ancestor) dua node

    Parameters
    ----------
    driver   : neo4j.Driver
    database : str
    """

    def __init__(self, driver: Driver, database: str = "neo4j") -> None:
        self._driver   = driver
        self._database = database

        # Struktur utama: uri → SkillNode
        self._nodes: dict[str, SkillNode] = {}

        # Lookup cepat: label.lower() → uri
        self._label_index: dict[str, str] = {}

        # Cache komputasi (dihitung sekali, dipakai berulang)
        self._ancestors_cache : dict[str, frozenset[str]] = {}
        self._leaves_cache    : dict[str, frozenset[str]] = {}

        self._load()

    # ----------------------------------------------------------
    # Public — lookup
    # ----------------------------------------------------------

    def get_by_label(self, label: str) -> Optional[SkillNode]:
        uri = self._label_index.get(label.lower())
        return self._nodes.get(uri) if uri else None

    def get_by_uri(self, uri: str) -> Optional[SkillNode]:
        return self._nodes.get(uri)

    def all_uris(self) -> list[str]:
        return list(self._nodes.keys())

    # ----------------------------------------------------------
    # Public — komputasi hierarki
    # ----------------------------------------------------------

    def subsumers(self, uri: str) -> frozenset[str]:
        """
        Mengembalikan semua leluhur node termasuk node itu sendiri.
        Hasil di-cache setelah komputasi pertama.
        """
        if uri in self._ancestors_cache:
            return self._ancestors_cache[uri]

        visited: set[str] = set()
        queue = [uri]
        while queue:
            current = queue.pop()
            if current in visited:
                continue
            visited.add(current)
            node = self._nodes.get(current)
            if node:
                queue.extend(node.parents)

        result = frozenset(visited)
        self._ancestors_cache[uri] = result
        return result

    def leaves(self, uri: str) -> frozenset[str]:
        """
        Mengembalikan semua leaf node keturunan dari uri,
        termasuk uri itu sendiri jika tidak punya child.
        """
        if uri in self._leaves_cache:
            return self._leaves_cache[uri]

        # Kumpulkan seluruh keturunan via BFS ke bawah
        all_descendants: set[str] = set()
        queue = [uri]
        while queue:
            current = queue.pop()
            if current in all_descendants:
                continue
            all_descendants.add(current)
            node = self._nodes.get(current)
            if node:
                queue.extend(node.children)

        # Leaf = keturunan yang tidak punya child
        leaf_set: set[str] = set()
        for desc_uri in all_descendants:
            node = self._nodes.get(desc_uri)
            if node and len(node.children) == 0:
                leaf_set.add(desc_uri)

        # Jika node itu sendiri tidak punya child, ia adalah leaf
        self_node = self._nodes.get(uri)
        if self_node and len(self_node.children) == 0:
            leaf_set.add(uri)

        result = frozenset(leaf_set)
        self._leaves_cache[uri] = result
        return result

    def lca(self, uri_a: str, uri_b: str) -> Optional[str]:
        """
        Menghitung Least Common Ancestor (LCA) dua skill.
        LCA = ancestor bersama yang paling dalam (paling sedikit subsumers-nya).
        """
        ancestors_a = self.subsumers(uri_a)
        ancestors_b = self.subsumers(uri_b)
        common = ancestors_a & ancestors_b

        if not common:
            return None

        # LCA = node dengan jumlah subsumers terbanyak (paling spesifik)
        return max(
            common,
            key=lambda u: len(self.subsumers(u)),
        )

    # ----------------------------------------------------------
    # Private — load dari Neo4j
    # ----------------------------------------------------------

    def _load(self) -> None:
        """
        Memuat seluruh node skill dan relasi subClassOf dari Neo4j.
        Hanya memuat node yang berasal dari ontologi Padepokan79.
        """
        logger.info("SkillGraph: memuat hierarki skill dari Neo4j ...")

        with self._driver.session(database=self._database) as session:
            # Ambil semua node skill ontologi
            node_result = session.run("""
                MATCH (s:owl__Class)
                WHERE s.uri CONTAINS "padepokan79"
                RETURN s.uri AS uri, s.rdfs__label AS label
            """)
            for record in node_result:
                uri   = record["uri"]
                label = record["label"] or uri.split("#")[-1]
                self._nodes[uri] = SkillNode(uri=uri, label=label)
                self._label_index[label.lower()] = uri

            # Ambil semua relasi subClassOf antar node skill
            rel_result = session.run("""
                MATCH (child:owl__Class)-[:rdfs__subClassOf]->(parent:owl__Class)
                WHERE child.uri  CONTAINS "padepokan79"
                  AND parent.uri CONTAINS "padepokan79"
                RETURN child.uri AS child_uri, parent.uri AS parent_uri
            """)
            for record in rel_result:
                child_uri  = record["child_uri"]
                parent_uri = record["parent_uri"]
                if child_uri in self._nodes:
                    self._nodes[child_uri].parents.append(parent_uri)
                if parent_uri in self._nodes:
                    self._nodes[parent_uri].children.append(child_uri)

        logger.info(
            f"SkillGraph: {len(self._nodes)} node skill dimuat."
        )
