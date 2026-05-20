# =============================================================
# validator.py
# ETL module - Semantic Similarity
#
# Responsibilities:
# 1) Structural validation (fast)
# 2) Optional reasoner validation (HermiT) + inferred type extraction
# =============================================================

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from loguru import logger

try:
    import owlready2 as owl
    from owlready2 import sync_reasoner_hermit
    from rdflib import Graph

    _OWL_AVAILABLE = True
except ImportError:
    _OWL_AVAILABLE = False
    logger.error("owlready2 atau rdflib tidak ditemukan.")


@dataclass
class ValidationResult:
    nip: str
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    inferred_types: list[str] = field(default_factory=list)


class OntologyValidator:
    """
    Load ontology T-Box from Turtle (.ttl) and validate TalentRecord.
    """

    def __init__(self, ttl_path: str | Path) -> None:
        if not _OWL_AVAILABLE:
            raise RuntimeError("owlready2 tidak tersedia.")

        self._ttl_path = Path(ttl_path).expanduser().resolve()
        self._onto: Optional[owl.Ontology] = None
        self._skill_label_map: dict[str, owl.ThingClass] = {}
        self._valid_placements = {
            "bandung",
            "remote",
            "tanpa batasan",
            "jakarta",
        }

        self._load_ontology()

    def validate(self, record) -> ValidationResult:
        result = ValidationResult(nip=record.nip, is_valid=True)

        self._check_nip(record, result)
        self._check_placement(record, result)
        self._check_skills(record, result)

        if not result.is_valid:
            return result

        self._run_reasoner_check(record, result)
        return result

    def get_skill_class(self, label: str) -> Optional[owl.ThingClass]:
        return self._skill_label_map.get(label.lower())

    def get_skill_uri(self, label: str) -> Optional[str]:
        cls = self.get_skill_class(label)
        return cls.iri if cls else None

    def _load_ontology(self) -> None:
        logger.info(f"OntologyValidator: memuat ontologi dari {self._ttl_path} ...")
        if not self._ttl_path.exists():
            raise FileNotFoundError(f"File ontologi tidak ditemukan: {self._ttl_path}")

        world = owl.World()
        self._onto = self._load_turtle_ontology(world)

        count = 0
        for cls in self._onto.classes():
            labels = cls.label
            if labels:
                for lbl in labels:
                    self._skill_label_map[str(lbl).lower()] = cls
                    count += 1
            else:
                self._skill_label_map[cls.name.lower()] = cls
                count += 1

        logger.info(f"OntologyValidator: {count} label skill terindeks.")

    def _load_turtle_ontology(self, world: owl.World) -> owl.Ontology:
        graph = Graph()
        graph.parse(self._ttl_path.as_posix(), format="turtle")

        temp_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".rdf", delete=False, encoding="utf-8"
            ) as f:
                f.write(graph.serialize(format="xml"))
                temp_path = Path(f.name)

            return world.get_ontology(temp_path.as_uri()).load()
        finally:
            if temp_path and temp_path.exists():
                temp_path.unlink()

    def _check_nip(self, record, result: ValidationResult) -> None:
        if not str(record.nip).strip():
            result.is_valid = False
            result.errors.append("NIP kosong atau tidak valid.")

    def _check_placement(self, record, result: ValidationResult) -> None:
        placements = record.jenis_penempatan
        if isinstance(placements, str):
            placements = [placements]

        normalized = [str(p).strip().lower() for p in placements if str(p).strip()]
        if not normalized:
            result.is_valid = False
            result.errors.append("Jenis Penempatan kosong atau tidak valid.")
            return

        for p in normalized:
            if p not in self._valid_placements:
                result.is_valid = False
                result.errors.append(f"Jenis Penempatan '{p}' tidak dikenal.")

    def _check_skills(self, record, result: ValidationResult) -> None:
        for label in record.skill_labels:
            if label.lower() not in self._skill_label_map:
                result.warnings.append(
                    f"Label skill '{label}' tidak ditemukan di ontologi. Skill dilewati."
                )

    def _run_reasoner_check(self, record, result: ValidationResult) -> None:
        try:
            test_world = owl.World()
            test_onto = self._load_turtle_ontology(test_world)

            with test_onto:
                talent_class = test_world.search_one(iri="*#Talent")
                if talent_class is None:
                    result.warnings.append(
                        "Class Talent tidak ditemukan. Validasi reasoner dilewati."
                    )
                    return

                temp_talent = talent_class(f"_temp_etl_{record.nip}")

                nip_prop = test_world.search_one(iri="*#nip")
                if nip_prop:
                    nip_prop[temp_talent] = [str(record.nip)]

                has_skill_prop = test_world.search_one(iri="*#hasSkill")
                if has_skill_prop:
                    for label in record.skill_labels:
                        skill_cls = test_onto.search_one(label=label)
                        if skill_cls:
                            temp_skill = skill_cls(
                                f"_temp_skill_{label.replace(' ', '_')}_{record.nip}"
                            )
                            has_skill_prop[temp_talent].append(temp_skill)

                sync_reasoner_hermit(test_world, infer_property_values=True)

                inferred: list[str] = []
                for inferred_type in temp_talent.INDIRECT_is_a:
                    if hasattr(inferred_type, "name") and inferred_type.name:
                        inferred.append(inferred_type.name)

                result.inferred_types = inferred
                logger.info(f"[NIP={record.nip}] Inferred types: {inferred}")

                inferred_names = {t.lower() for t in inferred}
                if "talent" not in inferred_names:
                    result.warnings.append(
                        "Individu tidak disimpulkan sebagai Talent oleh reasoner. "
                        f"Inferred types: {inferred}"
                    )

        except owl.base.OwlReadyInconsistentOntologyError:
            result.is_valid = False
            details = (
                f"skills={record.skill_labels}, "
                f"placement={record.jenis_penempatan}"
            )
            result.errors.append(
                f"Reasoner mendeteksi inkonsistensi aksioma untuk NIP={record.nip}. "
                f"{details}"
            )
            logger.error(
                f"OntologyValidator: inkonsistensi untuk NIP={record.nip}. {details}"
            )

        except Exception as exc:
            result.warnings.append(
                f"Validasi reasoner tidak dapat dijalankan: {exc}. "
                "Validasi struktural tetap berlaku."
            )
            logger.warning(
                f"OntologyValidator: reasoner error NIP={record.nip} - {exc}"
            )
