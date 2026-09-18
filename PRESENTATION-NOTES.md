# HPEC presentation — working notes

Context carried over from a review session. The deck file is `Capstone_Quiroga.pptx`.

**Format:** 10-minute talk, 5 minutes of Q&A, at IEEE HPEC. The paper has already been
submitted (5 pages, under the 6-page limit). This document is about the presentation
only — the paper is done except for camera-ready items.

---

## Current deck inventory

14 visible slides, 1 hidden.

| # | Title | Content |
|---|---|---|
| 1 | Title | Name, title, mentor |
| 2 | Background | 5 bullets + PBED graphic + pipeline graphic |
| 3 | Problem statement | 4 bullets |
| 4 | Proposed solution | 3 bullets |
| 5 | System Architecture | Block diagram |
| 6 | Mission Workflow | Sign-in screenshot |
| 7 | Mission Workflow | Mission Control screenshot |
| 8 | Mission Workflow | Create New Mission screenshot |
| 9 | Mission Workflow | Mission Overview screenshot |
| 10 | Document Page | RMP editor with proposed edit |
| 11 | Local Model Comparison | Latency bar chart, all trials |
| 12 | Local Model Comparison | Latency bar chart, success trials only |
| 13 | Conclusion and Future Work | Bullets |
| 14 | Questions? | Contact info |
| 15 | References | HIDDEN — still has template placeholder text |

---

## The main structural problem

**The headline result is not on any slide.**

Both "Local Model Comparison" slides show latency only. The success rates — 100% for
gemma2:2b, 44% for phi3, 7% for llama3.2:3b — appear nowhere, and neither does the fact
that 300 trials were run. An audience watching two bar charts of seconds concludes "one
model is slower." The actual finding is that two of three models could not reliably
produce a usable edit at all.

**Fix:** replace one of the two chart slides with the reliability-vs-latency scatterplot
(Fig. 6 from the paper) or a simple results table. The scatterplot carries both
dimensions in one image and the file already exists.

---

## Timing

14 slides / 10 minutes ≈ 43 seconds per slide. The allocation is wrong:

- **5 slides of UI screenshots** (6–10) is over a third of the talk. The sign-in screen
  (slide 6) earns nothing — cut it.
- **2 chart slides** saying nearly the same thing. Consolidate to one.

That frees ~90 seconds for a results slide and a limitations slide. Target ~11 visible
slides.

---

## Content errors to fix

- Slide 3: "Planning and reporting remain heavy manual" → "heavily manual"
- Slide 3: "WS" is undefined — spell out "workstation"
- Slide 13: "Explore more adaptive workflows orchestration" → "workflow orchestration"
- Slide 13: double space in "towards  higher-fidelity"
- Slide 2: "document intensive" → "document-intensive"
- Slides 4 and 13: "evidence grounded" → "evidence-grounded"
- Slide 1: deck says "Collaborative AI"; the paper says "Collaborative Generative AI"
- Slide 15 (hidden): contains template placeholder text including its own typo ("Add you
  references here"). Delete the slide or fill it in before sharing the file.

---

## Architecture diagram (slide 5)

Three problems beyond cosmetics:

1. **Spell-check squiggles are baked into the exported image** — red wavy underlines
   visible under "Excel/CSVs", "Ollama", "Langchain", "FastAPI", "MISREP,etc". Very
   visible on a projector. Regenerate with spell-check display off.
2. **It's drawn as one flat left-to-right chain.** Ingestion and generation are different
   paths that run at different times — indexing populates the store once, then each
   request reads from it. A single line misrepresents how RAG works.
3. **The review loop is missing**, and it is the paper's central claim. The stick figures
   at bottom right read as an afterthought.
4. **Mission isolation isn't drawn.** The whole security argument is that everything stays
   inside a locally hosted boundary, and there's no boundary in the figure.
5. **"Excel/CSVs" contradicts the pipeline**, which only handles .txt, .pdf, .docx. Also
   contradicts the paper's own Limitations section.

### Agreed redesign structure

Three lanes inside a dashed boundary labeled "Mission workspace · locally hosted,
isolated per mission":

- **Ingest lane (top):** Mission artifacts (.txt, .pdf, .docx) → Normalize + embed
  (chunk, tag, encode) → Mission index (FAISS vector store)
- **Generation lane (middle):** Template + draft (RMP, AAR, SITREP) → gemma2:2b (local,
  via LangChain) → Proposed edit (block-level change). The mission index feeds down into
  the model.
- **Review lane (bottom):** Proposed edit → Operator review (accept or reject) →
  Approved report (written as .docx). A return arrow runs from Operator review back to
  Template + draft — that loop is the contribution.

Color: teal for retrieval/generation, purple for the human-review path, gray for
inputs/outputs.

FastAPI, Uvicorn, SQLite, and Tiptap were deliberately left off — implementation detail
that doesn't help a 43-second slide. Name them verbally if asked, or add a small caption.

---

## Repeated slide titles

Four consecutive slides titled "Mission Workflow" and two titled "Local Model
Comparison." The audience loses track of position. Give each a specific subtitle:
"Mission Workflow: Setup", "Mission Workflow: Overview", "Document Page: Reviewing an
Edit", etc.

---

## Missing slides

**Limitations.** The paper has one; the deck doesn't. Without it, Q&A opens with someone
raising a gap you already know about, and you look less prepared than you are. Three
bullets: measured structural validity not edit quality, synthetic corpus, single
workstation.

**Speaker notes.** Every notes field is currently empty. For a timed 10-minute talk, one
line per slide helps hold pace.

---

## Chart defect

Slide 12's embedded chart title reads "100 trials per model" while its bars are labeled
n=44, n=100, n=7. Same defect as Fig. 5 in the paper. Fix when regenerating.

---

## Strategic guidance

### Do not add math to look more complex

This was raised and argued against. Bolting an equation or complexity bound onto a
systems demo doesn't signal rigor to an HPEC audience — it signals that the presenter
thought the work needed decoration. Those attendees do performance analysis for a living,
and math that can't be defended under questioning becomes the thing they remember.

Padding also costs the talk its best asset. The differentiator at a compute conference is
a concrete operational problem, a system that runs, and 300 real trials. Most submissions
have one or two of those.

### The one move that genuinely raises the ceiling

Check `ollama ps` for each model and look at the CPU/GPU split. If llama3.2:3b is
spilling layers to system memory on a 6 GB laptop GPU, the finding changes from a model
ranking to a **hardware threshold for viable on-prem structured-edit generation on
tactical-class equipment.** Same data, correct interpretation, much more interesting to
an HPC audience.

Two smaller items in the same category: pull standard deviations into a table (the error
bars mean the data exists), and split the 56 phi3 failures and 93 llama failures into
timeouts vs. malformed output.

### Where the ceiling sits this cycle

No baseline comparison (no-RAG vs. RAG, local vs. cloud, tool vs. manual) and no
evaluation of edit quality. Those absences cap this below a top-tier research talk
regardless of presentation. The honest framing — "we built it, we measured whether local
inference is even feasible, here's the hardware boundary we found" — will land better
than overreaching. Audiences are generous toward work that knows its own limits and
unforgiving toward work that oversells.

**Assessment as the deck currently stands:** middle of the pack, possibly slightly below,
because the result is invisible. With the fixes above: upper third for an applied talk.

---

## Q&A preparation

**"Why did llama3.2:3b fail?"**
"We didn't instrument that, but the likely cause is VRAM — the 3060 Laptop is 6 GB, and
a 3B model at that quantization can spill layers to CPU. The 201-second all-trial mean
versus 89 seconds on successes is consistent with timeouts rather than fast malformed
output. Confirming it is future work." (Replace with real numbers if `ollama ps` gets
checked first.)

**"Did you measure whether the edits were any good?"**
No. The benchmark measured structural validity and pipeline compatibility — whether the
model returned a parseable block edit that could be surfaced for review. Edit quality and
groundedness need human evaluation, which is future work. Say this plainly rather than
hedging.

**"How does this handle adversarial input?"**
The platform ingests artifacts from potentially compromised networks into a retrieval
index feeding an LLM, so prompt injection through planted log text is a real risk. Human
acceptance of every proposed edit is the current mitigation. Input sanitization is not
implemented.

---

## Task list

1. Replace one latency chart with the scatterplot or a results table showing success rates
2. Cut the sign-in screenshot (slide 6)
3. Regenerate the architecture diagram per the structure above, spell-check display off
4. Add a limitations slide
5. Differentiate the repeated slide titles
6. Fix the content errors listed above
7. Delete or complete the hidden references slide
8. Regenerate the success-trials chart with a correct title
9. Add speaker notes, one line per slide
10. Run `ollama ps` per model and check the CPU/GPU split
11. Pull standard deviations and the failure-mode breakdown from raw benchmark results

---

## Status — 2026-09-12

Deck rebuilt to 13 slides as `~/Downloads/Capstone_Quiroga_v2.pptx`
(original untouched). Details in [presentation/CHANGES.md](presentation/CHANGES.md).

| # | Task | Status |
|---|---|---|
| 1 | Replace a latency chart with scatterplot / results table | Done — slide 9 |
| 2 | Cut the sign-in screenshot | Done (also cut create-mission) |
| 3 | Regenerate the architecture diagram | Done — generated from code, no squiggles |
| 4 | Add a limitations slide | Done — slide 11 |
| 5 | Differentiate repeated slide titles | Done |
| 6 | Fix the content errors | Done — all 8 |
| 7 | Delete or complete the hidden references slide | Deleted |
| 8 | Regenerate success-trials chart with correct title | Superseded — both bar charts replaced |
| 9 | Add speaker notes, one line per slide | Done — with running clock |
| 10 | Run `ollama ps`, check CPU/GPU split | Done — **result overturns the VRAM answer, see below** |
| 11 | Pull std devs + failure-mode breakdown | Done — slide 10 |

### Task 10 result: the VRAM explanation is wrong

Measured on this workstation, Ollama 0.17.1, default 4096 context:

| Model | Resident | CPU/GPU split | Raw throughput |
|---|---|---|---|
| gemma2:2b | 3.5 GB | 14% / 86% | 31–38 tok/s |
| phi3 | 5.9 GB | **49% / 51%** | 17–19 tok/s |
| llama3.2:3b | 3.5 GB | **12% / 88%** | **51–52 tok/s** |

llama3.2:3b sits *further on the GPU than gemma2:2b* and has the **highest**
raw token throughput of the three. phi3 has by far the worst CPU spill yet is
the second fastest end-to-end. So the prepared Q&A answer — "likely VRAM, a 3B
model spilling layers on a 6 GB GPU" — is not supported and would not survive
questioning from this audience.

The benchmark prompt is only ~2,100 tokens, so context overflow is not the
cause either.

**Do not give the VRAM answer.** Replacement wording is in the slide 13
speaker notes.

### What is NOT established about llama's timeouts

Measured and solid:
- Not memory placement (88% GPU, better than phi3's 51%).
- Not raw speed (highest tok/s of the three, on both a small prompt and a
  ~2,100-token one).
- Not context overflow (benchmark prompt ~2,100 tokens vs 4,096 window).
- Every one of the 93 failures hit the cap with **zero** malformed output.

Not established: the mechanism. The leading hypothesis is that llama fails to
terminate generation under the JSON edit contract, but **this is unconfirmed.**

I tried to reproduce it by reconstructing the benchmark prompt (RMP template +
all 10 sample_mission artifacts + the structured-edit prompt + JSON suffix,
~8.5 KB) and streaming each model with `format: json`. **All three models ran
past a 90 s cap without terminating** — gemma 642 tokens, phi3 735, llama 1,069.
Since gemma actually succeeded 100/100 in 15.4 s in the real benchmark, the
reconstruction does not reproduce the benchmark condition and is therefore
**not evidence about the mechanism.** Dead end; do not cite it.

To settle it properly you would need to instrument the real pipeline path
(`_run_structured_edits`) with token-level streaming and capture output on
timeout, which `run_with_timeout` currently discards. Worth doing, not before
Monday.
