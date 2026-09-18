"""Local LLM-as-judge for RMP structured-edit grounding scores."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CHECKLIST_PATH = PROJECT_ROOT / "data" / "eval" / "rmp_gold" / "checklist.json"
RUBRIC_PATH = PROJECT_ROOT / "data" / "eval" / "rmp_gold" / "RUBRIC.md"

DEFAULT_JUDGE = "llama3.2:3b"
CROSS_JUDGE = "phi3"


def load_checklist() -> dict[str, Any]:
    if not CHECKLIST_PATH.is_file():
        return {"items": []}
    return json.loads(CHECKLIST_PATH.read_text(encoding="utf-8"))


def pick_judge_model(subject_model: str, default_judge: str = DEFAULT_JUDGE) -> str:
    sub = subject_model.lower().split(":")[0]
    judge = default_judge.lower().split(":")[0]
    if sub == judge or subject_model == default_judge:
        return CROSS_JUDGE
    return default_judge


def fetch_rmp_context(mission_id: str, max_chars: int = 12000) -> str:
    from src.templates.prompts import RMP_TEMPLATE_QUERY
    from src.retrieve.retriever import get_mission_retriever
    from src.utils.context_cleaner import clean_context_for_llm

    retriever = get_mission_retriever(mission_id=mission_id, report_type="rmp")
    docs = retriever.invoke(RMP_TEMPLATE_QUERY)
    raw = "\n\n---\n\n".join(d.page_content for d in docs)
    ctx = clean_context_for_llm(raw)
    if len(ctx) > max_chars:
        ctx = ctx[:max_chars] + "\n...[truncated]"
    return ctx


def _ollama_chat_json(model: str, system: str, user: str, base_url: str) -> dict[str, Any]:
    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
        }
    ).encode("utf-8")
    url = base_url.rstrip("/") + "/api/chat"
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    text = (data.get("message") or {}).get("content") or "{}"
    return json.loads(text)


def _strip_html(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html or "").strip()


def judge_edit(
    edit: dict[str, Any],
    source_context: str,
    checklist: dict[str, Any],
    judge_model: str,
    base_url: str,
) -> dict[str, Any]:
    items = checklist.get("items") or []
    checklist_text = "\n".join(f"- {i['id']}: {i['label']}" for i in items)
    rubric = ""
    if RUBRIC_PATH.is_file():
        rubric = RUBRIC_PATH.read_text(encoding="utf-8")[:2000]

    system = (
        "You score RMP document edits for factual grounding against source material. "
        "Output ONLY valid JSON with keys: grounding_score (1-5 int), hallucination (bool), "
        "checklist_items_addressed (array of id strings), rationale (short string)."
    )
    user = f"""RUBRIC:
{rubric}

CHECKLIST:
{checklist_text}

SOURCE TEXT:
{source_context}

EDIT:
target_block_id: {edit.get('target_block_id')}
reason: {edit.get('reason')}
new_html: {_strip_html(edit.get('new_html') or '')}

Score grounding of new_html and reason against SOURCE TEXT only."""

    try:
        out = _ollama_chat_json(judge_model, system, user, base_url)
        score = int(out.get("grounding_score", 1))
        score = max(1, min(5, score))
        return {
            "grounding_score": score,
            "hallucination": bool(out.get("hallucination", False)),
            "checklist_items_addressed": out.get("checklist_items_addressed") or [],
            "rationale": str(out.get("rationale") or "")[:500],
            "judge_error": "",
        }
    except (urllib.error.URLError, json.JSONDecodeError, KeyError, ValueError) as e:
        return {
            "grounding_score": 1,
            "hallucination": True,
            "checklist_items_addressed": [],
            "rationale": "",
            "judge_error": str(e),
        }


def score_trial_edits(
    mission_id: str,
    subject_model: str,
    edits: list[dict[str, Any]],
    *,
    judge_model: str | None = None,
    base_url: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from config.settings import get_ollama_base_url_for_report

    if not edits:
        return [], {
            "mean_grounding_score": None,
            "grounded_edit_rate": 0.0,
            "checklist_recall": 0.0,
            "hallucination_rate": 0.0,
            "judge_model": judge_model or pick_judge_model(subject_model),
            "edit_count": 0,
        }

    jm = judge_model or pick_judge_model(subject_model)
    url = base_url or get_ollama_base_url_for_report("rmp")
    checklist = load_checklist()
    context = fetch_rmp_context(mission_id)
    all_item_ids = {i["id"] for i in (checklist.get("items") or [])}

    rows: list[dict[str, Any]] = []
    addressed: set[str] = set()
    for edit in edits:
        result = judge_edit(edit, context, checklist, jm, url)
        for cid in result["checklist_items_addressed"]:
            addressed.add(str(cid))
        rows.append(
            {
                "edit_id": edit.get("edit_id"),
                "grounding_score": result["grounding_score"],
                "hallucination": result["hallucination"],
                "checklist_items_addressed": "|".join(result["checklist_items_addressed"]),
                "rationale": result["rationale"],
                "judge_error": result["judge_error"],
            }
        )

    scores = [r["grounding_score"] for r in rows if r["grounding_score"] is not None]
    grounded = sum(
        1 for r in rows if r["grounding_score"] >= 4 and not r["hallucination"]
    )
    halluc = sum(1 for r in rows if r["hallucination"])
    summary = {
        "mean_grounding_score": round(sum(scores) / len(scores), 2) if scores else None,
        "grounded_edit_rate": round(grounded / len(rows), 3),
        "checklist_recall": round(len(addressed & all_item_ids) / len(all_item_ids), 3)
        if all_item_ids
        else 0.0,
        "hallucination_rate": round(halluc / len(rows), 3),
        "judge_model": jm,
        "edit_count": len(rows),
    }
    return rows, summary
