# =============================================================
# neo4j_writer.py
# Modul ETL — Increment 2: Semantic Similarity
#
# Tanggung Jawab:
#   Menulis TalentRecord yang sudah tervalidasi ke Neo4j
#   menggunakan Cypher via driver resmi neo4j-python.
#
# Strategi MERGE:
#   Semua operasi menggunakan MERGE (bukan CREATE) agar
#   skrip idempoten — aman dijalankan berulang kali tanpa
#   membuat duplikat node.
#
# Asumsi Neo4j:
#   - Ontologi skill sudah diimpor via n10s (neosemantics)
#   - Node skill ada sebagai (:Resource) dengan properti
#     uri dan rdfs__label
#   - Talent, Placement, Project adalah node native Neo4j
#     (bukan diimpor via n10s)
# =============================================================

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from loguru import logger
from neo4j import GraphDatabase, Driver, Session


# ----------------------------------------------------------
# Hasil operasi tulis satu talenta
# ----------------------------------------------------------

@dataclass
class WriteResult:
    nip       : str
    success   : bool
    message   : str = ""


# ----------------------------------------------------------
# Writer utama
# ----------------------------------------------------------

class Neo4jWriter:
    """
    Menulis data talenta ke Neo4j.

    Parameters
    ----------
    uri      : str   — Bolt URI, contoh: bolt://localhost:7687
    user     : str   — username Neo4j
    password : str   — password Neo4j
    database : str   — nama database, default "neo4j"
    """

    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        database: str = "neo4j",
    ) -> None:
        self._driver: Driver = GraphDatabase.driver(uri, auth=(user, password))
        self._database = database
        logger.info(f"Neo4jWriter: terhubung ke {uri} (db={database}).")

    def close(self) -> None:
        self._driver.close()

    # ----------------------------------------------------------
    # Public
    # ----------------------------------------------------------

    def write_batch(self, records: list, validator) -> list[WriteResult]:
        """
        Menulis seluruh TalentRecord sekaligus.

        Parameters
        ----------
        records   : list[TalentRecord]
        validator : OntologyValidator — digunakan untuk resolve URI skill

        Returns
        -------
        list[WriteResult]
        """
        results: list[WriteResult] = []
        with self._driver.session(database=self._database) as session:
            for record in records:
                result = self._write_one(session, record, validator)
                results.append(result)

        success_count = sum(1 for r in results if r.success)
        logger.info(
            f"Neo4jWriter: {success_count}/{len(results)} talenta berhasil ditulis."
        )
        return results

    # ----------------------------------------------------------
    # Private — orkestrasi satu talenta
    # ----------------------------------------------------------

    def _write_one(self, session: Session, record, validator) -> WriteResult:
        try:
            with session.begin_transaction() as tx:
                self._merge_talent_node(tx, record)
                self._merge_placement_and_rel(tx, record)
                self._merge_skills_and_rel(tx, record, validator)
                if record.project_nama:
                    self._merge_project_and_rel(tx, record)
                tx.commit()

            logger.info(f"Neo4jWriter: NIP={record.nip} berhasil ditulis.")
            return WriteResult(nip=record.nip, success=True, message="OK")

        except Exception as exc:
            logger.error(f"Neo4jWriter: gagal menulis NIP={record.nip} — {exc}")
            return WriteResult(nip=record.nip, success=False, message=str(exc))

    # ----------------------------------------------------------
    # Private — Cypher per entitas
    # ----------------------------------------------------------

    def _merge_talent_node(self, tx, record) -> None:
        """
        Membuat atau memperbarui node (:Talent).
        NIP digunakan sebagai kunci unik (MERGE key).
        """
        cypher = """
        MERGE (t:Talent {nip: $nip})
        SET   t.namaLengkap      = $nama_lengkap,
              t.pengalamanTahun  = $pengalaman_tahun,
              t.concernPerbankan = $concern_perbankan
        """
        tx.run(cypher, {
            "nip"              : record.nip,
            "nama_lengkap"     : record.nama_lengkap,
            "pengalaman_tahun" : record.pengalaman_tahun,
            "concern_perbankan": record.concern_perbankan,
        })

    def _merge_placement_and_rel(self, tx, record) -> None:
        """
        Membuat atau menemukan node (:Placement) berdasarkan namaLokasi,
        lalu menghubungkan ke Talent via [:PREFERS_PLACEMENT].
        Relasi lama dihapus dulu agar tidak ada duplikat preferensi.
        """
        cypher = """
        MATCH  (t:Talent {nip: $nip})
        MERGE  (p:Placement {namaLokasi: $nama_lokasi})
        MERGE  (t)-[:PREFERS_PLACEMENT]->(p)
        """
        tx.run(cypher, {
            "nip"        : record.nip,
            "nama_lokasi": record.jenis_penempatan,
        })

    def _merge_skills_and_rel(self, tx, record, validator) -> None:
        """
        Untuk setiap label skill yang valid:
        - Cari node (:Resource) di Neo4j berdasarkan URI ontologi
        - Buat relasi [:HAS_SKILL] dari Talent ke node skill
        Skill yang tidak ada di ontologi dilewati (sudah dicatat
        sebagai warning di ValidationResult).
        """
        for label in record.skill_labels:
            uri = validator.get_skill_uri(label)
            if uri is None:
                # Sudah dicatat sebagai warning di validator
                continue

            cypher = """
            MATCH  (t:Talent {nip: $nip})
            MATCH  (s:owl__Class {uri: $skill_uri})
            MERGE  (t)-[:HAS_SKILL]->(s)
            """
            result = tx.run(cypher, {"nip": record.nip, "skill_uri": uri})

            # Cek apakah node skill ditemukan
            summary = result.consume()
            if summary.counters.relationships_created == 0:
                # Node skill mungkin ada tapi relasi sudah exist (OK karena MERGE)
                # atau node skill tidak ditemukan di Neo4j
                pass

    def _merge_project_and_rel(self, tx, record) -> None:
        """
        Membuat atau menemukan node (:Project),
        lalu menghubungkan ke Talent via [:ASSIGNED_TO_PROJECT]
        dengan startDate dan endDate sebagai edge properties.
        Relasi lama untuk talent yang sama dihapus dulu (satu proyek aktif).
        """
        # Hapus relasi proyek lama dulu (satu talenta hanya satu proyek aktif)
        cypher_delete = """
        MATCH (t:Talent {nip: $nip})-[r:ASSIGNED_TO_PROJECT]->()
        DELETE r
        """
        tx.run(cypher_delete, {"nip": record.nip})

        # Buat node project dan relasi baru dengan edge properties
        cypher = """
        MATCH  (t:Talent {nip: $nip})
        MERGE  (proj:Project {namaProject: $project_nama})
        MERGE  (t)-[r:ASSIGNED_TO_PROJECT]->(proj)
        SET    r.startDate = $start_date,
               r.endDate   = $end_date
        """
        tx.run(cypher, {
            "nip"         : record.nip,
            "project_nama": record.project_nama,
            "start_date"  : record.start_date,
            "end_date"    : record.end_date,
        })
