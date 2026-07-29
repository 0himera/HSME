# HyperGraph Research Memory Engine (HSME)

*Read this in other languages: [English](README_EN.md), [Русский](README.md)*

A unified R&D knowledge map for the mining and metallurgical industry built on the principles of **hypergraphs** and **Vector Symbolic Architectures (VSA)**.

Unlike traditional GraphRAG systems based on triplets (`Entity → Relation → Entity`), HSME represents an **experiment as a hyperedge**—a single cohesive causal event linking input parameters, equipment, processes, and outputs in a single mathematical object.


---

## Key Features

- **Mathematical VSA Core** — Binary Bipolar MAP model (Multiply, Add, Permute) implemented in `NumPy`. Encodes experiment hyperedges into high-dimensional vectors ($D = 10\,000$).
- **Knowledge Extraction from Documents** — NLP pipeline using LLM to extract entities and relations from `.docx` and `.pdf` files. Regex enrichment for numerical parameters (temperature, pH, current density).
- **Natural Language Semantic Search** — Queries like "nickel electrowinning at pH < 2" are automatically translated into VSA query vectors and matched using cosine similarity.
- **Counterfactual Analysis (Counterfactual Retrieval)** — Automatic identification of experiment pairs that differ by exactly one parameter, calculating the delta of output properties.
- **Research Gap Discovery** — Generates a Cartesian grid of parameters to find unexplored combinations, extrapolating properties using VSA topological similarity.
- **Scientific Hypothesis Synthesis** — LLM-generated scientific hypotheses for discovered gaps, backed by topologically close experiments.
- **Directed Semantic Relations** — Relations (`uses_material`, `operates_at_condition`, `produces_output`, `located_at`) encoded via cyclic permutation (Permute) to preserve directionality.
- **Interval Encoding for Numerical Parameters** — Monotonic semantic similarity for numeric values (temperatures, concentrations) by interpolating between the boundary vectors of a range.
- **Role-Based Access Control (RBAC)** — 4 roles (Administrator, Analyst, Researcher, External Partner) with access control for sensitive data and AI analytics tools.
- **Compliance Audit Logging** — Logging of user actions, including username, role, action type, and details.
- **Interactive Knowledge Map** — Visualization of the hypergraph using `Vis.js` with color-coded entity types and directed semantic relations.

---

## Project Structure

```
HSME/
├── backend/
│   ├── app.py                      # FastAPI application setup, CORS, and router registration
│   ├── main.py                     # Entry point (re-exports app)
│   ├── core/
│   │   ├── vsa.py                  # VSA operations (generate, bind, permute, bundle, similarity)
│   │   ├── models.py               # Pydantic schemas (Entity, Experiment, Relation, SearchQuery, GapQuery, AuditEntry)
│   │   └── config.py               # Configuration: VSA dimension, Yandex Cloud keys, env loader
│   ├── repository/
│   │   ├── database.py             # In-memory vector database: codebook, vector_store, search, gaps, counterfactuals
│   │   └── seeding.py              # Mock data seeding for demonstration (mining & metallurgy domain)
│   ├── routers/
│   │   ├── search.py               # Semantic search, NL query parsing, graph endpoint, stats, and RAG synthesis
│   │   ├── experiments.py          # CRUD endpoints (manual ingestion, paged listing)
│   │   ├── analytics.py            # Counterfactual retrieval, AI causal reasoning
│   │   ├── gaps.py                 # Gap analysis, property extrapolation, hypothesis generation
│   │   ├── ingestion.py            # Background corpus ingestion router
│   │   ├── audit.py                # Audit logs (Administrator only)
│   │   └── dependencies.py         # Role dependencies: UserSession, get_user_session, require_roles
│   └── services/
│       ├── document_parser.py      # Parser for .docx (python-docx) and .pdf (PyMuPDF) with metadata extraction
│       ├── nlp_extractor.py        # Entity & relation extraction using LLM + regex enrichment
│       └── ingestion.py            # Ingestion pipeline: parse → NLP → classify → VSA encode → save
├── frontend/                       # Next.js UI (static export → out/)
│   ├── app/                        # App Router entry
│   ├── components/                 # Corpus / Dialogue / Studio panels
│   └── lib/                        # API client, i18n, types
├── legacy/static-ui/               # Pre–Next.js dashboard (index.html + app.js)
├── .local/                         # Runtime: db_state.pkl, audit_logs (gitignored)
├── logs/relabel/                   # Ingestion/relabel logs (gitignored)
├── tests/
│   ├── test_vsa.py                 # Unit tests for VSA operations
│   ├── test_database.py            # Tests for database search and vector index operations
│   ├── test_api.py                 # Integration tests for FastAPI endpoints
│   ├── test_ingestion.py           # Ingestion pipeline validation
│   ├── test_nlp.py                 # NLP extractor tests
│   ├── test_parser.py              # Document parser tests
│   └── test_security.py            # Security & role-based validation tests
├── data/                           # Document corpus directory (reviews, articles, reports)
├── .env                            # Yandex Cloud credentials (ignored in VCS)
├── .env.template                   # Environment variables template
├── pyproject.toml                  # uv configuration and dependencies
└── README.md
```

---

## Installation & Setup

We recommend using [uv](https://github.com/astral-sh/uv) for fast package and python environment management.

### 1. Install Dependencies

```bash
uv sync
```

### 2. Configure Environment Variables

Copy the template file and fill in your Yandex Cloud keys (required for NLP extraction and LLM reasoning):

```bash
cp .env.template .env
```

Define the following in your `.env`:

```env
YANDEX_API_KEY=<your Yandex Cloud API key>
YANDEX_FOLDER_ID=<your Yandex Cloud Folder ID>
```

> **Note:** Without Yandex Cloud keys, the system operates in local fallback mode: natural language search uses local regex-based parsing, and AI synthesis is disabled.

### 3. Run Test Suite

Verify the entire engine stack (mathematics, database, API routing, security):

```bash
PYTHONPATH=. uv run pytest tests/ -v
```

### 4. Start the Development Server

Launch the FastAPI backend and static frontend server:

```bash
uv run uvicorn backend.app:app --reload --port 8000
```

Open your browser and navigate to: **[http://localhost:8000](http://localhost:8000)**

### 5. Ingest Document Corpus (Optional)

Place your research documents in the `data/` folder and click **«Импортировать корпус»** (Import Corpus) on the web dashboard (Administrator role required). The process runs asynchronously with a live progress indicator.

---

## How VSA Works

### 1. Entity Encoding (Role-Filler Binding)

Each unique entity is mapped to a high-dimensional vector in a codebook. We bind roles and fillers using element-wise multiplication ($\otimes$):

$$\mathbf{V}_{\text{bound}} = \mathbf{V}_{\text{Role:Material}} \otimes \mathbf{V}_{\text{Chloride Electrolyte}}$$

### 2. Relation Encoding (Permute + Bind)

Directed semantic links (e.g., `Electrowinning → uses_material → Nickel`) preserve directionality via cyclic permutation:

$$\mathbf{V}_{\text{relation}} = \text{Permute}(\mathbf{V}_{\text{source}}) \otimes \mathbf{V}_{\text{rel\_type}} \otimes \mathbf{V}_{\text{target}}$$

### 3. Experiment Hyperedge (Bundling)

All bindings (Role-Filler bindings + Relations) are combined into a single experiment vector using a majority vote (element-wise sum followed by sign extraction):

$$\mathbf{V}_{\text{experiment}} = \text{sign}\left( \sum_i \mathbf{V}_{\text{bound}_i} + \sum_j \mathbf{V}_{\text{relation}_j} \right)$$

### 4. Querying

The query is encoded similarly and matched against all experiments in the database using cosine similarity:

$$\text{Similarity} = \frac{\mathbf{V}_{\text{query}} \cdot \mathbf{V}_{\text{experiment}}}{D}$$

Matches are retrieved in milliseconds and filtered by metadata (year, geography, source type, sensitivity).

### 5. Interval Encoding for Numeric Parameters

For numeric parameters (pH, temperature, current density), we use linear interpolation between boundary vectors $\mathbf{V}_{\min}$ and $\mathbf{V}_{\max}$. This ensures monotonic semantic similarity: values like 45°C and 50°C are closer in vector space than 45°C and 900°C.

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| VSA Math Core | NumPy (Bipolar MAP VSA, $D = 10\,000$) |
| Backend | FastAPI + Uvicorn + Pydantic |
| NLP Extraction | LLM via OpenAI-compatible client |
| LLM Reasoning | LLM |
| Document Parsing | python-docx, PyMuPDF |
| Data Store | In-memory with pickle serialization |
| Frontend | Vanilla HTML5, CSS, JavaScript |
| Graph Visualization | Vis.js |
| Testing | pytest + httpx (FastAPI TestClient) |
| Dependency Manager | uv |

---

## Role-Based Access Matrix

| Role | Search | Graph | Counterfactuals | Gap Analysis | AI Reasoning | Ingestion | Audit Logs |
|------|-------|------|----------------|--------------|--------------|-----------|------------|
| Administrator | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Analyst | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ |
| Researcher | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| External Partner | ✅* | ✅* | ❌ | ❌ | ❌ | ❌ | ❌ |

\* External Partners are restricted to non-sensitive data (`is_sensitive = false`).

---

## Documentation

Public overview and pipelines: [documentation/README.md](./documentation/README.md)  
(Overview, L0–L4 retrieval, ingestion, dual-storage notes.)
