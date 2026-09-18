# Structured-edit reliability: fallback problem and mitigations

## What we observed (Experiment 2, n = 10)

On identical RMP `full_refresh` jobs, **60–70% of trials** invoked **full-draft RAG fallback** after the structured-edit path produced zero valid edits. Structured success (valid JSON, ≥1 edit, no fallback) was only **30–40%** per model.

This is a **pipeline reliability** result, not a reason to discard the benchmark. It shows that the current contract—*the model must emit a JSON array of edits with HTML in string fields*—is hard for local 3B-class models on a placeholder RMP shell.

## Root causes (in priority order)

1. **Invalid JSON in LLM output** — especially `Invalid \escape` when `old_html` / `new_html` contain backslashes, quotes, or unescaped HTML (see `run_10trial.err`).
2. **Empty or non-array JSON** — model adds prose or markdown fences despite instructions.
3. **Invalid `target_block_id`** — edits dropped in validation; if all drop, `len(edits)==0` triggers fallback (same as parse failure).
4. **Placeholder draft** — `[To be filled from mission data]` in every section makes “minimal edits” ambiguous; models often over-generate or produce huge JSON.
5. **No JSON mode on structured path** — the LLM judge uses Ollama `format: "json"`; structured edits used plain `ChatOllama` text completion until mitigations below.
6. **Immediate fallback policy** — `server.py` runs expensive full-draft RAG whenever `len(edits)==0`, which helps UX but inflates wall-clock and benchmark “failure” counts.

## Paper acknowledgment (suggested wording)

> Structured block-edit updates proved brittle in our evaluation: only 30–40% of trials completed without JSON parse failure or escalation to full-draft generation fallback. We treat this as a limitation of the current prompt and response format on local models, not as an intrinsic ceiling on RAG quality. Section X reports reliability separately from latency on the subset of structured-success trials.

## Mitigations (implemented or planned)

| Mitigation | Status | Effect |
|------------|--------|--------|
| Ollama **`format: "json"`** + `{"edits": [...]}` wrapper on retry | Implemented | Forces syntactically valid JSON object |
| **Server-side `old_html`** from block map (omit in prompt) | Implemented | Removes largest source of escape errors |
| **Robust parse** (fences, array extraction, object wrapper) | Implemented | Recovers some valid edits without fallback |
| **Seeded partial RMP** for eval (Experiment 3) | Planned | Realistic draft → smaller, targeted edits |
| **One repair retry** (small model or same model) | Partial (JSON retry) | Cheaper than full-draft fallback |
| **Defer fallback** / user-visible “retry structured” | Future | Avoid silent 10+ min full draft in benchmarks |
| **Benchmark: report fallback rate** | Done | `fig_paper_structured_reliability.pdf` |

## How to re-measure after mitigations

Run a new experiment id (do not overwrite `experiment2/`):

```powershell
.\.venv\Scripts\python.exe scripts\llm_benchmark.py --run --plot `
  --experiment-id experiment2_json_mode `
  --mission-id llm_benchmark --trials 10 --timeout 300
```

Compare `structured_success_rate` and `fallback_rate` to `experiment2/summary_table.csv`.
