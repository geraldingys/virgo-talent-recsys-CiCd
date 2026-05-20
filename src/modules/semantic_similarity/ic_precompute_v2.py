# =============================================================
# ic_precompute.py (v2 — similarity disimpan di relasi)
# Modul Semantic Similarity — Increment 2
#
# Tanggung Jawab:
#   Menghitung similarity seluruh pasangan skill dan
#   menyimpannya sebagai relasi [:SKILL_SIMILARITY]
#   antar node (:owl__Class).
#
# Struktur yang dihasilkan di Neo4j:
#
#   (:owl__Class {rdfs__label: "React.js"})
#       -[:SKILL_SIMILARITY {score: 0.75}]->
#   (:owl__Class {rdfs__label: "Vue.js"})
#
# Catatan:
#   - Relasi bersifat undirected secara logika tapi disimpan
#     satu arah (a→b jika uri_a < uri_b secara leksikografis)
#     untuk mencegah duplikat.
#   - Setiap kali ontologi diperbarui, jalankan ulang endpoint
#     POST /etl/recompute-ic untuk menghapus dan menghitung ulang.
#   - Penulisan ke Neo4j menggunakan UNWIND dalam batch kecil
#     (500 pasangan per transaksi) untuk menghindari timeout.
# =============================================================

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field

from loguru import logger
from neo4j import Driver

from .skill_graph import SkillGraph
from .sanchez import SanchezSimilarity

_BATCH_SIZE = 500


@dataclass
class PrecomputeReport:
    total_nodes        : int = 0
    total_pairs        : int = 0
    similarity_written : int = 0
    errors             : list[dict] = field(default_factory=list)
    duration_seconds   : float = 0.0


class ICPrecomputer:
    """
    Menghitung similarity semua pasangan skill,
    lalu menyimpannya ke Neo4j.

    Parameters
    ----------
    driver      : neo4j.Driver
    skill_graph : SkillGraph
    sanchez     : SanchezSimilarity
    database    : str
    """

    def __init__(
        self,
        driver      : Driver,
        skill_graph : SkillGraph,
        sanchez     : SanchezSimilarity,
        database    : str = "neo4j",
    ) -> None:
        self._driver      = driver
        self._graph       = skill_graph
        self._sanchez     = sanchez
        self._database    = database

    def run(self) -> PrecomputeReport:
        """
        Pipeline precompute lengkap:
        1. Hapus relasi SKILL_SIMILARITY lama
        2. Hitung similarity semua pasangan → simpan ke relasi
        """
        start  = time.perf_counter()
        report = PrecomputeReport()

        all_uris           = self._graph.all_uris()
        report.total_nodes = len(all_uris)
        report.total_pairs = len(all_uris) * (len(all_uris) - 1) // 2

        logger.info(
            f"ICPrecomputer: mulai. "
            f"{report.total_nodes} node, "
            f"{report.total_pairs} pasangan."
        )

        # ── Fase 0: Hapus data lama ──────────────────────────
        self._clear_old_data()

        # ── Fase 1: Hitung similarity semua pasangan ─────────
        logger.info("Fase 1/1 — Menghitung similarity semua pasangan ...")

        sim_batch     : list[dict] = []
        total_written : int        = 0

        for uri_a, uri_b in itertools.combinations(all_uris, 2):
            score = self._sanchez.similarity_by_uri(uri_a, uri_b)
            sim_batch.append({
                "uri_a": uri_a,
                "uri_b": uri_b,
                "score": round(score, 6),
            })

            if len(sim_batch) >= _BATCH_SIZE:
                written, errors = self._write_similarity_batch(sim_batch)
                total_written  += written
                report.errors.extend(errors)
                sim_batch = []
                logger.info(
                    f"  Progress: {total_written}/{report.total_pairs} pasangan ..."
                )

        # Tulis sisa batch terakhir
        if sim_batch:
            written, errors = self._write_similarity_batch(sim_batch)
            total_written  += written
            report.errors.extend(errors)

        report.similarity_written = total_written
        report.duration_seconds   = round(time.perf_counter() - start, 3)

        logger.info(
            f"ICPrecomputer: selesai. "
            f"Similarity: {report.similarity_written}/{report.total_pairs} pasangan. "
            f"Durasi: {report.duration_seconds}s."
        )
        return report

    # ----------------------------------------------------------
    # Private
    # ----------------------------------------------------------

    def _clear_old_data(self) -> None:
        logger.info("ICPrecomputer: menghapus relasi SKILL_SIMILARITY lama ...")
        cypher = """
        MATCH ()-[r:SKILL_SIMILARITY]->()
        CALL (r) { DELETE r }
        IN TRANSACTIONS OF 1000 ROWS
        """
        with self._driver.session(database=self._database) as session:
            session.run(cypher)
        logger.info("ICPrecomputer: relasi lama dihapus.")

    def _write_similarity_batch(
        self, batch: list[dict]
    ) -> tuple[int, list[dict]]:
        """
        Menulis satu batch pasangan sebagai relasi [:SKILL_SIMILARITY].
        Relasi disimpan satu arah (uri_a → uri_b).
        Saat query, gunakan relasi tanpa arah: MATCH (a)-[:SKILL_SIMILARITY]-(b)
        """
        cypher = """
        UNWIND $rows AS row
        MATCH (a:owl__Class {uri: row.uri_a})
        MATCH (b:owl__Class {uri: row.uri_b})
        MERGE (a)-[r:SKILL_SIMILARITY]->(b)
        SET r.score = row.score
        """
        errors  : list[dict] = []
        written : int        = 0
        try:
            with self._driver.session(database=self._database) as session:
                session.run(cypher, rows=batch).consume()
                written = len(batch)
        except Exception as exc:
            logger.error(f"ICPrecomputer: gagal tulis similarity — {exc}")
            errors.append({"phase": "similarity", "error": str(exc)})
        return written, errors

