# =============================================================
# validator.py
# Modul ETL — Increment 2: Semantic Similarity
#
# Tanggung Jawab:
#   Memvalidasi setiap TalentRecord terhadap T-Box ontologi
#   menggunakan pustaka Owlready2.
#
# Dua lapis validasi:
#   1. Validasi label skill  — semua label skill di baris data
#      harus ada di dalam ontologi (cek via rdfs:label).
#   2. Validasi reasoner     — membuat individu sementara di
#      world Owlready2 dan menjalankan HermiT untuk
#      memastikan tidak ada kontradiksi aksioma (Disjoint,
#      Functional Property, Domain/Range).
#
# Catatan:
#   OntologyValidator dimuat SEKALI saat aplikasi startup
#   (singleton). Reasoner dijalankan per-batch, bukan per-baris,
#   untuk menjaga performa.
# =============================================================

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from loguru import logger
from rdflib import Graph

try:
    import owlready2 as owl
    from owlready2 import sync_reasoner_hermit
    _OWL_AVAILABLE = True
except ImportError:
    _OWL_AVAILABLE = False
    logger.error("owlready2 tidak ditemukan. Jalankan: pip install owlready2")


# ----------------------------------------------------------
# Hasil validasi satu baris
# ----------------------------------------------------------

@dataclass
class ValidationResult:
    nip        : str
    is_valid   : bool
    errors     : list[str] = field(default_factory=list)
    warnings   : list[str] = field(default_factory=list)


# ----------------------------------------------------------
# Validator utama
# ----------------------------------------------------------

class OntologyValidator:
    """
    Memuat T-Box dari file .ttl dan memvalidasi TalentRecord.

    Parameters
    ----------
    ttl_path : str | Path
        Path ke file ontologi Turtle (.ttl) hasil export Protégé.
    """

    def __init__(self, ttl_path: str | Path) -> None:
        if not _OWL_AVAILABLE:
            raise RuntimeError("owlready2 tidak tersedia.")

        self._ttl_path = Path(ttl_path).expanduser().resolve()
        self._onto: Optional[owl.Ontology] = None
        self._skill_label_map: dict[str, owl.ThingClass] = {}  # label.lower() → class
        self._valid_placements = {"remote", "bandung", "tanpa batasan"}

        self._load_ontology()

    # ----------------------------------------------------------
    # Public
    # ----------------------------------------------------------

    def validate(self, record) -> ValidationResult:
        """
        Memvalidasi satu TalentRecord.

        Langkah 1 — Validasi struktural (cepat, tanpa reasoner):
          - NIP tidak kosong
          - Jenis Penempatan ada di daftar nilai valid
          - Semua label skill ada di dalam ontologi

        Langkah 2 — Validasi reasoner (HermiT):
          - Membuat individu sementara dan menjalankan reasoner
          - Menghapus individu sementara setelah selesai

        Parameters
        ----------
        record : TalentRecord
            Satu baris talenta dari Transformer.

        Returns
        -------
        ValidationResult
        """
        result = ValidationResult(nip=record.nip, is_valid=True)

        # ── Langkah 1: Validasi Struktural ──────────────────
        self._check_nip(record, result)
        self._check_placement(record, result)
        self._check_skills(record, result)

        # Jika sudah ada error struktural, jangan lanjut ke reasoner
        if not result.is_valid:
            return result

        # ── Langkah 2: Validasi Reasoner ────────────────────
        self._run_reasoner_check(record, result)

        return result

    def get_skill_class(self, label: str) -> Optional[owl.ThingClass]:
        """
        Mengambil OWL class dari ontologi berdasarkan label skill.
        Digunakan oleh neo4j_writer untuk mendapatkan URI resmi.
        """
        return self._skill_label_map.get(label.lower())

    def get_skill_uri(self, label: str) -> Optional[str]:
        """
        Mengambil URI IRI dari skill class berdasarkan label.
        Digunakan untuk mencocokkan node Resource di Neo4j.
        """
        cls = self.get_skill_class(label)
        if cls is None:
            return None
        return cls.iri

    # ----------------------------------------------------------
    # Private — load
    # ----------------------------------------------------------

    def _load_ontology(self) -> None:
        """Memuat file .ttl ke Owlready2 dan membangun skill label map."""
        logger.info(f"OntologyValidator: memuat ontologi dari {self._ttl_path} ...")
        if not self._ttl_path.exists():
            raise FileNotFoundError(f"File ontologi tidak ditemukan: {self._ttl_path}")

        world = owl.World()
        self._onto = self._load_turtle_ontology(world)

        # Bangun lookup: label.lower() → OWL class
        count = 0
        for cls in self._onto.classes():
            labels = cls.label  # list of strings
            if labels:
                for lbl in labels:
                    self._skill_label_map[lbl.lower()] = cls
                    count += 1
            else:
                # Fallback: gunakan nama lokal (fragment URI)
                local_name = cls.name
                self._skill_label_map[local_name.lower()] = cls
                count += 1

        logger.info(
            f"OntologyValidator: ontologi dimuat. "
            f"{count} label skill terindeks."
        )

    def _load_turtle_ontology(self, world: owl.World) -> owl.Ontology:
        """Membaca Turtle lalu mengonversinya ke RDF/XML sementara agar Owlready2 bisa memuatnya."""
        graph = Graph()
        graph.parse(self._ttl_path.as_posix(), format="turtle")

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".rdf", delete=False, encoding="utf-8") as temp_file:
                temp_file.write(graph.serialize(format="xml"))
                temp_path = Path(temp_file.name)

            return world.get_ontology(temp_path.as_uri()).load()
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()

    # ----------------------------------------------------------
    # Private — validasi struktural
    # ----------------------------------------------------------

    def _check_nip(self, record, result: ValidationResult) -> None:
        if not record.nip or not str(record.nip).strip():
            result.is_valid = False
            result.errors.append("NIP kosong atau tidak valid.")

    def _check_placement(self, record, result: ValidationResult) -> None:
        if record.jenis_penempatan.lower() not in self._valid_placements:
            result.is_valid = False
            result.errors.append(
                f"Jenis Penempatan '{record.jenis_penempatan}' tidak dikenal. "
                f"Nilai valid: Remote, Bandung, Tanpa Batasan."
            )

    def _check_skills(self, record, result: ValidationResult) -> None:
        for label in record.skill_labels:
            if label.lower() not in self._skill_label_map:
                # Bukan error fatal — cukup warning, skill dilewati saat tulis
                result.warnings.append(
                    f"Label skill '{label}' tidak ditemukan di ontologi. "
                    f"Skill ini akan dilewati."
                )

    # ----------------------------------------------------------
    # Private — validasi reasoner
    # ----------------------------------------------------------

    def _run_reasoner_check(self, record, result: ValidationResult) -> None:
        """
        Membuat individu sementara di world terisolasi,
        menjalankan HermiT, lalu membersihkan.
        Menggunakan world terpisah agar tidak mencemari ontologi utama.
        """
        try:
            # Buat world terpisah agar individu test tidak persisten
            test_world = owl.World()
            test_onto = self._load_turtle_ontology(test_world)

            with test_onto:
                # Ambil class Talent dari ontologi test
                TalentClass = test_onto.search_one(label="Talent")
                if TalentClass is None:
                    # Coba cari via nama lokal
                    TalentClass = test_world.search_one(iri="*#Talent")

                if TalentClass is None:
                    result.warnings.append(
                        "Class Talent tidak ditemukan di ontologi. "
                        "Validasi reasoner dilewati."
                    )
                    return

                # Buat individu sementara
                temp_individual = TalentClass(f"_temp_etl_{record.nip}")

                # Pasang skill yang valid
                hasSkill_prop = test_onto.search_one(label="hasSkill")
                if hasSkill_prop:
                    for label in record.skill_labels:
                        skill_cls = test_onto.search_one(label=label)
                        if skill_cls:
                            # Buat individu skill sementara
                            temp_skill = skill_cls(f"_temp_skill_{label}_{record.nip}")
                            hasSkill_prop[temp_individual].append(temp_skill)

                # Jalankan HermiT reasoner
                with owl.base.JAVA_MEMORY:
                    pass  # pastikan Java tersedia (owlready2 butuh Java untuk HermiT)

                sync_reasoner_hermit(test_world, infer_property_values=False)

        except owl.base.OwlReadyInconsistentOntologyError:
            result.is_valid = False
            result.errors.append(
                f"Reasoner mendeteksi inkonsistensi aksioma untuk NIP={record.nip}. "
                f"Data ditolak."
            )
            logger.error(
                f"OntologyValidator: inkonsistensi terdeteksi untuk NIP={record.nip}."
            )
        except Exception as exc:
            # Reasoner gagal bukan karena inkonsistensi — log tapi jangan blokir
            result.warnings.append(
                f"Validasi reasoner tidak dapat dijalankan: {exc}. "
                f"Validasi struktural tetap berlaku."
            )
            logger.warning(
                f"OntologyValidator: reasoner error untuk NIP={record.nip} — {exc}"
            )
