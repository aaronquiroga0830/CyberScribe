# Agentic RAG MVP

Mission-scoped RAG platform for structured report updates (RMP, Timeline, AAR, SITREP) with human-in-the-loop review.

## Quick start

1. **Read first:** [docs/PROJECT_MASTER.md](docs/PROJECT_MASTER.md) — architecture, API, run instructions, conventions.
2. **Environment:** Copy [`.env.example`](.env.example) to `.env` and adjust paths/models.
3. **Python:** `python -m venv .venv`, activate, `pip install -r requirements.txt`
4. **Ollama:** Install [Ollama](https://ollama.com), pull a chat model (e.g. `ollama pull phi3`) and an embedding model if using Ollama embeddings.
5. **Front-end (optional):** `npm install` in `web/`, build per PROJECT_MASTER §19.

## Local-only data (not in git)

Per [`.gitignore`](.gitignore), these stay on your machine:

- `.env` — secrets and local overrides
- `data/missions/` — mission source documents (add your own after clone)
- `data/indexes/`, `data/agentic_rag.db` — built at runtime
- `output/` — generated reports and benchmark artifacts

## Benchmark

LLM comparison harness: [`scripts/llm_benchmark.py`](scripts/llm_benchmark.py).  
After a run, see `output/benchmark/BENCHMARK_REPORT.md` (local) for methodology and results.

## License

Private thesis / research project unless otherwise noted.
