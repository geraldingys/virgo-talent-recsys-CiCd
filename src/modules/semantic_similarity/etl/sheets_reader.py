# =============================================================
# sheets_reader.py
# Modul ETL — Increment 2: Semantic Similarity
#
# Tanggung Jawab:
#   Membaca data talenta dari Google Sheets menggunakan
#   Service Account credentials. Mengembalikan list of dict
#   mentah (raw) sebelum transformasi.
#
# Kolom Spreadsheet yang Diharapkan:
#   No. | Nama Lengkap | NIP | Jenis Penempatan |
#   Concern Perbankan | Teknologi | Pengalaman |
#   Project | start_date | end_date
# =============================================================

import os
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials
from loguru import logger

# Scope minimal yang dibutuhkan untuk read-only Sheets
_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

# Mapping nama kolom spreadsheet → key internal yang konsisten
_COLUMN_MAP = {
    "No."                 : "no",
    "Nama Lengkap"        : "nama_lengkap",
    "NIP"                 : "nip",
    "Jenis Penempatan"    : "jenis_penempatan",
    "Concern Perbankan"   : "concern_perbankan",
    "Teknologi"           : "teknologi",
    "Pengalaman"          : "pengalaman",
    "Project"             : "project",
    "start_date"          : "start_date",
    "end_date"            : "end_date",
}


class SheetsReader:
    """
    Membaca baris data talenta dari Google Sheets.

    Parameters
    ----------
    credentials_path : str
        Path ke file JSON credentials Service Account.
    spreadsheet_id : str
        ID Google Spreadsheet (dari URL: /d/<ID>/edit).
    worksheet_name : str, optional
        Nama tab/worksheet. Default: sheet pertama.
    """

    def __init__(
        self,
        credentials_path: str,
        spreadsheet_id: str,
        worksheet_name: Optional[str] = None,
    ) -> None:
        self._credentials_path = credentials_path
        self._spreadsheet_id = spreadsheet_id
        self._worksheet_name = worksheet_name
        self._client: Optional[gspread.Client] = None

    # ----------------------------------------------------------
    # Public
    # ----------------------------------------------------------

    def fetch_all(self) -> list[dict]:
        """
        Mengambil seluruh baris data dari spreadsheet.

        Returns
        -------
        list[dict]
            Setiap elemen adalah satu baris talenta dengan
            key menggunakan nama internal (_COLUMN_MAP).
            Baris kosong (NIP kosong) dilewati secara otomatis.
        """
        ws = self._get_worksheet()
        raw_records = ws.get_all_records(
            expected_headers=list(_COLUMN_MAP.keys()),
            default_blank="",
        )

        normalized: list[dict] = []
        for idx, row in enumerate(raw_records, start=2):  # baris ke-2 = setelah header
            mapped = {_COLUMN_MAP.get(k, k): v for k, v in row.items()}

            # Lewati baris yang NIP-nya kosong
            if not str(mapped.get("nip", "")).strip():
                logger.warning(f"Baris {idx}: NIP kosong, dilewati.")
                continue

            normalized.append(mapped)

        logger.info(f"SheetsReader: {len(normalized)} baris berhasil dibaca.")
        return normalized

    # ----------------------------------------------------------
    # Private
    # ----------------------------------------------------------

    def _get_client(self) -> gspread.Client:
        if self._client is None:
            creds = Credentials.from_service_account_file(
                self._credentials_path,
                scopes=_SCOPES,
            )
            self._client = gspread.authorize(creds)
            logger.info("SheetsReader: autentikasi Service Account berhasil.")
        return self._client

    def _get_worksheet(self) -> gspread.Worksheet:
        client = self._get_client()
        spreadsheet = client.open_by_key(self._spreadsheet_id)

        if self._worksheet_name:
            ws = spreadsheet.worksheet(self._worksheet_name)
        else:
            ws = spreadsheet.sheet1

        logger.info(f"SheetsReader: membaca worksheet '{ws.title}'.")
        return ws
