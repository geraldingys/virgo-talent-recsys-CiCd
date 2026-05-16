# =============================================================
# skill_requirement.py
# Modul Semantic Similarity — Increment 2
#
# Format input dari NER:
#   [
#     ["React.js"],                  # satu kebutuhan (AND)
#     ["PostgreSQL", "MySQL"],       # alternatif dalam grup (OR)
#   ]
#
# Semantik:
#   - Array luar  : setiap grup digabung AND (Best Match Average antar grup)
#   - Array dalam : >1 skill = OR (ambil skor tertinggi di grup)
#
# Referensi agregasi disjungtif:
#   Yager, R.R. (1988) 'On ordered weighted averaging aggregation
#   operators in multicriteria decisionmaking', IEEE Transactions
#   on Systems, Man, and Cybernetics, 18(1), pp. 183–190.
# =============================================================

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SkillRequirement:
    """
    Satu unit kebutuhan skill dari NER.

    Jika is_disjunctive=True, matcher mengambil skor tertinggi
    dari semua alternatif dalam skills (OR logic).

    Jika is_disjunctive=False, skills berisi satu elemen (kebutuhan tunggal).
    """
    skills         : list[str]
    is_disjunctive : bool = False

    @property
    def label(self) -> str:
        """Label ringkas untuk logging dan response."""
        if self.is_disjunctive:
            return " | ".join(self.skills)
        return self.skills[0]


def parse_requirements(raw: list[list[str]]) -> list[SkillRequirement]:
    """
    Memparse skill requirement bertingkat dari NER.

    Parameters
    ----------
    raw : list[list[str]]
        Contoh: [["React.js"], ["PostgreSQL", "MySQL"]]

    Returns
    -------
    list[SkillRequirement]
    """
    parsed: list[SkillRequirement] = []

    for group in raw:
        skills = [s.strip() for s in group if isinstance(s, str) and s.strip()]
        if not skills:
            continue

        parsed.append(SkillRequirement(
            skills         = skills,
            is_disjunctive = len(skills) > 1,
        ))

    return parsed
