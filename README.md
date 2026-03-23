# virgo-talent-recsys

**Tugas Akhir D3 Teknik Informatika — Politeknik Negeri Bandung 2026**

> Pengembangan Sistem Rekomendasi Talenta Multi-Kriteria Berbasis Semantic Similarity pada Knowledge Graph di PT Padepokan Tujuh Sembilan

**Tim:** Geraldin Gysrawa · Ikhsan Zuhri Al Ghifary · M. Harish Al Rasyidi

---

## Arsitektur Sistem

```
Telegram Bot
     │
     ▼
  n8n (existing PT P79)
     │  webhook / HTTP node
     ▼
  FastAPI  ←──────────────────── Ollama Qwen3:8b (server PT P79)
     │                           akses via Bearer token
     ▼
  Neo4j (Docker)
  Knowledge Graph + Ontologi skill (.ttl dari Protégé)
```

---

## Stack Teknologi

| Komponen        | Teknologi             | Keterangan                         |
| --------------- | --------------------- | ---------------------------------- |
| Backend API     | FastAPI (Python 3.11) | Dikelola tim                       |
| Knowledge Graph | Neo4j 5.x + n10s      | Docker, dikelola tim               |
| Ontologi        | Protégé → `.ttl`      | Dikelola tim                       |
| LLM / NER       | Ollama — Qwen3:8b     | Remote server PT P79, Bearer token |
| Workflow        | n8n                   | Existing PT P79, tambah node baru  |
| Interface       | Telegram Bot          | Existing PT P79                    |

---

## Struktur Modul

```
Increment 1 → src/modules/ner/                  (Named Entity Recognition)
Increment 2 → src/modules/semantic_similarity/  (Sánchez Similarity + KG)
Increment 3 → src/modules/saw/                  (SAW + ROC weighting)
```

---

virgo-recsys/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .gitignore
├── .env.example ← copy ini jadi .env lalu isi nilainya
├── README.md
├── src/
│ ├── api/ ← FastAPI entrypoint (main.py nanti di sini)
│ ├── core/ ← config, database connection, settings
│ ├── modules/
│ │ ├── ner/ ← Increment 1: LLM + Qwen3:8b
│ │ ├── semantic_similarity/ ← Increment 2: Sánchez + Neo4j
│ │ └── saw/ ← Increment 3: SAW + ROC
│ └── utils/ ← helper functions bersama
├── ontology/
│ ├── ttl/ ← export dari Protégé (.ttl) → dimount ke Neo4j
│ ├── owl/ ← file OWL source
│ └── exports/ ← gitignored, hasil generate ulang
├── data/
│ ├── samples/ ← dummy data untuk testing (boleh di-commit)
│ ├── raw/ processed/ seeds/ ← gitignored (data internal P79)
├── tests/
│ ├── unit/ integration/ e2e/
├── docs/
│ ├── srs/ sdd/ uml/ ← taruh dokumen SRS, SDD, diagram di sini
└── configs/

---

## Quick Start

### 1. Clone & setup environment

```bash
git clone <repo-url>
cd virgo-talent-recsys
cp .env.example .env
# Edit .env — isi OLLAMA_BASE_URL dan OLLAMA_API_TOKEN dari PT P79
```

### 2. Jalankan FastAPI + Neo4j

```bash
docker compose up -d
```

### 3. (Opsional) Jalankan Ollama lokal untuk dev offline

```bash
docker compose --profile local-ollama up -d ollama
docker exec virgo-ollama ollama pull qwen3:8b
# Lalu set di .env: OLLAMA_BASE_URL=http://localhost:11434
```

### 4. Akses

| Service              | URL                        |
| -------------------- | -------------------------- |
| FastAPI Swagger Docs | http://localhost:8000/docs |
| Neo4j Browser        | http://localhost:7474      |

---

## Development (tanpa Docker)

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn src.api.main:app --reload
```

---

## Branching Strategy

```
main                      → stabil, sudah diuji
develop                   → integrasi antar modul
feature/inc1-ner          → Increment 1: Modul NER
feature/inc2-semantic-sim → Increment 2: Semantic Similarity
feature/inc3-saw          → Increment 3: SAW + ROC
```

---

## Menjalankan Tests

```bash
pytest tests/ -v --cov=src
```
