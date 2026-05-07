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

    # ----------------------------------------------------------
    # Private — load dari Neo4j
    # ----------------------------------------------------------

    def _load(self) -> None:
        """
        Memuat seluruh node skill dan relasi subClassOf dari Neo4j.
        Prioritas memuat node ontologi Padepokan79. Jika tidak ada,
        fallback ke seluruh node owl__Class agar service tetap jalan.
        """
        logger.info("SkillGraph: memuat hierarki skill dari Neo4j ...")

        with self._driver.session(database=self._database) as session:
            # Prioritas: ambil node skill namespace ontology utama
            node_result = session.run("""
                MATCH (s:owl__Class)
                WHERE s.uri CONTAINS "padepokan79"
                RETURN s.uri AS uri, s.rdfs__label AS label
            """)
            node_records = list(node_result)

            # Fallback: jika namespace utama belum ada, muat seluruh owl__Class
            if not node_records:
                logger.warning(
                    "SkillGraph: tidak menemukan node dengan uri mengandung "
                    "'padepokan79'. Fallback ke semua :owl__Class."
                )
                node_records = list(session.run("""
                    MATCH (s:owl__Class)
                    RETURN s.uri AS uri, s.rdfs__label AS label
                """))
            for record in node_records:
                uri   = record["uri"]
                if not uri:
                    continue
                label = record["label"] or uri.split("#")[-1]
                self._nodes[uri] = SkillNode(uri=uri, label=label)
                self._label_index[label.lower()] = uri

            # Ambil relasi subClassOf dan simpan hanya jika kedua node termuat
            rel_result = session.run("""
                MATCH (child:owl__Class)-[:rdfs__subClassOf]->(parent:owl__Class)
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
