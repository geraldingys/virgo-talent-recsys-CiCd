# =============================================================
# similarity_service.py
# Modul Semantic Similarity — Increment 2
#
# Tanggung Jawab:
#   Menyediakan satu titik akses (service layer) untuk
#   seluruh operasi semantic similarity.
#   Diinstansiasi sekali saat startup FastAPI (singleton).
#
# Alur kerja:
#   1. Saat startup: load SkillGraph dan inisialisasi matcher.
#   2. Saat request: matcher baca [:SKILL_SIMILARITY] jika ada,
#      selain itu fallback Sánchez di memori (dukungan | pada requirement).
#   3. POST /etl/recompute-ic: hitung ulang relasi similarity ke Neo4j.
# =============================================================

from __future__ import annotations

from typing import Optional

from loguru import logger
from neo4j import Driver

from .ic_precompute_v2 import ICPrecomputer, PrecomputeReport
from .matcher import SkillMatcher, TalentSkillScore
from .skill_graph import SkillGraph
from .sanchez import SanchezSimilarity


class SemanticSimilarityService:
    """
    Service layer untuk semantic similarity.
    Diinstansiasi satu kali di lifespan FastAPI.

    Parameters
    ----------
    driver   : neo4j.Driver
    database : str
    """

    def __init__(self, driver: Driver, database: str = "neo4j") -> None:
        self._driver   = driver
        self._database = database

        # Komponen utama — diinisialisasi saat startup
        self._skill_graph : Optional[SkillGraph]         = None
        self._sanchez     : Optional[SanchezSimilarity]  = None
        self._matcher     : Optional[SkillMatcher]       = None

    def initialize(self) -> None:
        """
        Memuat graf skill dari Neo4j dan menginisialisasi matcher.
        Dipanggil satu kali saat lifespan startup FastAPI.
        """
        logger.info("SemanticSimilarityService: inisialisasi ...")
        self._skill_graph = SkillGraph(self._driver, self._database)
        self._sanchez     = SanchezSimilarity(self._skill_graph)
        self._matcher     = SkillMatcher(
            driver      = self._driver,
            skill_graph = self._skill_graph,
            sanchez     = self._sanchez,
            database    = self._database,
        )
        logger.info("SemanticSimilarityService: siap.")

    def reload(self) -> None:
        """
        Memuat ulang graf skill dari Neo4j.
        Dipanggil setelah ETL sync selesai.
        """
        logger.info("SemanticSimilarityService: reload graf skill ...")
        self.initialize()

    def rank_talents(self, required_skills: list[str]) -> list[TalentSkillScore]:
        """
        Menghitung skor kemiripan skill seluruh talenta
        terhadap daftar skill requirement.

        Parameters
        ----------
        required_skills : list[str]
            Label skill dari NER; satu string dapat memuat beberapa alternatif
            dipisah | (contoh: "React.js|Vue.js").

        Returns
        -------
        list[TalentSkillScore]
            Diurutkan dari skor tertinggi ke terendah.
        """
        if self._matcher is None:
            raise RuntimeError(
                "SemanticSimilarityService belum diinisialisasi. "
                "Panggil initialize() dulu."
            )
        return self._matcher.match(required_skills)

    def recompute_ic_similarity(self) -> PrecomputeReport:
        """
        Menghitung ulang relasi [:SKILL_SIMILARITY] di Neo4j.
        Dipanggil dari POST /etl/recompute-ic setelah ontologi berubah.
        """
        if self._skill_graph is None or self._sanchez is None:
            raise RuntimeError(
                "SemanticSimilarityService belum diinisialisasi. "
                "Panggil initialize() dulu."
            )
        precomputer = ICPrecomputer(
            driver      = self._driver,
            skill_graph = self._skill_graph,
            sanchez     = self._sanchez,
            database    = self._database,
        )
        return precomputer.run()
