# =============================================================
# skill_requirement.py
# Modul Semantic Similarity — Increment 2
#
# Tanggung Jawab:
#   Memparse format skill requirement yang mengandung operator
#   disjungtif (|) menjadi struktur yang siap diolah matcher.
#
# Format input dari NER:
#   ["React.js|Vue.js", "Node.js", "PostgreSQL"]
#
# Hasil parse:
#   [
#     SkillRequirement(skills=["React.js", "Vue.js"], is_disjunctive=True),
#     SkillRequirement(skills=["Node.js"],             is_disjunctive=False),
#     SkillRequirement(skills=["PostgreSQL"],           is_disjunctive=False),
#   ]
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

    Jika is_disjunctive=False, skills selalu berisi tepat satu
    elemen dan diperlakukan sebagai kebutuhan tunggal.
    """
    skills         : list[str]
    is_disjunctive : bool = False

    @property
    def label(self) -> str:
        """Label ringkas untuk logging dan response."""
        return " | ".join(self.skills)


def parse_requirements(raw: list[str]) -> list[SkillRequirement]:
    """
    Memparse list skill requirement mentah dari NER.

    Parameters
    ----------
    raw : list[str]
        Contoh: ["React.js|Vue.js", "Node.js", "PostgreSQL"]

    Returns
    -------
    list[SkillRequirement]
    """
    parsed: list[SkillRequirement] = []

    for item in raw:
        item = item.strip()
        if not item:
            continue

        if "|" in item:
            alternatives = [s.strip() for s in item.split("|") if s.strip()]
            parsed.append(SkillRequirement(
                skills         = alternatives,
                is_disjunctive = True,
            ))
        else:
            parsed.append(SkillRequirement(
                skills         = [item],
                is_disjunctive = False,
            ))

    return parsed
