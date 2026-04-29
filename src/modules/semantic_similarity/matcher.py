# =============================================================
# matcher.py
# Modul Semantic Similarity — Increment 2
#
# Tanggung Jawab:
#   Mengorkestrasi pencocokan skill antara requirement
#   dan seluruh talenta menggunakan strategi Best Match Average.
#
# Strategi Best Match Average:
#   Untuk setiap skill requirement r, cari skill talenta t
#   yang paling mirip. Rata-ratakan seluruh nilai tersebut.
#
#   score(T, R) = (1/|R|) × Σ max_{t ∈ T} sim(r, t)
#
# Output:
#   List talenta beserta skor kemiripan skill,
#   diurutkan dari skor tertinggi ke terendah.
# =============================================================

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from loguru import logger
from neo4j import Driver

from .sanchez import SanchezSimilarity
from .skill_graph import SkillGraph


# ----------------------------------------------------------
# Struktur data output
# ----------------------------------------------------------

@dataclass
class SkillMatchDetail:
    """Detail kemiripan satu skill requirement dengan skill terbaik talenta."""
    required_skill  : str
    best_match_skill: str
    similarity_score: float


@dataclass
class TalentSkillScore:
    """Skor kemiripan skill satu talenta terhadap seluruh requirement."""
    nip              : str
    nama_lengkap     : str
    skill_score      : float                                    # skor akhir [0, 1]
    match_details    : list[SkillMatchDetail] = field(default_factory=list)
    talent_skills    : list[str]              = field(default_factory=list)


# ----------------------------------------------------------
# Matcher utama
# ----------------------------------------------------------

class SkillMatcher:
    """
    Menghitung skor kemiripan skill seluruh talenta terhadap
    daftar skill requirement menggunakan Best Match Average.

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

    # ----------------------------------------------------------
    # Public
    # ----------------------------------------------------------

    def match(self, required_skills: list[str]) -> list[TalentSkillScore]:
        """
        Menghitung skor kemiripan skill semua talenta terhadap
        daftar skill requirement.

        Parameters
        ----------
        required_skills : list[str]
            Label skill yang dibutuhkan (hasil NER Increment 1).

        Returns
        -------
        list[TalentSkillScore]
            Diurutkan dari skor tertinggi ke terendah.
            Talenta tanpa skill sama sekali tetap disertakan
            dengan skor 0.0.
        """
        if not required_skills:
            logger.warning("SkillMatcher: daftar required_skills kosong.")
            return []

        # Filter requirement yang ada di ontologi
        valid_requirements = [
            r for r in required_skills
            if self._graph.get_by_label(r) is not None
        ]
        missing = set(required_skills) - set(valid_requirements)
        if missing:
            logger.warning(
                f"SkillMatcher: skill berikut tidak ada di ontologi "
                f"dan dilewati: {missing}"
            )

        if not valid_requirements:
            logger.error("SkillMatcher: tidak ada requirement yang valid di ontologi.")
            return []

        # Ambil semua talenta beserta skill-nya dari Neo4j
        talent_skill_map = self._fetch_talent_skills()

        # Hitung skor per talenta
        results: list[TalentSkillScore] = []
        for (nip, nama), skill_labels in talent_skill_map.items():
            score_obj = self._compute_score(
                nip               = nip,
                nama_lengkap      = nama,
                required_skills   = valid_requirements,
                talent_skill_labels = skill_labels,
            )
            results.append(score_obj)

        # Urutkan dari skor tertinggi
        results.sort(key=lambda x: x.skill_score, reverse=True)

        logger.info(
            f"SkillMatcher: selesai menghitung {len(results)} talenta "
            f"terhadap {len(valid_requirements)} skill requirement."
        )
        return results

    # ----------------------------------------------------------
    # Private — ambil data dari Neo4j
    # ----------------------------------------------------------

    def _fetch_talent_skills(self) -> dict[tuple[str, str], list[str]]:
        """
        Mengambil semua talenta beserta label skill-nya dari Neo4j.

        Returns
        -------
        dict[tuple[nip, nama], list[label_skill]]
        """
        cypher = """
        MATCH (t:Talent)
        OPTIONAL MATCH (t)-[:HAS_SKILL]->(s:owl__Class)
        RETURN t.nip          AS nip,
               t.namaLengkap  AS nama,
               collect(s.rdfs__label) AS skills
        """
        result: dict[tuple[str, str], list[str]] = {}
        with self._driver.session(database=self._database) as session:
            records = session.run(cypher)
            for record in records:
                nip   = record["nip"]
                nama  = record["nama"] or ""
                skills = [s for s in (record["skills"] or []) if s]
                result[(nip, nama)] = skills

        logger.info(f"SkillMatcher: {len(result)} talenta dimuat dari Neo4j.")
        return result

    # ----------------------------------------------------------
    # Private — komputasi Best Match Average
    # ----------------------------------------------------------

    def _compute_score(
        self,
        nip                 : str,
        nama_lengkap        : str,
        required_skills     : list[str],
        talent_skill_labels : list[str],
    ) -> TalentSkillScore:
        """
        Menghitung Best Match Average satu talenta.

        Untuk setiap skill requirement:
          1. Cari skill talenta dengan similarity tertinggi
          2. Catat pasangan tersebut sebagai SkillMatchDetail

        Skor akhir = rata-rata dari semua best_match per requirement.
        """
        if not talent_skill_labels:
            return TalentSkillScore(
                nip          = nip,
                nama_lengkap = nama_lengkap,
                skill_score  = 0.0,
                talent_skills= [],
            )

        match_details: list[SkillMatchDetail] = []
        total_similarity = 0.0

        for req in required_skills:
            best_score = 0.0
            best_match = ""

            for talent_skill in talent_skill_labels:
                sim = self._sanchez.similarity(req, talent_skill)
                if sim > best_score:
                    best_score = sim
                    best_match = talent_skill

            match_details.append(SkillMatchDetail(
                required_skill   = req,
                best_match_skill = best_match,
                similarity_score = best_score,
            ))
            total_similarity += best_score

        # Best Match Average
        final_score = total_similarity / len(required_skills)

        return TalentSkillScore(
            nip           = nip,
            nama_lengkap  = nama_lengkap,
            skill_score   = round(final_score, 6),
            match_details = match_details,
            talent_skills = talent_skill_labels,
        )
