# =============================================================
# transformer.py (v2 — dengan SkillNormalizer)
# Modul ETL — Increment 2: Semantic Similarity
#
# Perubahan dari v1:
#   - Kolom Teknologi sekarang melewati SkillNormalizer
#     sebelum disimpan ke TalentRecord.
#   - TalentRecord menyimpan skill_labels (label kanonik)
#     dan skill_raw (label asli dari spreadsheet).
#   - Log normalisasi per baris untuk auditabilitas.
# =============================================================

from dataclasses import dataclass, field
from typing import Optional

from loguru import logger

from .skill_normalizer import SkillNormalizer

_PLACEMENT_MAP = {
    "remote"         : "Remote",
    "bandung"        : "Bandung",
    "jakarta"        : "Jakarta",
    "tanpa batasan"  : "Tanpa Batasan",
}

# Nilai pendidikan yang diakui sistem
_VALID_PENDIDIKAN = {"S3", "S2", "S1", "D4", "D3", "D2", "D1", "SMA", "SMK"}

@dataclass
class TalentRecord:
    nip                : str
    nama_lengkap       : str
    pengalaman_tahun   : int
    concern_perbankan  : bool
    jenis_penempatan   : list[str] = field(default_factory=list)
    skill_labels       : list[str] = field(default_factory=list)  # label kanonik ontologi
    skill_raw          : list[str] = field(default_factory=list)  # label asli spreadsheet
    skill_not_found    : list[str] = field(default_factory=list)  # gagal dinormalisasi
    project_nama       : Optional[str] = None
    start_date         : Optional[str] = None
    end_date           : Optional[str] = None
    pendidikan         : Optional[str] = None

class Transformer:
    """
    Mengubah list[dict] mentah dari SheetsReader
    menjadi list[TalentRecord] yang sudah bersih dan ternormalisasi.

    Parameters
    ----------
    normalizer : SkillNormalizer
        Instance normalizer yang sudah diberi ontology_labels.
        Jika None, normalisasi hanya menggunakan alias map
        (lapisan fuzzy tidak aktif).
    """

    def __init__(self, normalizer: Optional[SkillNormalizer] = None) -> None:
        self._normalizer = normalizer

    def transform(self, raw_rows: list[dict]) -> list[TalentRecord]:
        records: list[TalentRecord] = []
        for row in raw_rows:
            try:
                record = self._transform_row(row)
                records.append(record)
            except Exception as exc:
                logger.warning(
                    f"Transformer: baris NIP={row.get('nip', '?')} "
                    f"gagal ditransformasi — {exc}"
                )
        logger.info(f"Transformer: {len(records)} baris berhasil ditransformasi.")
        return records

    def _transform_row(self, row: dict) -> TalentRecord:
        nip          = str(row["nip"]).strip()
        nama_lengkap = str(row["nama_lengkap"]).strip()

        try:
            pengalaman = int(str(row.get("pengalaman", "0")).strip() or "0")
        except ValueError:
            pengalaman = 0

        concern_raw = str(row.get("concern_perbankan", "false")).strip().lower()
        concern     = concern_raw in ("true", "1", "yes", "ya")

        penempatan_raw = str(row.get("jenis_penempatan", "")).strip().lower()
        penempatan     = self._normalize_placements(penempatan_raw, nip)

        # ── Normalisasi skill ──────────────────────────────
        teknologi_raw = str(row.get("teknologi", "")).strip()
        raw_labels    = [s.strip() for s in teknologi_raw.split(",") if s.strip()]

        skill_labels    : list[str] = []
        skill_not_found : list[str] = []

        if self._normalizer and raw_labels:
            results = self._normalizer.normalize_batch(raw_labels)
            for r in results:
                if r.canonical:
                    skill_labels.append(r.canonical)
                    if r.method not in ("exact", "alias"):
                        logger.info(
                            f"[NIP={nip}] Skill '{r.original}' → "
                            f"'{r.canonical}' via {r.method}"
                        )
                else:
                    skill_not_found.append(r.original)
        else:
            # Fallback: pakai label mentah jika normalizer belum diinisialisasi
            skill_labels = raw_labels

        # Log skill yang tidak ditemukan
        if skill_not_found:
            logger.warning(
                f"[NIP={nip}] Skill tidak ditemukan di ontologi "
                f"dan dilewati: {skill_not_found}"
            )

        project_nama = str(row.get("project", "")).strip() or None
        start_date   = self._parse_date(row.get("start_date", ""), nip)
        end_date     = self._parse_date(row.get("end_date", ""), nip)

        # ── Normalisasi pendidikan ─────────────────────────
        pendidikan_raw = str(row.get("pendidikan", "")).strip().upper()
        pendidikan = pendidikan_raw if pendidikan_raw in _VALID_PENDIDIKAN else None
        if pendidikan_raw and pendidikan is None:
            logger.warning(
                f"[NIP={nip}] Nilai pendidikan '{pendidikan_raw}' "
                f"tidak dikenal, dilewati."
            )

        return TalentRecord(
            nip               = nip,
            nama_lengkap      = nama_lengkap,
            pengalaman_tahun  = pengalaman,
            concern_perbankan = concern,
            jenis_penempatan  = penempatan,
            skill_labels      = skill_labels,
            skill_raw         = raw_labels,
            skill_not_found   = skill_not_found,
            project_nama      = project_nama,
            start_date        = start_date,
            end_date          = end_date,
            pendidikan        = pendidikan,
        )

    @staticmethod
    def _parse_date(value: object, nip: str) -> Optional[str]:
        """
        Mengonversi nilai tanggal dari spreadsheet ke ISO (YYYY-MM-DD).

        Spreadsheet memakai format Indonesia hari/bulan/tahun, misalnya
        15/01/2023. Selain string, mendukung serial angka Sheets/Excel
        dan objek date/datetime jika library mengembalikannya.
        """
        from datetime import date, datetime, timedelta

        if value is None:
            return None
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()

        if isinstance(value, (int, float)) and not isinstance(value, bool):
            # Sel tanggal di Sheets sering dikirim sebagai nomor serial (hari
            # sejak 30 Des 1899, sama seperti Excel).
            serial = int(value)
            if 20000 <= serial <= 120000:
                base = datetime(1899, 12, 30)
                try:
                    return (base + timedelta(days=serial)).date().isoformat()
                except (OverflowError, ValueError):
                    pass

        text = str(value).strip()
        if not text:
            return None

        # "15/01/2023 00:00:00" atau tanggalISO + waktu
        if " " in text:
            head = text.split()[0]
            if any(sep in head for sep in ("/", "-", ".")):
                text = head

        # Utamakan DD/MM/YYYY dari spreadsheet (contoh 15/01/2023)
        formats = (
            "%Y-%m-%d",
            "%d/%m/%Y",
            "%d-%m-%Y",
            "%d.%m.%Y",
            "%m/%d/%Y",
        )
        for fmt in formats:
            try:
                return datetime.strptime(text, fmt).date().isoformat()
            except ValueError:
                continue

        logger.warning(f"NIP={nip}: format tanggal '{value}' tidak dikenali.")
        return None

    @staticmethod
    def _normalize_placements(raw_value: str, nip: str) -> list[str]:
        """
        Menormalkan jenis penempatan.

        Jika spreadsheet berisi lebih dari satu nilai (mis. "bandung, remote"),
        simpan semua nilai yang dikenal agar talent bisa punya lebih dari satu
        relasi placement. Hanya nilai Bandung, Remote, Tanpa Batasan, dan
        Jakarta yang diterima.
        """
        if not raw_value:
            raise ValueError("Jenis Penempatan kosong.")

        candidates = [
            part.strip()
            for part in raw_value.replace("/", ",").replace("|", ",").split(",")
            if part.strip()
        ]
        if not candidates:
            raise ValueError("Jenis Penempatan kosong.")

        placements: list[str] = []
        for candidate in candidates:
            mapped = _PLACEMENT_MAP.get(candidate)
            if mapped is not None:
                if mapped not in placements:
                    placements.append(mapped)

        if placements:
            if len(placements) > 1:
                logger.warning(
                    f"NIP={nip}: Jenis Penempatan gabungan '{raw_value}' "
                    f"ditemukan, memakai {placements}."
                )
            return placements

        raise ValueError(f"Jenis Penempatan '{raw_value}' tidak dikenal.")
