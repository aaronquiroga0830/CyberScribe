# HPEC deck rebuild — what changed and why

**Source:** `~/Downloads/Capstone_Quiroga.pptx` (untouched)
**Output:** `~/Downloads/Capstone_Quiroga_v2.pptx` + `Capstone_Quiroga_v2.pdf`
**Rebuild command:** `.venv/Scripts/python.exe presentation/build_deck.py`

The original file is never modified. Re-running the build regenerates v2 from
scratch, so edits made by hand in v2 are lost on rebuild — once you start
hand-editing, stop rebuilding.

---

## Structure: 14 visible + 1 hidden  →  13 visible

| # | Slide | Status |
|---|-------|--------|
| 1 | Title | text fix |
| 2 | Background | text fix |
| 3 | Problem statement | text fixes |
| 4 | Proposed solution | text fix |
| 5 | System Architecture | **new diagram** |
| 6 | Mission Workflow: Setup | retitled |
| 7 | Mission Workflow: Overview | retitled |
| 8 | Document Page: Reviewing an Edit | **new composite w/ magnified callout** |
| 9 | Local Model Benchmark | **new — scatter + results table** |
| 10 | How the Models Failed | **new slide** |
| 11 | Limitations | **new slide** |
| 12 | Conclusion and Future Work | text fixes |
| 13 | Questions? | Q&A prep in notes |

**Cut:** sign-in screenshot, create-mission screenshot, hidden references slide
(it still had template placeholder text, including its own typo).

**Timing:** ~9:45 against a 10-minute slot. Per-slide targets and a running
clock are in the speaker notes of every slide.

---

## Why the two bar charts are gone

Both old chart slides plotted latency only, with near-identical bars. The
success rates — 100% / 44% / 7% — appeared nowhere in the deck, and slide 12's
embedded chart title said "100 trials per model" over bars labeled n=44, n=100,
n=7.

They are replaced by two slides that each carry a distinct claim:

- **Slide 9** — reliability *and* latency in one scatter, plus the table with
  the all-trials column (that's where llama's 201.6 s lives).
- **Slide 10** — the failure-mode breakdown, which is new analysis.

---

## New analysis on slide 10

Computed from the 300 rows in `output/benchmark/experiment3/results.csv`:

| Model | Success | Malformed JSON | Timed out | Mean time when failing |
|---|---|---|---|---|
| gemma2:2b | 100 | 0 | 0 | — |
| phi3 | 44 | 54 | 0 | 17.5 s (median 13.8) |
| llama3.2:3b | 7 | 0 | 93 | 210.0 s (all 93 identical) |

Two opposite failure modes the old bar charts hid completely. All 93 llama
failures hit the 210 s invocation cap *exactly*; phi3 never timed out once.

Standard deviations, all trials: gemma 11.1 s, phi3 22.4 s, llama 31.9 s.

This breakdown is **not in the submitted paper** — it is a deeper cut of the
same 300 trials. Worth saying so if asked.

---

## Architecture diagram

The old PNG had five problems: red spell-check squiggles baked into the export
(visible under "CSVs", "MISREP", "Ollama", "Langchain", "FastAPI"); one flat
left-to-right chain that misrepresented how RAG works; no review loop; no
mission boundary; and "Excel/CSVs" as an input, which contradicts both the
pipeline and the paper's own Limitations section.

The replacement draws three lanes inside a dashed mission boundary — ingest
populates the index, generation reads from it, review closes the loop back to
the draft. Inputs list `.txt / .pdf / .docx` only. Generated from code, so
there are no spell-check artifacts.

FastAPI, Uvicorn, SQLite and Tiptap are deliberately omitted — implementation
detail that doesn't earn space on a 45-second slide. Name them verbally if
asked.

---

## Text corrections applied

| Slide | Was | Now |
|---|---|---|
| 1 | Collaborative AI | Collaborative **Generative** AI (matches paper) |
| 2 | document intensive | document-intensive |
| 3 | remain heavy manual | remain heavily manual |
| 3 | locally hosted on WS | locally hosted on the workstation |
| 4, 12 | evidence grounded | evidence-grounded |
| 12 | adaptive workflows orchestration | adaptive workflow orchestration |
| 12 | towards··higher-fidelity | towards higher-fidelity |

---

## Assets (for Google Slides, or to reuse)

All under `presentation/assets/`. PNG for slides, PDF where vector matters.

| File | Slide | Regenerate with |
|---|---|---|
| `fig_architecture.png/.pdf` | 5 | `make_architecture.py` |
| `fig_document_callout.png` | 8 | `make_document_callout.py` |
| `fig_tradeoff_labeled.png/.pdf` | 9 | `make_benchmark_figs.py` |
| `fig_failure_modes.png/.pdf` | 10 | `make_benchmark_figs.py` |
| `src_*.png` | — | extracted originals from the old deck |

### Applying by hand in Google Slides

1. Delete the sign-in and create-mission screenshot slides, and the hidden
   references slide.
2. Slide 5: replace the image with `fig_architecture.png`.
3. Slide 8 (document page): replace with `fig_document_callout.png`; retitle
   "Document Page: Reviewing an Edit".
4. Replace the first chart slide with `fig_tradeoff_labeled.png` and add the
   results table; retitle "Local Model Benchmark".
5. Replace the second chart slide with `fig_failure_modes.png`; retitle "How
   the Models Failed"; add the punchline line underneath.
6. Add a Limitations slide before Conclusion (four bullets, see slide 11).
7. Apply the text corrections above.
8. Copy speaker notes from the v2 pptx.

Keep content left of **18.5 in** on this 20 × 11.25 in canvas — the master's
decorative panel starts at 18.68 in and silently covers anything under it.
