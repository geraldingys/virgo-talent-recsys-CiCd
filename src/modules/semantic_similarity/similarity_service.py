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
#   1. Saat startup: load SkillGraph dari Neo4j, precompute IC
#   2. Saat request: terima required_skills, kembalikan ranked list
# =============================================================

from __future__ import annotations

from typing import Optional

from loguru import logger
from neo4j import Driver

from .skill_graph import SkillGraph
from .sanchez import SanchezSimilarity
from .matcher import SkillMatcher, TalentSkillScore


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
        Memuat graf skill dari Neo4j dan menghitung IC semua node.
        Dipanggil satu kali saat lifespan startup FastAPI.
        """
        logger.info("SemanticSimilarityService: inisialisasi ...")
        self._skill_graph = SkillGraph(self._driver, self._database)
        self._sanchez     = SanchezSimilarity(self._skill_graph)
        self._sanchez.precompute_all_ic()
        self._matcher     = SkillMatcher(
            driver      = self._driver,
            skill_graph = self._skill_graph,
            sanchez     = self._sanchez,
            database    = self._database,
        )
        logger.info("SemanticSimilarityService: siap.")

    def reload(self) -> None:
        """
        Memuat ulang graf skill dan IC dari Neo4j.
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
            Label skill dari hasil NER Increment 1.

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
