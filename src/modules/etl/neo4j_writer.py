# =============================================================
# neo4j_writer.py
# Modul ETL — Increment 2: Semantic Similarity
#
# Tanggung Jawab:
#   Menulis TalentRecord yang sudah tervalidasi ke Neo4j
#   menggunakan Cypher via driver resmi neo4j-python.
#
# Perubahan dari versi sebelumnya:
#   - write_batch() tidak lagi menerima OntologyValidator sebagai
#     parameter. URI skill sudah diselesaikan di pipeline sebelum
#     data masuk ke writer (Single Responsibility Principle).
#   - write_batch() menerima skill_uri_map: dict[label, uri]
#     yang disiapkan oleh ETLPipeline.
#
# Strategi MERGE:
#   Semua operasi menggunakan MERGE (bukan CREATE) agar
#   skrip idempoten — aman dijalankan berulang kali tanpa
#   membuat duplikat node.
# =============================================================

from __future__ import annotations

from dataclasses import dataclass

from loguru import logger
from neo4j import Driver, GraphDatabase, Session


@dataclass
class WriteResult:
    nip    : str
    success: bool
    message: str = ""


class Neo4jWriter:
    """
    Menulis data talenta ke Neo4j.

    Parameters
    ----------
    uri      : str  — Bolt URI, contoh: bolt://localhost:7687
    user     : str  — username Neo4j
    password : str  — password Neo4j
    database : str  — nama database, default "neo4j"
    """

    def __init__(
        self,
        uri     : str,
        user    : str,
        password: str,
        database: str = "neo4j",
    ) -> None:
        self._driver  : Driver = GraphDatabase.driver(uri, auth=(user, password))
        self._database: str    = database
        logger.info(f"Neo4jWriter: terhubung ke {uri} (db={database}).")

    def close(self) -> None:
        self._driver.close()

    # ----------------------------------------------------------
    # Public
    # ----------------------------------------------------------

    def write_batch(
        self,
        records      : list,
        skill_uri_map: dict[str, str],
    ) -> list[WriteResult]:
        """
        Menulis seluruh TalentRecord sekaligus.

        Parameters
        ----------
        records       : list[TalentRecord]
        skill_uri_map : dict[label_kanonik, uri_ontologi]
            Dibangun oleh ETLPipeline dari OntologyValidator
            sebelum memanggil writer. Writer tidak perlu tahu
            soal ontologi — cukup pakai URI yang sudah disiapkan.

        Returns
        -------
        list[WriteResult]
        """
        results: list[WriteResult] = []
        with self._driver.session(database=self._database) as session:
            for record in records:
                result = self._write_one(session, record, skill_uri_map)
                results.append(result)

        success_count = sum(1 for r in results if r.success)
        logger.info(
            f"Neo4jWriter: {success_count}/{len(results)} talenta berhasil ditulis."
        )
        return results

    # ----------------------------------------------------------
    # Private — orkestrasi satu talenta
    # ----------------------------------------------------------

    def _write_one(
        self,
        session      : Session,
        record,
        skill_uri_map: dict[str, str],
    ) -> WriteResult:
        try:
            with session.begin_transaction() as tx:
                self._merge_talent_node(tx, record)
                self._merge_placement_and_rel(tx, record)
                self._merge_skills_and_rel(tx, record, skill_uri_map)
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
        cypher = """
        MERGE (t:Talent {nip: $nip})
        SET   t.namaLengkap      = $nama_lengkap,
              t.pengalamanTahun  = $pengalaman_tahun,
              t.concernPerbankan = $concern_perbankan,
              t.pendidikan       = $pendidikan,
              t.statusPenugasan  = $status_penugasan
        """
        tx.run(cypher, {
            "nip"              : record.nip,
            "nama_lengkap"     : record.nama_lengkap,
            "pengalaman_tahun" : record.pengalaman_tahun,
            "concern_perbankan": record.concern_perbankan,
            "pendidikan"       : record.pendidikan,
            "status_penugasan" : record.status_penugasan,
        })

    def _merge_placement_and_rel(self, tx, record) -> None:
        """
        Satu talenta bisa punya lebih dari satu relasi placement
        sesuai keputusan desain (jenis_penempatan adalah list).
        """
        cypher = """
        MATCH  (t:Talent {nip: $nip})
        MERGE  (p:Placement {namaLokasi: $nama_lokasi})
        MERGE  (t)-[:PREFERS_PLACEMENT]->(p)
        """
        placements = record.jenis_penempatan
        if isinstance(placements, str):
            placements = [placements]

        for nama_lokasi in placements:
            if not str(nama_lokasi).strip():
                continue
            tx.run(cypher, {
                "nip"        : record.nip,
                "nama_lokasi": nama_lokasi,
            })

    def _merge_skills_and_rel(
        self,
        tx           ,
        record       ,
        skill_uri_map: dict[str, str],
    ) -> None:
        """
        URI skill diambil dari skill_uri_map yang sudah disiapkan
        pipeline — writer tidak bergantung pada OntologyValidator.
        """
        cypher = """
        MATCH (t:Talent {nip: $nip})
        MATCH (s:owl__Class {uri: $skill_uri})
        MERGE (t)-[:HAS_SKILL]->(s)
        """
        for label in record.skill_labels:
            uri = skill_uri_map.get(label)
            if uri is None:
                continue
            tx.run(cypher, {"nip": record.nip, "skill_uri": uri})

    def _merge_project_and_rel(self, tx, record) -> None:
        """
        Hapus relasi proyek lama sebelum membuat yang baru
        (satu talenta hanya boleh punya satu proyek aktif).
        startDate dan endDate disimpan sebagai edge properties.
        """
        cypher_delete = """
        MATCH (t:Talent {nip: $nip})-[r:ASSIGNED_TO_PROJECT]->()
        DELETE r
        """
        tx.run(cypher_delete, {"nip": record.nip})

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
