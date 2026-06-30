# HyperGraph Research Memory Engine (HSME)

A lightweight, high-performance scientific knowledge engine designed for the analysis of materials, alloy processing regimes, and experimental properties. 

Unlike standard search systems or triple-based GraphRAG (`Entity -> Relation -> Entity`), HSME represents **experiments as hyperedges**. An experiment is preserved as a cohesive causal unit of information, keeping inputs, processes, and outputs linked in a single mathematical structure.

---

## Key Features

- **Custom VSA Core (`NumPy`)**: Built from scratch using a Binary Bipolar MAP (Multiply, Add, Permute) Vector Symbolic Architecture. Encodes structured hyperedge data into high-dimensional vectors ($D = 10,000$).
- **Counterfactual Retrieval**: Automatically detects pairs of experiments where exactly one input parameter was changed (e.g. annealing temperature modified from $900^\circ\text{C}$ to $950^\circ\text{C}$, keeping alloy and cooling rate constant) and calculates the causal impact on properties (e.g. Yield Strength delta).
- **Research Gap Discovery**: Automatically maps the Cartesian grid of research coordinates (Alloy $\times$ Temperature $\times$ Cooling) to find unexplored combinations.
- **Topological Manifold Extrapolation**: Hypothesizes and projects output properties for research gaps by measuring topological trends across similar experiments in the VSA space.
- **Academic monospaced Frontend**: A strict, style-free UI built with vanilla HTML5 and JavaScript to match academic terminal tooling. No heavy frameworks, no shadows, no rounded corners.

---

## Project Structure

```
HSME/
├── backend/
│   ├── main.py         # FastAPI endpoints (ingest, search, counterfactuals, gaps, reasoning)
│   ├── models.py       # Pydantic schemas (Entity, Experiment)
│   ├── database.py     # In-memory vector store, entity codebook, and mock data seeder
│   └── vsa.py          # Math operations for VSA (generate, bind, bundle, similarity)
├── frontend/
│   ├── index.html      # Minimalist dashboard
│   └── app.js          # API client and dynamic table renderer
├── tests/
│   ├── test_vsa.py     # Unit tests for VSA operations
│   ├── test_database.py# Unit tests for vector indexing and database queries
│   └── test_api.py     # Integration tests for HTTP endpoints
├── pyproject.toml      # uv configuration and dependencies
└── README.md           # This guide
```

---

## Installation & Setup

We recommend using [uv](https://github.com/astral-sh/uv) for fast package and python environment management.

### 1. Install Dependencies
Initialize the project environment and download dependencies (`fastapi`, `uvicorn`, `numpy`, `pydantic`, `pytest`, `httpx`):
```bash
uv sync
```

### 2. Run Tests
Verify the entire engine stack (mathematics, database, API routing) by running the test suite:
```bash
PYTHONPATH=. uv run pytest tests/ -v
```

### 3. Start the Development Server
Launch the FastAPI бэкенд and static frontend server:
```bash
uv run uvicorn backend.main:app --reload --port 8000
```
Open your browser and navigate to: **[http://localhost:8000](http://localhost:8000)**

---

## How VSA Is Used

### 1. Representation & Binding
Each unique parameter is mapped to a high-dimensional vector in a codebook (e.g., $\mathbf{V}_{\text{Alloy A}}$, $\mathbf{V}_{\text{Role:Alloy}}$).
We bind roles and fillers using element-wise multiplication ($\otimes$):
$$\mathbf{V}_{\text{bound}} = \mathbf{V}_{\text{Role:Alloy}} \otimes \mathbf{V}_{\text{Alloy A}}$$

### 2. Experiment Bundling (Hyperedge Encoding)
An experiment is encoded by bundling all of its role-filler bindings together via majority vote (element-wise sum followed by sign extraction):
$$\mathbf{V}_{\text{experiment}} = \text{sign}\left( \sum \mathbf{V}_{\text{bound\_i}} \right)$$

### 3. Querying
To search for experiments matching custom conditions (e.g. Alloy A at $900^\circ\text{C}$), we bundle the corresponding queries and compute the cosine similarity against all experiment vectors in the database:
$$\mathbf{V}_{\text{query}} = \text{sign}(\mathbf{V}_{\text{Role:Alloy}} \otimes \mathbf{V}_{\text{Alloy A}} + \mathbf{V}_{\text{Role:Temp}} \otimes \mathbf{V}_{\text{900C}})$$
$$\text{Similarity} = \frac{\mathbf{V}_{\text{query}} \cdot \mathbf{V}_{\text{experiment}}}{D}$$
Matches with high similarity scores are retrieved in milliseconds without complex graph traversal.
