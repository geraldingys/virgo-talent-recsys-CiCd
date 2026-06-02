# Panduan Demonstrasi Increment 2
## Virgo Talent Recommendation System

> **Fokus Increment 2:** ETL Pipeline (Google Sheets → Neo4j) dan
> *Ontology-based Skill Similarity* berbasis graf hierarki OWL.

### Catatan tambahan

Materi presentasi dan dokumentasi lengkap Increment 2 (PDF) tersedia di Google Drive:

- **[increment 2.pdf](https://drive.google.com/file/d/1MnnhfGMgnOxPb7rdhl0xFOS-f5MCmat6/view?usp=sharing)**

---

## 1. Tujuan Increment 2

Increment 2 membangun fondasi data dan kecerdasan semantik yang menjadi
prasyarat sistem rekomendasi multi-kriteria pada Increment 3. Terdapat
dua komponen utama yang dibangun pada increment ini.

**ETL Pipeline** bertanggung jawab untuk:
- Membaca data talenta dari Google Sheets secara otomatis melalui *trigger* N8N
- Menormalisasi dan memvalidasi setiap baris data terhadap ontologi OWL
- Menyinkronisasi data talenta ke Neo4j dalam bentuk node dan relasi graf

**Ontology-based Skill Similarity** bertanggung jawab untuk:
- Memuat hierarki ontologi skill (360 node) ke dalam memori graf
- Menghitung kemiripan semantik seluruh pasangan skill (64.620 pasangan)
  menggunakan formula Sánchez *feature-based similarity*
- Menyimpan skor similarity ke Neo4j sebagai fondasi Increment 3

**Formula Sánchez *Feature-based Similarity*:**

```
φ(a)      = himpunan subsumers dari a (termasuk dirinya sendiri)
union     = φ(a) ∪ φ(b)
sym_diff  = φ(a) Δ φ(b)
disnorm   = log₂(1 + |sym_diff| / |union|)
sim(a, b) = 1 − disnorm
```

Tidak menggunakan *Information Content* (IC) maupun LCA. Similarity
murni berbasis perbandingan himpunan subsumers antar konsep dalam
hierarki ontologi.

**Struktur data yang dihasilkan di Neo4j:**

| Node / Relasi | Keterangan |
|---|---|
| `(:Talent)` | Profil talenta dengan properti NIP, nama, pengalaman, dll. |
| `(:owl__Class)` | Node ontologi skill (diimpor via n10s) |
| `(:Placement)` | Lokasi penempatan kerja |
| `(:Project)` | Proyek aktif |
| `[:HAS_SKILL]` | Relasi talenta → skill |
| `[:PREFERS_PLACEMENT]` | Relasi talenta → placement |
| `[:ASSIGNED_TO_PROJECT]` | Relasi talenta → proyek (dengan `startDate`, `endDate`) |
| `[:rdfs__subClassOf]` | Hierarki ontologi skill (diimpor via n10s) |
| `[:SKILL_SIMILARITY]` | Skor kemiripan Sánchez antar pasangan skill (hasil precompute) |

---

## 2. Prasyarat

### 2.1 Perangkat Lunak

- Docker dan Docker Compose sudah terinstall
- Java 21 terinstall di dalam container (sudah dikonfigurasi di `Dockerfile` —
  dibutuhkan oleh HermiT *reasoner*)
- Akses internet aktif (untuk pull image Docker pertama kali)

### 2.2 File Konfigurasi

```
virgo-talent-recsys/
├── docker-compose.yml
├── .env                          ← salin dari .env.example, isi nilai aktual
├── configs/
│   └── credentials.json          ← file JSON Service Account Google
├── ontology/
│   └── ttl/
│       └── Data model v2.ttl     ← file ontologi hasil ekspor Protégé
├── plugins/
│   └── neosemantics-*.jar        ← plugin n10s untuk Neo4j
└── src/
```

### 2.3 Isi `.env` yang Wajib Diisi

```env
# Neo4j
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=changeme123

# Google Sheets
GOOGLE_CREDENTIALS_PATH=configs/credentials.json
GOOGLE_SPREADSHEET_ID=<isi dengan ID spreadsheet aktual>
GOOGLE_WORKSHEET_NAME=                    # kosongkan = sheet pertama

# Ontologi
ONTOLOGY_TTL_PATH=ontology/ttl/Data model v2.ttl
```

### 2.4 Persiapan Google Sheets

Pastikan email *Service Account* (tercantum di field `client_email` dalam
`credentials.json`) sudah ditambahkan sebagai *viewer* pada Google Sheets
melalui menu *Share*.

---

## 3. Menjalankan Docker

### 3.1 Build dan Jalankan Service

```bash
# Jalankan FastAPI + Neo4j
docker compose up -d

# Lihat status container
docker compose ps
```

Dua container yang harus berstatus `healthy`:
- `virgo-api` — FastAPI pada port `8000`
- `virgo-neo4j` — Neo4j pada port `7474` (Browser) dan `7687` (Bolt)

### 3.2 Cek Log Startup

```bash
# Log FastAPI (termasuk inisialisasi similarity service)
docker compose logs -f api

# Log Neo4j
docker compose logs -f neo4j
```

Pastikan baris berikut muncul di log `api` sebelum melanjutkan:

```
Virgo API: siap menerima request.
```

### 3.3 Akses Neo4j Browser

Buka `http://localhost:7474` di browser, login dengan:
- **Username:** `neo4j`
- **Password:** sesuai `NEO4J_PASSWORD` di `.env` (default: `changeme123`)

---

## 4. Setup Awal Neo4j (Satu Kali)

Langkah ini hanya perlu dilakukan **sekali** saat pertama kali setup,
sebelum ETL dijalankan.

### 4.1 Buat Constraint n10s

Jalankan di Neo4j Browser:

```cypher
CREATE CONSTRAINT n10s_unique_uri
FOR (r:Resource) REQUIRE r.uri IS UNIQUE;
```

### 4.2 Inisialisasi Konfigurasi n10s

```cypher
CALL n10s.graphconfig.init({
  handleVocabUris: "SHORTEN",
  handleMultival: "OVERWRITE"
});
```

### 4.3 Import Ontologi Skill dari File TTL

> **Catatan:** Nama file mengandung spasi sehingga perlu URL-encode (`%20`).

```cypher
CALL n10s.rdf.import.fetch(
  "file:///import/ontology/Data%20model%20v2.ttl",
  "Turtle"
);
```

### 4.4 Verifikasi Import Ontologi

```cypher
-- Cek jumlah node skill yang berhasil diimpor
MATCH (s:owl__Class)
WHERE s.uri CONTAINS "padepokan79"
RETURN count(s) AS total_skill_node;
-- Expected: 360
```

```cypher
-- Cek hierarki skill (sample)
MATCH (s:owl__Class)-[:rdfs__subClassOf]->(parent:owl__Class)
WHERE s.uri CONTAINS "padepokan79"
RETURN s.rdfs__label AS skill, parent.rdfs__label AS parent
LIMIT 10;
```

---

## 5. Menjalankan ETL Pipeline

### 5.1 Trigger Sinkronisasi Manual

```bash
curl -X POST http://localhost:8000/etl/sync
```

Atau melalui FastAPI Swagger UI di `http://localhost:8000/docs` →
`POST /etl/sync`.

### 5.2 Contoh Response Sukses

```json
{
  "status": "success",
  "total_rows": 250,
  "transformed_ok": 248,
  "validated_ok": 248,
  "written_ok": 248,
  "validation_errors": [],
  "write_errors": [],
  "inference_log": [...]
}
```

### 5.3 Precompute Sánchez Similarity

Jalankan **setelah** ETL sync selesai. Proses ini menghitung skor
Sánchez *feature-based similarity* untuk 64.620 pasangan skill,
lalu menyimpannya sebagai relasi `[:SKILL_SIMILARITY]` di Neo4j.

```bash
curl -X POST http://localhost:8000/etl/recompute-ic
```

Response yang diharapkan:

```json
{
  "total_nodes": 360,
  "total_pairs": 64620,
  "similarity_written": 64620,
  "errors": [],
  "duration_seconds": 22.597
}
```

> **Catatan:** Nama endpoint `recompute-ic` adalah nama lama yang
> dipertahankan untuk kompatibilitas. Perhitungan yang berjalan
> sebenarnya adalah Sánchez *feature-based similarity*, bukan
> *Information Content* (IC).

---

## 6. Verifikasi Hasil ETL di Neo4j

### 6.1 Statistik Umum Graph

```cypher
MATCH (n)
RETURN labels(n) AS tipe, count(n) AS jumlah
ORDER BY jumlah DESC;
```

Hasil yang diharapkan:

| tipe | jumlah |
|---|---|
| `["Resource", "owl__Class"]` | 360 |
| `["Talent"]` | 250 |
| `["Project"]` | 21 |
| `["Placement"]` | 4 |
| `["Resource", "owl__Ontology"]` | 1 |

### 6.2 Profil Lengkap Satu Talenta

```cypher
MATCH (t:Talent {nip: "10417010"})
OPTIONAL MATCH (t)-[:HAS_SKILL]->(s:owl__Class)
OPTIONAL MATCH (t)-[:PREFERS_PLACEMENT]->(p:Placement)
OPTIONAL MATCH (t)-[r:ASSIGNED_TO_PROJECT]->(proj:Project)
RETURN t.namaLengkap          AS nama,
       t.pengalamanTahun       AS pengalaman,
       t.pendidikan            AS pendidikan,
       t.concernPerbankan      AS concern_perbankan,
       t.statusPenugasan       AS status_penugasan,
       collect(DISTINCT s.rdfs__label) AS skills,
       collect(DISTINCT p.namaLokasi)  AS placement,
       proj.namaProject        AS project,
       r.startDate             AS start_date,
       r.endDate               AS end_date;
```

Contoh hasil:

| nama | pengalaman | pendidikan | concern_perbankan | status_penugasan | skills | placement | project | start_date | end_date |
|---|---|---|---|---|---|---|---|---|---|
| Budi Santoso | 5.0 | S1 | true | irreplacable | [PostgreSQL, Java, Spring Boot] | [Remote] | Mobile Banking App | 2023-09-10 | 2024-10-10 |

### 6.3 Visualisasi Graf Talenta

```cypher
MATCH (t:Talent {nip: "10417010"})
OPTIONAL MATCH (t)-[r1:HAS_SKILL]->(s:owl__Class)
OPTIONAL MATCH (t)-[r2:PREFERS_PLACEMENT]->(p:Placement)
OPTIONAL MATCH (t)-[r3:ASSIGNED_TO_PROJECT]->(proj:Project)
RETURN t, r1, s, r2, p, r3, proj;
```

### 6.4 Cek Talenta yang Skill-nya Tidak Terhubung ke Ontologi

```cypher
MATCH (t:Talent)
WHERE NOT (t)-[:HAS_SKILL]->()
RETURN t.nip, t.namaLengkap;
```

### 6.5 Distribusi Status Penugasan

```cypher
MATCH (t:Talent)
RETURN t.statusPenugasan AS status, count(*) AS jumlah
ORDER BY jumlah DESC;
```

---

## 7. Eksplorasi Ontologi Skill di Neo4j

### 7.1 Hierarki Lengkap Satu Skill

```cypher
MATCH path = (s:owl__Class {rdfs__label: "React.js"})
             -[:rdfs__subClassOf*]->(ancestor:owl__Class)
RETURN [node IN nodes(path) | node.rdfs__label] AS hierarki;
```

### 7.2 Koneksi A-Box (Talenta) dengan T-Box (Skill) dan Dua Level Hierarki

```cypher
MATCH (t:Talent {nip: "10417010"})
      -[:HAS_SKILL]->(skill:owl__Class)
      -[:rdfs__subClassOf]->(parent:owl__Class)
      -[:rdfs__subClassOf]->(grandparent:owl__Class)
RETURN t, skill, parent, grandparent
LIMIT 60;
```

### 7.3 Skor Similarity Dua Skill (Hasil Precompute Sánchez)

```cypher
-- Cek similarity React.js vs semua skill lain
MATCH (a:owl__Class {rdfs__label: "React.js"})
      -[r:SKILL_SIMILARITY]-
      (b:owl__Class)
WHERE b.uri CONTAINS "padepokan79"
RETURN b.rdfs__label AS skill, r.score AS similarity
ORDER BY r.score DESC
LIMIT 15;
```

### 7.4 10 Pasangan Skill Paling Mirip

```cypher
MATCH (a:owl__Class)-[r:SKILL_SIMILARITY]->(b:owl__Class)
WHERE a.uri CONTAINS "padepokan79"
  AND r.score < 1.0
RETURN a.rdfs__label AS skill_a,
       b.rdfs__label AS skill_b,
       r.score       AS similarity
ORDER BY r.score DESC
LIMIT 10;
```

### 7.5 Jumlah Relasi SKILL_SIMILARITY

```cypher
MATCH ()-[r:SKILL_SIMILARITY]->()
RETURN count(r) AS total_pasangan;
-- Expected: 64620
```

---

## 8. Endpoint API Lengkap

| Method | Endpoint | Fungsi |
|---|---|---|
| `GET` | `/` | Info sistem |
| `GET` | `/health` | Health check |
| `POST` | `/etl/sync` | Sinkronisasi Google Sheets → Neo4j |
| `POST` | `/etl/recompute-ic` | Hitung ulang Sánchez similarity + simpan ke Neo4j |
| `POST` | `/similarity/rank` | Ranking talenta berdasarkan kemiripan skill |

### Contoh `/similarity/rank`

```bash
curl -X POST http://localhost:8000/similarity/rank \
  -H "Content-Type: application/json" \
  -d '{
    "required_skills": ["React.js", "Node.js", "PostgreSQL"]
  }'
```

Mendukung operator `|` untuk kebutuhan disjungtif:

```bash
curl -X POST http://localhost:8000/similarity/rank \
  -H "Content-Type: application/json" \
  -d '{
    "required_skills": ["React.js|Vue.js", "Node.js", "PostgreSQL"]
  }'
```

Dokumentasi interaktif tersedia di `http://localhost:8000/docs`.

---

## 9. Troubleshooting

| Masalah | Kemungkinan Penyebab | Solusi |
|---|---|---|
| Container `virgo-api` tidak `healthy` | Neo4j belum siap saat startup | Tunggu 60 detik, lalu `docker compose restart api` |
| `POST /etl/sync` error `credentials` | `credentials.json` tidak ditemukan | Periksa `GOOGLE_CREDENTIALS_PATH` di `.env` |
| `POST /etl/sync` error `403 Forbidden` | Email Service Account belum diberi akses | Tambahkan email Service Account sebagai *viewer* di Google Sheets |
| Import ontologi gagal | Nama file mengandung spasi | Gunakan `Data%20model%20v2.ttl` (URL-encode) |
| `total_skill_node` kurang dari 360 | Import tidak lengkap | Hapus data lama dan ulangi import dari langkah 4.1 |
| `similarity_written: 0` | Node `owl__Class` tidak ditemukan | Pastikan import ontologi berhasil (langkah 4.4) |
| `POST /etl/recompute-ic` lambat | Normal — 64.620 pasangan dihitung dan ditulis ke Neo4j | Tunggu hingga selesai, proses batch per 500 pasangan |

---

## 10. Catatan untuk Increment 3

Setelah Increment 2 selesai, data berikut sudah tersedia di Neo4j dan
siap digunakan sebagai input algoritma SAW pada Increment 3:

| Properti / Relasi | Node | Kriteria SAW |
|---|---|---|
| `pengalamanTahun` (float) | `(:Talent)` | Kriteria Pengalaman |
| `concernPerbankan` (boolean) | `(:Talent)` | Kriteria Sektor Perbankan |
| `statusPenugasan` (string) | `(:Talent)` | Kriteria Ketersediaan |
| `[:PREFERS_PLACEMENT]` | `(:Talent) → (:Placement)` | Kriteria Lokasi |
| `[:SKILL_SIMILARITY] {score}` | `(:owl__Class) → (:owl__Class)` | Kriteria Skill |
