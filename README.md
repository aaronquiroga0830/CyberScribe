# CyberScribe

CyberScribe is a locally hosted workspace for turning mission documents into evidence-grounded reports. It combines a rich-text editor, local AI assistance, and human review for Risk Mitigation Plans (RMP), mission timelines, After Action Reports (AAR), and SITREPs.

AI proposes changes; people review, accept, edit, and approve them. Reports and mission data remain in your configured local folders. Ollama provides local model inference.

## What runs where

- **Ollama** runs the language model on your computer.
- **Python / FastAPI** serves the API, authenticates users, retrieves mission evidence, and saves reports.
- **Vite / TypeScript / Tiptap** builds the browser interface. FastAPI serves the finished build; a separate Node server is not required.
- **SQLite and FAISS** store application state and per-mission indexes locally.

## Prerequisites

Install these before starting:

- **Python 3.13** (the validated Python version).
- **Node.js 24 LTS** and npm. Vite requires Node 20.19+ or 22.12+; Node 24 is used for validation.
- **Git** to clone and update the repository.
- **[Ollama](https://ollama.com/download)** to run a local language model.

The first Python install and embedding-model download can take several minutes. On Linux, install your distribution's Python venv package if `python3 -m venv` is unavailable.

## First-time setup

Run all commands from the **repository root**, where `server.py`, `requirements.txt`, and `package.json` live. Do not run npm from `web/`.

### 1. Get the project

```bash
git clone https://github.com/aaronquiroga0830/CyberScribe.git
cd CyberScribe
```

This repository is private; cloning requires an account with access. If you already have the project, open a terminal in your existing project folder instead.

### 2. Create the Python environment

**Windows PowerShell:**

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

If PowerShell blocks activation, use `.\.venv\Scripts\python.exe` in place of `python` in subsequent commands. Activation is only a convenience.

**Linux / macOS:**

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
[ -f .env ] || cp .env.example .env
```

Keep an existing `.env`: it may contain your chosen model and data paths.

### 3. Prepare Ollama

Start the Ollama application. If it is not already running as a background service, run this in a separate terminal and leave it open:

```bash
ollama serve
```

Download the model selected in `.env`. The example configuration uses:

```bash
ollama pull gemma2:2b
ollama list
```

You can use another installed model by setting `OLLAMA_MODEL` to its exact name. The default Ollama address is `http://127.0.0.1:11434`.

Embeddings use `sentence-transformers` and `all-MiniLM-L6-v2` by default. That model downloads on first use; it does not need an `ollama pull` command.

### 4. Build the browser interface

From the repository root:

```bash
npm ci
npm run typecheck
npm run build
```

This produces `web/dist/`. **The build is required** before opening the application. TypeScript source files cannot be served directly as a working production interface.

### 5. Start CyberScribe

With the Python environment active:

```bash
python -m uvicorn server:app --host 127.0.0.1 --port 8000
```

Leave that terminal open and visit **http://127.0.0.1:8000**. Stop the server with **Ctrl+C**.

### 6. Create an account and your first mission

1. On the sign-in page, select **Create initial admin**. Enter a display name, username, and password. This works only when no users exist yet.
2. Sign in with that account.
3. Select **+ New mission**, and enter its name and source/output folders. These are paths on the machine running the Python server.
4. Put mission evidence in the source folder. Supported files are **UTF-8 `.txt`, text-based `.pdf`, and `.docx`**. DOCX paragraphs and tables are supported; scanned PDFs require OCR outside CyberScribe.
5. Open a report and request an update. The first update may take longer while the embedding model and index initialize.
6. Review the proposed changes, accept or reject them, and save your edits. Use the review workflow and export controls when the report is ready.

The source and output folders should be separate. Approved/saved report exports use the mission's configured output folder.

## Starting it again

After the first setup, start Ollama and run these from your existing project folder:

**Windows PowerShell:**

```powershell
.\.venv\Scripts\python.exe -m uvicorn server:app --host 127.0.0.1 --port 8000
```

**Linux / macOS:**

```bash
.venv/bin/python -m uvicorn server:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000**. You do not need to reinstall packages or rebuild the interface on every launch.

After updating the project, install any changed Python requirements and run `npm ci`, `npm run typecheck`, and `npm run build`. Restart the Python server after rebuilding or changing configuration.

## Configuration

Copy `.env.example` once and edit `.env` as needed:

```dotenv
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=gemma2:2b
EMBEDDING_PROVIDER=sentence-transformers
EMBEDDING_MODEL=all-MiniLM-L6-v2
VECTOR_STORE_TYPE=faiss
DATA_DIR=data
OUTPUT_DIR=output
```

- Relative data paths are resolved from the repository root.
- `OLLAMA_GENERATE_TIMEOUT_S` optionally limits each generation request in seconds. Unset means no limit.
- For Ollama embeddings, set `EMBEDDING_PROVIDER=ollama`, select an embedding model in `EMBEDDING_MODEL`, and pull that model with Ollama.
- Rebuild mission indexes after changing the embedding model or vector-store backend.
- Optional `OLLAMA_BASE_URL_RMP` and `OLLAMA_BASE_URL_TIMELINE` route those reports to separate Ollama instances. Ollama's `OLLAMA_NUM_PARALLEL` belongs in the Ollama server environment.
- Chroma is an optional backend retained in the code; it requires a separate `chromadb` installation. The standard setup and validation use FAISS.

## Optional CLI and scheduler

The browser workflow is the main application and supports all four report types. The separate CLI and scheduler retain the older RMP/Timeline workflow; they are not required to use the web app.

```bash
python run.py build mission_alpha --source /path/to/mission/documents
python run.py run mission_alpha
python run.py all mission_alpha --source /path/to/mission/documents
```

For the daily scheduler, create the mission through the UI first, then run this in another activated terminal:

```bash
python run_scheduler.py
```

It processes active missions daily at 02:00 local time. Run it only when you want that background workflow.

## Development and checks

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python -m pip check
npm ci
npm run typecheck
npm run build
```

API smoke tests use a temporary database and do not call Ollama. GitHub Actions runs the Python tests and front-end checks on pushes and pull requests.

## Research tools

Benchmark dependencies are separate from the application:

```bash
python -m pip install -r requirements-research.txt
python scripts/llm_benchmark.py --help
```

The benchmark entry point is `scripts/llm_benchmark.py`; runs write to `output/benchmark/`. Preserve benchmark outputs used by research and evaluation. Research notes and assets may be maintained locally alongside the application.

## Data and backups

The platform was previously called Agentic RAG MVP. The existing `data/agentic_rag.db` filename is retained so upgrades continue using your current accounts and missions.

Git excludes `.env`, `.venv/`, `node_modules/`, `web/dist/`, mission source files under `data/missions/`, indexes, application database files, temporary files, logs, and `output/`.

Back up your database, mission source folders, output folders, and `.env` separately. Stop CyberScribe and its scheduler before copying the SQLite database. GitHub stores the application code; it is not a backup of ignored mission data. Additional research files are not automatically ignored.

## Troubleshooting

- **Web app is not built / HTTP 503:** run `npm ci` and `npm run build` in the repository root, then restart the server.
- **Changes do not appear:** rebuild with `npm run build`, restart the server, and refresh the browser.
- **Ollama connection refused:** start Ollama and check `OLLAMA_BASE_URL`.
- **Model not found:** run `ollama list`, pull the required model, and match `OLLAMA_MODEL` exactly.
- **First update is slow:** initial model downloads, index creation, and local inference take time. Check both server terminals for errors.
- **Import errors:** use the project's `.venv` Python and install `requirements.txt` from the repository root.
- **Port 8000 is busy:** use `--port 8001` and open `http://127.0.0.1:8001`.
- **No source documents:** verify that the mission's source folder exists on the server machine and contains supported files.

## Project documentation

Start with this README for current installation instructions. [PROJECT_MASTER.md](docs/PROJECT_MASTER.md) describes the architecture and workflows; [PROJECT_CONTEXT.md](docs/PROJECT_CONTEXT.md) maps the source files. Planning documents record design history and may describe earlier versions or future work.

## License

Private thesis / research project. No open-source license has been granted.
