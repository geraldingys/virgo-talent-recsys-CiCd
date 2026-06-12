# =============================================================
# pipeline.py
# Modul ETL — Increment 2: Semantic Similarity
#
# Tanggung Jawab:
#   Mengorkestrasi seluruh langkah ETL dalam satu class:
#   Sheets → Transform → Validate → Neo4j
#
# Perubahan dari versi sebelumnya:
#   - run_etl_pipeline() diubah menjadi class ETLPipeline
#     dengan method run() (OOP refactor).
#   - skill_uri_map dibangun di pipeline dan diteruskan ke
#     Neo4jWriter — validator tidak lagi diteruskan ke writer
#     (Single Responsibility Principle).
#   - ETLPipeline menyimpan komponen internal sebagai atribut
#     sehingga memudahkan testing dan dependency injection.
# =============================================================

from __future__ import annotations

from dataclasses import dataclass, field

from loguru import logger

from .sheets_reader import SheetsReader
from .skill_normalizer import SkillNormalizer
from .transformer import Transformer
from .validator import OntologyValidator, ValidationResult
from .neo4j_writer import Neo4jWriter, WriteResult


# ----------------------------------------------------------
# Konfigurasi pipeline
# ----------------------------------------------------------

@dataclass
class ETLConfig:
    # Google Sheets
    credentials_path: str
    spreadsheet_id  : str
    worksheet_name  : str | None = None

    # Ontologi
    ttl_path        : str = "ontology/ttl/Data_model_v2.ttl"

    # Neo4j
    neo4j_uri       : str = "neo4j+s://localhost"
    neo4j_user      : str = "neo4j"
    neo4j_password  : str = "changeme123"
    neo4j_database  : str = "neo4j"


# ----------------------------------------------------------
# Ringkasan hasil pipeline
# ----------------------------------------------------------

@dataclass
class PipelineReport:
    total_rows       : int = 0
    transformed_ok   : int = 0
    validated_ok     : int = 0
    written_ok       : int = 0
    validation_errors: list[dict] = field(default_factory=list)
    write_errors     : list[dict] = field(default_factory=list)
    inference_log    : list[dict] = field(default_factory=list)


# ----------------------------------------------------------
# Pipeline utama
# ----------------------------------------------------------

class ETLPipeline:
    """
    Mengorkestrasi seluruh langkah ETL dari Google Sheets ke Neo4j.

    Alur:
    1. SheetsReader       — baca data mentah dari Google Sheets
    2. OntologyValidator  — muat ontologi, bangun skill_uri_map
    3. SkillNormalizer    — normalisasi label skill (alias + fuzzy)
    4. Transformer        — bersihkan dan parsing setiap baris
    5. Validasi           — cek struktural + reasoner HermiT
    6. Neo4jWriter        — tulis baris yang lolos ke Neo4j

    Parameters
    ----------
    config : ETLConfig
        Konfigurasi koneksi dan path file.
    """

    def __init__(self, config: ETLConfig) -> None:
        self._config = config

        # Komponen diinisialisasi saat run() dipanggil
        self._reader    : SheetsReader | None       = None
        self._validator : OntologyValidator | None  = None
        self._normalizer: SkillNormalizer | None    = None
        self._transformer: Transformer | None       = None
        self._writer    : Neo4jWriter | None        = None

    # ----------------------------------------------------------
    # Public
    # ----------------------------------------------------------

    def run(self) -> PipelineReport:
        """
        Menjalankan pipeline ETL secara lengkap.

        Returns
        -------
        PipelineReport
            Ringkasan statistik dan daftar error per NIP.
        """
        report = PipelineReport()
        logger.info("=" * 60)
        logger.info("ETLPipeline: mulai.")
        logger.info("=" * 60)

        # ── Langkah 1: Baca Google Sheets ───────────────────
        raw_rows = self._step_read()
        report.total_rows = len(raw_rows)
        if not raw_rows:
            logger.warning("Tidak ada data di spreadsheet. Pipeline dihentikan.")
            return report

        # ── Langkah 2: Inisialisasi Validator & Normalizer ──
        skill_uri_map = self._step_init_validator_and_normalizer()

        # ── Langkah 3: Transformasi ──────────────────────────
        records = self._step_transform(raw_rows)
        report.transformed_ok = len(records)
        if not records:
            logger.warning("Tidak ada baris yang berhasil ditransformasi.")
            return report

        # ── Langkah 4: Validasi ──────────────────────────────
        valid_records = self._step_validate(records, report)
        report.validated_ok = len(valid_records)
        if not valid_records:
            logger.warning("Tidak ada baris yang lolos validasi.")
            return report

        # ── Langkah 5: Tulis ke Neo4j ────────────────────────
        self._step_write(valid_records, skill_uri_map, report)

        self._log_summary(report)
        return report

    # ----------------------------------------------------------
    # Private — langkah-langkah pipeline
    # ----------------------------------------------------------

    def _step_read(self) -> list[dict]:
        logger.info("Langkah 1/5 — Membaca data dari Google Sheets ...")
        self._reader = SheetsReader(
            credentials_path = self._config.credentials_path,
            spreadsheet_id   = self._config.spreadsheet_id,
            worksheet_name   = self._config.worksheet_name,
        )
        raw_rows = self._reader.fetch_all()
        logger.info(f"Langkah 1 selesai: {len(raw_rows)} baris dibaca.")
        return raw_rows

    def _step_init_validator_and_normalizer(self) -> dict[str, str]:
        """
        Memuat ontologi, membangun skill_uri_map, dan menginisialisasi
        SkillNormalizer dengan label kanonik dari ontologi.

        Returns
        -------
        dict[str, str]
            skill_uri_map: label_kanonik → URI ontologi.
            Diteruskan ke Neo4jWriter — validator tidak perlu
            ikut sampai ke writer.
        """
        logger.info("Langkah 2/5 — Inisialisasi Validator & SkillNormalizer ...")

        self._validator = OntologyValidator(ttl_path=self._config.ttl_path)

        # Bangun skill_uri_map dari ontologi yang sudah dimuat
        skill_uri_map: dict[str, str] = {}
        canonical_labels: list[str]   = []

        for cls in self._validator._onto.classes():
            labels = cls.label if hasattr(cls, "label") and cls.label else []
            label  = next(iter(labels), cls.name)
            uri    = cls.iri

            if label and uri:
                skill_uri_map[label]      = uri
                canonical_labels.append(label)

        self._normalizer = SkillNormalizer(
            ontology_labels = canonical_labels,
            fuzzy_threshold = 85,
        )

        logger.info(
            f"Langkah 2 selesai: {len(canonical_labels)} skill di ontologi, "
            f"Normalizer siap dengan fuzzy matching."
        )
        return skill_uri_map

    def _step_transform(self, raw_rows: list[dict]) -> list:
        logger.info("Langkah 3/5 — Normalisasi dan transformasi baris ...")
        self._transformer = Transformer(normalizer=self._normalizer)
        records = self._transformer.transform(raw_rows)
        logger.info(f"Langkah 3 selesai: {len(records)} baris ditransformasi.")
        return records

    def _step_validate(
        self,
        records: list,
        report : PipelineReport,
    ) -> list:
        logger.info("Langkah 4/5 — Validasi ontologi (Owlready2 + HermiT) ...")

        valid_records: list = []
        for record in records:
            result: ValidationResult = self._validator.validate(record)

            # Catat hasil inferensi untuk laporan
            if getattr(result, "inferred_types", None):
                report.inference_log.append({
                    "nip"           : record.nip,
                    "nama_lengkap"  : record.nama_lengkap,
                    "inferred_types": result.inferred_types,
                })

            if result.warnings:
                for w in result.warnings:
                    logger.warning(f"[NIP={record.nip}] WARNING: {w}")

            if result.is_valid:
                valid_records.append(record)
            else:
                for e in result.errors:
                    logger.error(f"[NIP={record.nip}] DITOLAK: {e}")
                report.validation_errors.append({
                    "nip"   : record.nip,
                    "errors": result.errors,
                })

        logger.info(
            f"Langkah 4 selesai: {len(valid_records)}/{len(records)} "
            f"baris lolos validasi."
        )
        return valid_records

    def _step_write(
        self,
        valid_records : list,
        skill_uri_map : dict[str, str],
        report        : PipelineReport,
    ) -> None:
        logger.info("Langkah 5/5 — Menulis data ke Neo4j ...")
        self._writer = Neo4jWriter(
            uri      = self._config.neo4j_uri,
            user     = self._config.neo4j_user,
            password = self._config.neo4j_password,
            database = self._config.neo4j_database,
        )
        try:
            write_results: list[WriteResult] = self._writer.write_batch(
                records       = valid_records,
                skill_uri_map = skill_uri_map,
            )
        finally:
            self._writer.close()

        for wr in write_results:
            if wr.success:
                report.written_ok += 1
            else:
                report.write_errors.append({
                    "nip"    : wr.nip,
                    "message": wr.message,
                })

        logger.info(
            f"Langkah 5 selesai: {report.written_ok}/{len(valid_records)} "
            f"talenta berhasil ditulis ke Neo4j."
        )

    @staticmethod
    def _log_summary(report: PipelineReport) -> None:
        logger.info("=" * 60)
        logger.info("ETLPipeline: selesai.")
        logger.info(f"  Total baris dibaca   : {report.total_rows}")
        logger.info(f"  Berhasil ditransform : {report.transformed_ok}")
        logger.info(f"  Lolos validasi       : {report.validated_ok}")
        logger.info(f"  Ditulis ke Neo4j     : {report.written_ok}")
        logger.info(f"  Error validasi       : {len(report.validation_errors)}")
        logger.info(f"  Error tulis          : {len(report.write_errors)}")
        logger.info("=" * 60)
