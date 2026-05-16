# =============================================================
# matcher.py — grup OR (array dalam) + lookup similarity Neo4j
# Modul Semantic Similarity — Increment 2
#
# Mendukung format requirement dari NER:
#   [["React.js"], ["PostgreSQL", "MySQL"]]
#
# Strategi agregasi:
#   - Untuk setiap SkillRequirement (grup skill):
#       * Jika is_disjunctive=True: ambil skor tertinggi dari
#         semua kombinasi (skill_requirement × skill_talenta)
#         → OR logic (Yager, 1988)
#       * Jika is_disjunctive=False: satu skill, cari best match
#         dari skill talenta biasa
#   - Skor akhir = rata-rata skor semua grup (Best Match Average)
#
# Sumber similarity:
#   - Utama : relasi [:SKILL_SIMILARITY] di Neo4j (precomputed)
#   - Fallback : SanchezSimilarity.similarity() langsung
# =============================================================

from __future__ import annotations

from dataclasses import dataclass, field

from loguru import logger
from neo4j import Driver

from .sanchez import SanchezSimilarity
from .skill_graph import SkillGraph
from .skill_requirement import SkillRequirement, parse_requirements


@dataclass
class SkillMatchDetail:
    required_skill  : str    # label grup, misal "React.js | Vue.js"
    best_match_skill: str    # skill talenta dengan skor tertinggi
    similarity_score: float
    source          : str = "neo4j"   # "neo4j" | "computed"


@dataclass
class TalentSkillScore:
    nip           : str
    nama_lengkap  : str
    skill_score   : float
    match_details : list[SkillMatchDetail] = field(default_factory=list)
    talent_skills : list[str]              = field(default_factory=list)


class SkillMatcher:
    """
    Menghitung skor kemiripan skill seluruh talenta terhadap
    daftar skill requirement menggunakan Best Match Average
    dengan dukungan kebutuhan disjungtif (grup OR dalam array).
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

    def match(self, required_skills: list[list[str]]) -> list[TalentSkillScore]:
        """
        Parameters
        ----------
        required_skills : list[list[str]]
            Format dari NER: grup luar = AND, grup dalam (>1) = OR.
            Contoh: [["React.js"], ["PostgreSQL", "MySQL"]]
        """
        if not required_skills:
            return []

        requirements = parse_requirements(required_skills)

        # Validasi semua skill di setiap grup
        valid_requirements: list[SkillRequirement] = []
        for req in requirements:
            valid_skills = [
                s for s in req.skills
                if self._graph.get_by_label(s) is not None
            ]
            missing = set(req.skills) - set(valid_skills)
            if missing:
                logger.warning(
                    f"SkillMatcher: skill tidak ditemukan di ontologi, "
                    f"dibuang dari grup '{req.label}': {missing}"
                )
            if valid_skills:
                valid_requirements.append(SkillRequirement(
                    skills         = valid_skills,
                    is_disjunctive = req.is_disjunctive,
                ))

        if not valid_requirements:
            logger.error("SkillMatcher: tidak ada requirement valid di ontologi.")
            return []

        # Kumpulkan URI semua skill dari semua grup
        req_uris: dict[str, str] = {}
        for req in valid_requirements:
            for skill in req.skills:
                node = self._graph.get_by_label(skill)
                if node:
                    req_uris[skill] = node.uri

        # Tentukan mode: Neo4j atau fallback computed
        use_neo4j        = self._check_similarity_available()
        talent_skill_map = self._fetch_talent_skills()

        results: list[TalentSkillScore] = []
        for (nip, nama), skill_labels in talent_skill_map.items():
            if use_neo4j:
                score_obj = self._compute_score_from_neo4j(
                    nip, nama, valid_requirements, req_uris, skill_labels
                )
            else:
                score_obj = self._compute_score_fallback(
                    nip, nama, valid_requirements, skill_labels
                )
            results.append(score_obj)

        results.sort(key=lambda x: x.skill_score, reverse=True)
        logger.info(
            f"SkillMatcher: {len(results)} talenta dihitung "
            f"({'Neo4j' if use_neo4j else 'computed'})."
        )
        return results

    # ----------------------------------------------------------
    # Private — cek ketersediaan SKILL_SIMILARITY
    # ----------------------------------------------------------

    def _check_similarity_available(self) -> bool:
        cypher = """
        MATCH ()-[r:SKILL_SIMILARITY]->()
        RETURN count(r) AS total LIMIT 1
        """
        with self._driver.session(database=self._database) as session:
            result = session.run(cypher).single()
            total  = result["total"] if result else 0
        if total == 0:
            logger.warning(
                "SkillMatcher: SKILL_SIMILARITY belum ada. "
                "Fallback ke perhitungan langsung. "
                "Jalankan POST /etl/recompute-ic untuk mengaktifkan Neo4j mode."
            )
            return False
        return True

    # ----------------------------------------------------------
    # Private — ambil data talenta dari Neo4j
    # ----------------------------------------------------------

    def _fetch_talent_skills(self) -> dict[tuple[str, str], list[str]]:
        cypher = """
        MATCH (t:Talent)
        OPTIONAL MATCH (t)-[:HAS_SKILL]->(s:owl__Class)
        RETURN t.nip         AS nip,
               t.namaLengkap AS nama,
               collect(s.rdfs__label) AS skills
        """
        result: dict[tuple[str, str], list[str]] = {}
        with self._driver.session(database=self._database) as session:
            for record in session.run(cypher):
                nip    = record["nip"]
                nama   = record["nama"] or ""
                skills = [s for s in (record["skills"] or []) if s]
                result[(nip, nama)] = skills
        return result

    # ----------------------------------------------------------
    # Private — hitung skor dari Neo4j (mode utama)
    # ----------------------------------------------------------

    def _compute_score_from_neo4j(
        self,
        nip                 : str,
        nama_lengkap        : str,
        requirements        : list[SkillRequirement],
        req_uris            : dict[str, str],
        talent_skill_labels : list[str],
    ) -> TalentSkillScore:

        if not talent_skill_labels:
            return TalentSkillScore(
                nip=nip, nama_lengkap=nama_lengkap, skill_score=0.0
            )

        # URI skill talenta yang ditemukan di ontologi
        talent_uris: dict[str, str] = {}
        for label in talent_skill_labels:
            node = self._graph.get_by_label(label)
            if node:
                talent_uris[label] = node.uri

        if not talent_uris:
            return TalentSkillScore(
                nip=nip, nama_lengkap=nama_lengkap,
                skill_score=0.0, talent_skills=talent_skill_labels
            )

        # Query similarity semua req_uri vs semua talent_uri sekaligus
        cypher = """
        UNWIND $req_uris AS req_uri
        UNWIND $talent_uris AS talent_uri
        OPTIONAL MATCH (a:owl__Class {uri: req_uri})
                   -[r:SKILL_SIMILARITY]-
                   (b:owl__Class {uri: talent_uri})
        RETURN req_uri    AS req_uri,
               talent_uri AS talent_uri,
               CASE
                 WHEN req_uri = talent_uri THEN 1.0
                 ELSE coalesce(r.score, 0.0)
               END AS score
        """
        # sim_matrix[req_uri][talent_uri] = score
        sim_matrix: dict[str, dict[str, float]] = {
            uri: {} for uri in req_uris.values()
        }
        with self._driver.session(database=self._database) as session:
            for record in session.run(cypher, {
                "req_uris"    : list(req_uris.values()),
                "talent_uris" : list(talent_uris.values()),
            }):
                req_uri    = record["req_uri"]
                talent_uri = record["talent_uri"]
                if req_uri in sim_matrix:
                    sim_matrix[req_uri][talent_uri] = record["score"]

        # Best Match Average dengan dukungan disjunctive
        match_details    : list[SkillMatchDetail] = []
        total_similarity : float                  = 0.0

        for req in requirements:
            best_score : float = 0.0
            best_label : str   = ""

            # Untuk setiap alternatif di grup requirement
            for req_skill in req.skills:
                req_uri    = req_uris.get(req_skill)
                scores_row = sim_matrix.get(req_uri, {}) if req_uri else {}

                # Bandingkan dengan setiap skill talenta
                for talent_label, talent_uri in talent_uris.items():
                    score = scores_row.get(talent_uri, 0.0)
                    if score > best_score:
                        best_score = score
                        best_label = talent_label

            match_details.append(SkillMatchDetail(
                required_skill   = req.label,
                best_match_skill = best_label,
                similarity_score = best_score,
                source           = "neo4j",
            ))
            total_similarity += best_score

        final_score = total_similarity / len(requirements)

        return TalentSkillScore(
            nip           = nip,
            nama_lengkap  = nama_lengkap,
            skill_score   = round(final_score, 6),
            match_details = match_details,
            talent_skills = talent_skill_labels,
        )

    # ----------------------------------------------------------
    # Private — fallback jika SKILL_SIMILARITY belum ada
    # ----------------------------------------------------------

    def _compute_score_fallback(
        self,
        nip                 : str,
        nama_lengkap        : str,
        requirements        : list[SkillRequirement],
        talent_skill_labels : list[str],
    ) -> TalentSkillScore:

        if not talent_skill_labels:
            return TalentSkillScore(
                nip=nip, nama_lengkap=nama_lengkap, skill_score=0.0
            )

        match_details    : list[SkillMatchDetail] = []
        total_similarity : float                  = 0.0

        for req in requirements:
            best_score : float = 0.0
            best_label : str   = ""

            # Untuk setiap alternatif di grup requirement
            for req_skill in req.skills:
                for talent_skill in talent_skill_labels:
                    sim = self._sanchez.similarity(req_skill, talent_skill)
                    if sim > best_score:
                        best_score = sim
                        best_label = talent_skill

            match_details.append(SkillMatchDetail(
                required_skill   = req.label,
                best_match_skill = best_label,
                similarity_score = best_score,
                source           = "computed",
            ))
            total_similarity += best_score

        return TalentSkillScore(
            nip           = nip,
            nama_lengkap  = nama_lengkap,
            skill_score   = round(total_similarity / len(requirements), 6),
            match_details = match_details,
            talent_skills = talent_skill_labels,
        )
