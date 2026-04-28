# =============================================================
# pipeline.py
# Modul ETL — Increment 2: Semantic Similarity
#
# Tanggung Jawab:
#   Mengorkestrasi seluruh langkah ETL dalam satu fungsi:
#   Sheets → Transform → Validate → Neo4j
#
# Fungsi run_etl_pipeline() adalah entry point tunggal yang
# dipanggil oleh endpoint FastAPI maupun oleh N8N via HTTP.
# =============================================================

from __future__ import annotations

from dataclasses import dataclass, field

from loguru import logger

from .sheets_reader import SheetsReader
from .transformer import Transformer
from .validator import OntologyValidator, ValidationResult
from .neo4j_writer import Neo4jWriter, WriteResult


# ----------------------------------------------------------
# Konfigurasi pipeline (diisi dari .env via Settings)
# ----------------------------------------------------------

@dataclass
class ETLConfig:
    # Google Sheets
    credentials_path : str
    spreadsheet_id   : str
    worksheet_name   : str | None = None

    # Ontologi
    ttl_path         : str = "ontology/ttl/Data_model_v2.ttl"

    # Neo4j
    neo4j_uri        : str = "bolt://localhost:7687"
    neo4j_user       : str = "neo4j"
    neo4j_password   : str = "changeme123"
    neo4j_database   : str = "neo4j"


# ----------------------------------------------------------
# Ringkasan hasil pipeline
# ----------------------------------------------------------

@dataclass
class PipelineReport:
    total_rows        : int = 0
    transformed_ok    : int = 0
    validated_ok      : int = 0
    written_ok        : int = 0
    validation_errors : list[dict] = field(default_factory=list)
    write_errors      : list[dict] = field(default_factory=list)


# ----------------------------------------------------------
# Entry point
# ----------------------------------------------------------

def run_etl_pipeline(config: ETLConfig) -> PipelineReport:
    """
    Menjalankan pipeline ETL secara lengkap.

    Alur:
    1. SheetsReader  — ambil data mentah dari Google Sheets
    2. Transformer   — normalisasi dan parsing setiap baris
    3. OntologyValidator — validasi struktural + reasoner HermiT
    4. Neo4jWriter   — tulis baris yang lolos validasi ke Neo4j

    Parameters
    ----------
    config : ETLConfig
        Konfigurasi koneksi dan path file.

    Returns
    -------
    PipelineReport
        Ringkasan statistik dan daftar error per NIP.
    """
    report = PipelineReport()
    logger.info("=" * 60)
    logger.info("ETL Pipeline: mulai.")
    logger.info("=" * 60)

    # ── Langkah 1: Baca Google Sheets ───────────────────────
    logger.info("Langkah 1/4 — Membaca data dari Google Sheets ...")
    reader = SheetsReader(
        credentials_path = config.credentials_path,
        spreadsheet_id   = config.spreadsheet_id,
        worksheet_name   = config.worksheet_name,
    )
    raw_rows = reader.fetch_all()
    report.total_rows = len(raw_rows)
    logger.info(f"Langkah 1 selesai: {report.total_rows} baris dibaca.")

    if not raw_rows:
        logger.warning("Tidak ada data di spreadsheet. Pipeline dihentikan.")
        return report

    # ── Langkah 2: Transformasi ──────────────────────────────
    logger.info("Langkah 2/4 — Normalisasi dan transformasi baris ...")
    transformer = Transformer()
    records = transformer.transform(raw_rows)
    report.transformed_ok = len(records)
    logger.info(f"Langkah 2 selesai: {report.transformed_ok} baris ditransformasi.")

    if not records:
        logger.warning("Tidak ada baris yang berhasil ditransformasi. Pipeline dihentikan.")
        return report

    # ── Langkah 3: Validasi Ontologi ────────────────────────
    logger.info("Langkah 3/4 — Validasi terhadap ontologi (Owlready2 + HermiT) ...")
    validator = OntologyValidator(ttl_path=config.ttl_path)

    valid_records = []
    for record in records:
        result: ValidationResult = validator.validate(record)

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

    report.validated_ok = len(valid_records)
    logger.info(
        f"Langkah 3 selesai: {report.validated_ok}/{report.transformed_ok} "
        f"baris lolos validasi."
    )

    if not valid_records:
        logger.warning("Tidak ada baris yang lolos validasi. Pipeline dihentikan.")
        return report

    # ── Langkah 4: Tulis ke Neo4j ────────────────────────────
    logger.info("Langkah 4/4 — Menulis data ke Neo4j ...")
    writer = Neo4jWriter(
        uri      = config.neo4j_uri,
        user     = config.neo4j_user,
        password = config.neo4j_password,
        database = config.neo4j_database,
    )

    try:
        write_results: list[WriteResult] = writer.write_batch(valid_records, validator)
    finally:
        writer.close()

    for wr in write_results:
        if wr.success:
            report.written_ok += 1
        else:
            report.write_errors.append({"nip": wr.nip, "message": wr.message})

    logger.info(
        f"Langkah 4 selesai: {report.written_ok}/{report.validated_ok} "
        f"talenta berhasil ditulis ke Neo4j."
    )

    # ── Ringkasan ────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("ETL Pipeline: selesai.")
    logger.info(f"  Total baris dibaca   : {report.total_rows}")
    logger.info(f"  Berhasil ditransform : {report.transformed_ok}")
    logger.info(f"  Lolos validasi       : {report.validated_ok}")
    logger.info(f"  Ditulis ke Neo4j     : {report.written_ok}")
    logger.info(f"  Error validasi       : {len(report.validation_errors)}")
    logger.info(f"  Error tulis          : {len(report.write_errors)}")
    logger.info("=" * 60)

    return report
