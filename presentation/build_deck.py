"""Rebuild Capstone_Quiroga.pptx for the HPEC talk.

Reads the original deck, applies the restructure, writes Capstone_Quiroga_v2.pptx.
The original file is never modified.
"""
from __future__ import annotations

import copy
import os
import shutil

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Emu, Inches, Pt

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")
SRC = r"C:\Users\aaron\Downloads\Capstone_Quiroga.pptx"
DST = r"C:\Users\aaron\Downloads\Capstone_Quiroga_v2.pptx"

NAVY = RGBColor(0x0C, 0x18, 0x2B)
PURPLE = RGBColor(0x6B, 0x4E, 0x9B)
GRAY = RGBColor(0x5B, 0x66, 0x75)
BODY_PT = 34
# The master's decorative panel starts at 18.68in; keep content left of it.
SAFE_RIGHT = 18.5
CONTENT = (Inches(0.5), Inches(1.75), Inches(18.0), Inches(8.85))


# --------------------------------------------------------------------------
# slide-collection helpers (python-pptx has no public API for these)
# --------------------------------------------------------------------------
def _sldIdLst(prs):
    return prs.slides._sldIdLst


def delete_slide(prs, index):
    lst = _sldIdLst(prs)
    ids = list(lst)
    sld_id = ids[index]
    rId = sld_id.get(
        "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    )
    prs.part.drop_rel(rId)
    lst.remove(sld_id)


def move_slide(prs, old_index, new_index):
    lst = _sldIdLst(prs)
    ids = list(lst)
    el = ids[old_index]
    lst.remove(el)
    lst.insert(new_index, el)


def slide_index(prs, slide):
    for i, s in enumerate(prs.slides):
        if s is slide:
            return i
    raise ValueError("slide not in presentation")


# --------------------------------------------------------------------------
# content helpers
# --------------------------------------------------------------------------
def replace_text_everywhere(prs, pairs):
    """Run-level find/replace so existing character formatting survives."""
    hits = 0
    for slide in prs.slides:
        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            for para in shape.text_frame.paragraphs:
                for run in para.runs:
                    for old, new in pairs:
                        if old in run.text:
                            run.text = run.text.replace(old, new)
                            hits += 1
    return hits


def title_of(slide):
    for shape in slide.shapes:
        if shape.has_text_frame and shape.is_placeholder:
            if shape.placeholder_format.idx == 0:
                return shape
    return None


def body_of(slide):
    for shape in slide.shapes:
        if shape.has_text_frame and shape.is_placeholder:
            if shape.placeholder_format.idx == 1:
                return shape
    return None


def set_title(slide, text):
    sh = title_of(slide)
    if sh is None:
        return
    tf = sh.text_frame
    para = tf.paragraphs[0]
    if para.runs:
        para.runs[0].text = text
        for extra in para.runs[1:]:
            extra._r.getparent().remove(extra._r)
    else:
        para.add_run().text = text
    for extra in list(tf.paragraphs)[1:]:
        extra._p.getparent().remove(extra._p)


def set_bullets(slide, items, size=BODY_PT):
    """items: list of (text, level) or (text, level, bold)."""
    sh = body_of(slide)
    if sh is None:
        return
    tf = sh.text_frame
    tf.word_wrap = True
    for p in list(tf.paragraphs)[1:]:
        p._p.getparent().remove(p._p)
    first = tf.paragraphs[0]
    for r in list(first.runs):
        r._r.getparent().remove(r._r)

    def fill(para, spec):
        text, level = spec[0], spec[1]
        bold = spec[2] if len(spec) > 2 else False
        para.level = level
        run = para.add_run()
        run.text = text
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = PURPLE if bold else NAVY
        run.font.name = "Arial"

    fill(first, items[0])
    for spec in items[1:]:
        blank = tf.add_paragraph()
        blank.level = 0
        fill(tf.add_paragraph(), spec)


def clear_pictures(slide):
    for shape in list(slide.shapes):
        if shape.shape_type == 13:
            shape._element.getparent().remove(shape._element)


def fit_picture(slide, path, box=CONTENT, align="center"):
    """Drop in a picture scaled to fit `box`, preserving aspect ratio."""
    from PIL import Image

    bx, by, bw, bh = box
    with Image.open(path) as im:
        iw, ih = im.size
    scale = min(bw / iw, bh / ih)
    w, h = int(iw * scale), int(ih * scale)
    if align == "center":
        x = bx + (bw - w) // 2
    else:
        x = bx
    y = by + (bh - h) // 2
    return slide.shapes.add_picture(path, x, y, width=w, height=h)


def set_notes(slide, text):
    slide.notes_slide.notes_text_frame.text = text.strip()


def style_cell(cell, text, *, bold=False, size=22, color=NAVY, align_center=False):
    from pptx.enum.text import PP_ALIGN

    cell.text = ""
    para = cell.text_frame.paragraphs[0]
    run = para.add_run()
    run.text = text
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    run.font.name = "Arial"
    if align_center:
        para.alignment = PP_ALIGN.CENTER
    cell.margin_left = Inches(0.12)
    cell.margin_right = Inches(0.12)
    cell.margin_top = Inches(0.06)
    cell.margin_bottom = Inches(0.06)


# ==========================================================================
shutil.copyfile(SRC, DST)
prs = Presentation(DST)
print(f"opened copy: {len(prs.slides)} slides")

# --- 1. text corrections (before indices shift) ----------------------------
n = replace_text_everywhere(prs, [
    ("Collaborative AI for Cyber Mission",
     "Collaborative Generative AI for Cyber Mission"),
    ("document intensive", "document-intensive"),
    ("remain heavy manual", "remain heavily manual"),
    ("locally hosted on WS", "locally hosted on the workstation"),
    ("evidence grounded", "evidence-grounded"),
    ("Evidence grounded", "Evidence-grounded"),
    ("adaptive workflows orchestration", "adaptive workflow orchestration"),
    ("towards  higher-fidelity", "towards higher-fidelity"),
])
print(f"text replacements: {n}")

# --- 2. create the Limitations slide FIRST -------------------------------
# python-pptx names new slide parts by slide count, so adding after a delete
# collides with an existing slideN.xml. Add while the count is still 15.
lim = prs.slides.add_slide(prs.slide_layouts[0])

# --- 3. drop slides: references (15), create-mission (8), sign-in (6) ------
for idx in (14, 7, 5):
    delete_slide(prs, idx)
print(f"after deletions: {len(prs.slides)} slides")

# --- 4. move Limitations into place, just before Conclusion ---------------
move_slide(prs, slide_index(prs, lim), 10)
# order now: 1 Title, 2 Background, 3 Problem, 4 Solution, 5 Architecture,
#            6 MissionControl, 7 Overview, 8 DocumentPage,
#            9 Chart(all), 10 Chart(success), 11 Conclusion, 12 Questions

# --- 3. architecture ------------------------------------------------------
s = prs.slides[4]
clear_pictures(s)
fit_picture(s, os.path.join(ASSETS, "fig_architecture.png"),
            box=(Inches(0.5), Inches(1.9), Inches(17.0), Inches(8.6)),
            align="left")

# --- 4. workflow slide titles --------------------------------------------
set_title(prs.slides[5], "Mission Workflow: Setup")
set_title(prs.slides[6], "Mission Workflow: Overview")

# --- 5. document page -----------------------------------------------------
s = prs.slides[7]
set_title(s, "Document Page: Reviewing an Edit")
clear_pictures(s)
fit_picture(s, os.path.join(ASSETS, "fig_document_callout.png"),
            box=(Inches(0.5), Inches(1.75), Inches(12.5), Inches(8.6)),
            align="left")


def _side_para(tf, first, text, *, size, bold, color,
               space_before=0, space_after=0):
    para = tf.paragraphs[0] if first else tf.add_paragraph()
    run = para.add_run()
    run.text = text
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    run.font.name = "Arial"
    para.space_before = Pt(space_before)
    para.space_after = Pt(space_after)
    return para


# Sidebar text is a real text box, not baked into the image, so it stays editable.
side = s.shapes.add_textbox(Inches(13.25), Inches(3.2), Inches(5.15), Inches(6.0))
stf = side.text_frame
stf.word_wrap = True
_side_para(stf, True, "What the operator sees",
           size=30, bold=True, color=NAVY, space_after=24)
for _head, _body in [
    ("Grounded", "every proposal names the mission artifact it came from"),
    ("Reviewable", "the operator accepts or rejects — nothing applies silently"),
    ("Auditable", "the decision is logged against the mission record"),
]:
    _side_para(stf, False, _head, size=26, bold=True, color=PURPLE,
               space_before=16, space_after=4)
    _side_para(stf, False, _body, size=20, bold=False, color=GRAY,
               space_after=8)

# --- 6. benchmark results (scatter + table) -------------------------------
s = prs.slides[8]
set_title(s, "Local Model Benchmark")
clear_pictures(s)
fit_picture(s, os.path.join(ASSETS, "fig_tradeoff_labeled.png"),
            box=(Inches(0.6), Inches(1.9), Inches(10.2), Inches(8.6)))

rows, cols = 4, 4
tbl_shape = s.shapes.add_table(
    rows, cols, Inches(11.0), Inches(3.6), Inches(7.4), Inches(3.2)
)
tbl = tbl_shape.table
for w, i in zip((Inches(2.2), Inches(1.45), Inches(1.85), Inches(1.9)), range(4)):
    tbl.columns[i].width = w
headers = ["Model", "Success", "Time\n(successful)", "Time\n(all trials)"]
for i, h in enumerate(headers):
    style_cell(tbl.cell(0, i), h, bold=True, size=21, color=NAVY,
               align_center=i > 0)
data = [
    ("gemma2:2b", "100 / 100", "15.4 s", "15.4 s"),
    ("phi3", "44 / 100", "27.5 s", "21.9 s"),
    ("llama3.2:3b", "7 / 100", "89.0 s", "201.6 s"),
]
for r, row in enumerate(data, start=1):
    for c, val in enumerate(row):
        style_cell(tbl.cell(r, c), val, bold=(c == 0), size=21,
                   align_center=c > 0)

note = s.shapes.add_textbox(Inches(11.0), Inches(7.05), Inches(7.4), Inches(1.6))
tf = note.text_frame
tf.word_wrap = True
run = tf.paragraphs[0].add_run()
run.text = ("300 trials total  ·  one workstation (Ryzen 9, 16 GB, RTX 3060 "
            "Laptop)  ·  300 s job cap, 210 s invocation cap")
run.font.size = Pt(19)
run.font.color.rgb = RGBColor(0x5B, 0x66, 0x75)
run.font.name = "Arial"

# --- 7. failure modes -----------------------------------------------------
s = prs.slides[9]
set_title(s, "How the Models Failed")
clear_pictures(s)
fit_picture(s, os.path.join(ASSETS, "fig_failure_modes.png"),
            box=(Inches(0.8), Inches(1.9), Inches(18.4), Inches(6.6)))

box = s.shapes.add_textbox(Inches(1.2), Inches(8.6), Inches(17.3), Inches(1.7))
tf = box.text_frame
tf.word_wrap = True
for i, (text, color) in enumerate([
    ("phi3 fails fast and wrong.   llama3.2:3b fails slow and silent.", PURPLE),
    ("Only gemma2:2b clears both bars.", NAVY),
]):
    para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
    r = para.add_run()
    r.text = text
    r.font.size = Pt(28)
    r.font.bold = True
    r.font.color.rgb = color
    r.font.name = "Arial"

# --- 8. limitations (slide created above, now at index 10) ----------------
set_title(lim, "Limitations")
tsh, bsh = title_of(lim), body_of(lim)
ref = prs.slides[2]
rt, rb = title_of(ref), body_of(ref)
for dst_sh, src_sh in ((tsh, rt), (bsh, rb)):
    if dst_sh is not None and src_sh is not None:
        dst_sh.left, dst_sh.top = src_sh.left, src_sh.top
        dst_sh.width, dst_sh.height = src_sh.width, src_sh.height
set_bullets(lim, [
    ("Measured structural validity, not edit quality", 0),
    ("Synthetic mission corpus, not an operational mission", 0),
    ("Single workstation \u2014 different hardware moves the boundary", 0),
    ("No baseline against manual drafting", 0),
])

# --- 9. remaining titles --------------------------------------------------
set_title(prs.slides[11], "Conclusion and Future Work")

# --- 10. speaker notes ----------------------------------------------------
NOTES = [
    # 1 Title
    """[0:10]
Good morning. I'm Aaron Quiroga - Air Force cyber operator, and this is joint
work with Dr. Jeremy Kepner at MIT Lincoln Laboratory.
Collaborative Generative AI for Cyber Mission Planning, Analysis, and Reporting.""",
    # 2 Background
    """[0:45 | running 0:55]
Cyber Protection Teams conduct defensive operations on government networks using
cyber weapon systems. Every mission runs through four phases - plan, brief,
execute, debrief. Operators generate artifacts at every phase: crew logs, crew
notes, findings. Those artifacts have to be consolidated into formal products.
KEY LINE: the length of each phase sets the length of the mission.""",
    # 3 Problem
    """[0:45 | running 1:40]
That consolidation is manual. Every hour spent assembling reports is an hour not
spent on execution or analysis. And if you extend execution instead, the mission
runs longer - so the team runs fewer missions per year. That makes this an
operational problem, not an administrative one.
Two hard constraints: mission artifacts are sensitive, so this has to run locally
on the workstation - no cloud AI. And the formal record needs human
accountability - no silent automation.""",
    # 4 Solution
    """[0:40 | running 2:20]
So: a mission-scoped, evidence-grounded RAG platform. It ingests the mission's
own artifacts plus the reporting templates, and generates draft updates as
proposals a human approves.
Emphasis on proposals. The AI never commits anything to the mission record.""",
    # 5 Architecture
    """[1:15 | running 3:35]
Everything inside the dashed line stays on the mission workstation, and it is
isolated per mission - no mission's evidence reaches another.
TOP LANE, ingest: artifacts are normalized, chunked, embedded into a per-mission
FAISS index. This runs once and populates the store.
MIDDLE LANE, generate: the report template plus the current draft go to
gemma2:2b, which runs locally in Ollama, with evidence retrieved from that
index. (LangChain is the orchestration layer - it wires retrieval to the prompt
and calls Ollama. It does not run the model. Say this only if asked.) The output is a proposed block-level edit - not report text.
BOTTOM LANE is the contribution: that edit goes to an operator who accepts or
rejects it. Accepted edits update the draft and feed the next cycle. Approved
reports export as .docx to the mission output path.
(If asked what's omitted: FastAPI, Uvicorn, SQLite, Tiptap - implementation
detail.)""",
    # 6 Workflow setup
    """[0:35 | running 4:10]
Briefly, the workspace. Mission Control is where a mission lead sees current and
past missions and creates a new one. Creating a mission establishes the
workspace boundary - source path, output path, and the operator roster who get
access. Move quickly here.""",
    # 7 Workflow overview
    """[0:35 | running 4:45]
The mission overview is the coordination point: mission metadata, assigned team
members, which reports exist, and the review state of each. From here an
operator opens a report. Move quickly here too.""",
    # 8 Document page
    """[1:15 | running 6:00]
This is the core interaction - slow down here.
The operator is in a Risk Mitigation Plan. They request an update; the system
retrieves from the mission index and the local model proposes a change. Here it
proposed Finding 4 - multiple local admin accounts with weak passwords.
Three things matter:
GROUNDED - the proposal names crew_log_1.txt, the artifact it came from, so the
reviewer can trace it.
REVIEWABLE - accept or reject, in place, in context. Nothing enters the document
silently.
AUDITABLE - the decision is logged against the mission record.
That accountability chain is what makes this usable inside a formal reporting
process.""",
    # 9 Benchmark
    """[1:20 | running 7:20]
The central technical question: can a model small enough to run on this hardware
reliably produce a structured edit at all?
100 RMP trials per model, three local models, 300 trials total, one workstation -
Ryzen 9, 16 GB, RTX 3060 Laptop - through Ollama. A trial succeeds if the model
returns at least one valid block edit ready for review inside the time caps.
gemma2:2b: 100 out of 100, 15.4 seconds.
phi3: 44 out of 100.
llama3.2:3b: 7 out of 100.
POINT AT the all-trials column: llama averaged 201 seconds per attempt, because
most attempts ran to the cap.""",
    # 10 Failure modes
    """[1:00 | running 8:20]
These two failures are not the same failure.
phi3 never timed out once. It failed in about 17 seconds on average by emitting
JSON the pipeline could not parse. That is a FORMAT problem.
llama3.2:3b never produced malformed output. All 93 failures hit the 210-second
invocation cap exactly. That is a TERMINATION problem, not a speed problem:
we measured llama at the HIGHEST raw throughput of the three models and 88%
resident on GPU, so it is not memory placement and not slowness.
So phi3 fails fast and wrong; llama fails slow and silent. ("Slow" = the
failure burns the full cap, not that the model is slow - it isn't.)
Only gemma2:2b clears both bars.
The practical read: this is an output-format and termination boundary for
on-prem structured generation, not a general model ranking and not a hardware
limit.
(This breakdown is not in the paper - it is a deeper cut of the same 300 trials.)""",
    # 11 Limitations
    """[0:45 | running 9:05]
Three I want to state plainly.
We measured structural validity - whether a parseable edit came back - not
whether the edit was any good. Edit quality needs human evaluation. Future work.
The corpus is synthetic, not an operational mission.
These numbers are one workstation; different hardware moves the boundary.
And there is no baseline - we have not measured this against an operator
drafting by hand.
Say this plainly and without hedging. It buys credibility in Q&A.""",
    # 12 Conclusion
    """[0:40 | running 9:45]
Evidence-grounded, human-in-the-loop RAG is a workable approach for this
workflow, and local inference is feasible - but model choice dominates
reliability.
Next: deploy into our unit's testing environment, improve retrieval fidelity,
and explore adaptive workflow orchestration.""",
    # 13 Questions
    """Q&A PREP

"Why did llama3.2:3b fail?"
We measured this. It is NOT a memory or speed story - do not say VRAM.
On this workstation llama3.2:3b sits 88% resident on GPU (gemma 86%, phi3 only
51%) and has the highest raw throughput of the three at ~52 tok/s. The
benchmark prompt is ~2,100 tokens, well inside the 4,096 context.
What the data shows: every one of the 93 failures hit the invocation cap with
zero malformed output. That points to the model not terminating generation
under our JSON edit contract, rather than generating slowly. We have not
isolated that mechanism - that is future work.
If pressed on why gemma succeeds: it reliably emits a short, closed edit array;
llama does not, under the same contract.

"Did you measure whether the edits were any good?"
No. We measured structural validity and pipeline compatibility - whether a
parseable block edit came back and could be surfaced for review. Edit quality
and groundedness need human evaluation. Say this plainly; do not hedge.

"How does this handle adversarial input?"
Real risk. The platform ingests artifacts from potentially compromised networks
into an index that feeds an LLM, so prompt injection through planted log text is
possible. Human acceptance of every proposed edit is the current mitigation.
Input sanitization is not implemented.

"Why gemma2:2b and not a larger model?"
Constraint is the target hardware. The benchmark is about what runs on the
equipment operators actually have, not what runs in a datacenter.

"Is the architecture diagram's file list complete?"
The pipeline ingests .txt, .pdf, .docx. Figure 1 in the paper shows Excel/CSV;
that is aspirational and the Limitations section states the real list.""",
]
for i, note in enumerate(NOTES):
    if i < len(prs.slides):
        set_notes(prs.slides[i], note)

prs.save(DST)
print(f"\nwrote {DST}")
print(f"final slide count: {len(Presentation(DST).slides)}")
