# =============================================================
# transformer.py
# Modul ETL — Increment 2: Semantic Similarity
#
# Tanggung Jawab:
#   Menormalisasi data mentah dari Google Sheets menjadi
#   struktur yang siap ditulis ke Neo4j. Termasuk:
#   - Membersihkan whitespace dan kapitalisasi
#   - Mengurai kolom "Teknologi" (string CSV → list)
#   - Memetakan label skill ke URI ontologi
#   - Menormalisasi nilai Jenis Penempatan dan Concern Perbankan
# =============================================================

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from loguru import logger

# ----------------------------------------------------------
# Nilai valid Jenis Penempatan (sesuai ontologi Placement)
# ----------------------------------------------------------
_PLACEMENT_MAP = {
    "remote"         : "Remote",
    "bandung"        : "Bandung",
    "tanpa batasan"  : "Tanpa Batasan",
}


@dataclass
class TalentRecord:
    """
    Representasi satu baris talenta setelah transformasi.
    Struktur ini yang diteruskan ke Validator dan Neo4jWriter.
    """
    nip                : str
    nama_lengkap       : str
    pengalaman_tahun   : int
    concern_perbankan  : bool
    jenis_penempatan   : str                  # nilai: Remote | Bandung | Tanpa Batasan
    skill_labels       : list[str] = field(default_factory=list)  # label asli dari spreadsheet
    project_nama       : Optional[str] = None
    start_date         : Optional[str] = None  # string ISO: YYYY-MM-DD
    end_date           : Optional[str] = None


class Transformer:
    """
    Mengubah list[dict] mentah dari SheetsReader
    menjadi list[TalentRecord] yang sudah bersih.
    """

    def transform(self, raw_rows: list[dict]) -> list[TalentRecord]:
        """
        Memproses seluruh baris sekaligus.

        Parameters
        ----------
        raw_rows : list[dict]
            Output langsung dari SheetsReader.fetch_all().

        Returns
        -------
        list[TalentRecord]
            Baris yang gagal diproses dilewati dengan log warning.
        """
        records: list[TalentRecord] = []
        for idx, row in enumerate(raw_rows):
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

    # ----------------------------------------------------------
    # Private
    # ----------------------------------------------------------

    def _transform_row(self, row: dict) -> TalentRecord:
        nip           = str(row["nip"]).strip()
        nama_lengkap  = str(row["nama_lengkap"]).strip()

        # Pengalaman: pastikan integer, default 0 jika kosong
        try:
            pengalaman = int(str(row.get("pengalaman", "0")).strip() or "0")
        except ValueError:
            pengalaman = 0
            logger.warning(f"NIP={nip}: nilai pengalaman tidak valid, diset 0.")

        # Concern Perbankan: terima "True"/"False"/"1"/"0"/bool
        concern_raw = str(row.get("concern_perbankan", "false")).strip().lower()
        concern = concern_raw in ("true", "1", "yes", "ya")

        # Jenis Penempatan: normalisasi ke nilai baku
        penempatan_raw = str(row.get("jenis_penempatan", "")).strip().lower()
        penempatan = _PLACEMENT_MAP.get(penempatan_raw)
        if penempatan is None:
            raise ValueError(
                f"Nilai Jenis Penempatan '{penempatan_raw}' tidak dikenal. "
                f"Nilai valid: {list(_PLACEMENT_MAP.values())}"
            )

        # Teknologi: pisahkan berdasarkan koma, bersihkan whitespace
        teknologi_raw = str(row.get("teknologi", "")).strip()
        skill_labels: list[str] = [
            s.strip()
            for s in teknologi_raw.split(",")
            if s.strip()
        ]

        # Project & tanggal (opsional — satu proyek aktif)
        project_nama = str(row.get("project", "")).strip() or None
        start_date   = self._parse_date(row.get("start_date", ""), nip)
        end_date     = self._parse_date(row.get("end_date", ""), nip)

        return TalentRecord(
            nip               = nip,
            nama_lengkap      = nama_lengkap,
            pengalaman_tahun  = pengalaman,
            concern_perbankan = concern,
            jenis_penempatan  = penempatan,
            skill_labels      = skill_labels,
            project_nama      = project_nama,
            start_date        = start_date,
            end_date          = end_date,
        )

    @staticmethod
    def _parse_date(value: str, nip: str) -> Optional[str]:
        """
        Menormalisasi berbagai format tanggal menjadi string ISO YYYY-MM-DD.
        Mengembalikan None jika kosong.
        """
        value = str(value).strip()
        if not value:
            return None

        # Format umum yang mungkin dipakai di spreadsheet
        from datetime import datetime
        formats = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"]
        for fmt in formats:
            try:
                return datetime.strptime(value, fmt).date().isoformat()
            except ValueError:
                continue

        logger.warning(f"NIP={nip}: format tanggal '{value}' tidak dikenali, dilewati.")
        return None
