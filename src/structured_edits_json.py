"""
Parse and normalize structured-edit JSON from local LLMs.
Reduces fallback by accepting {"edits": [...]} or [...], and filling old_html server-side.
"""
from __future__ import annotations

import json
import re
from typing import Any

from src.document_blocks import DocumentBlock


def _strip_markdown_fences(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```\s*$", "", text)
    return text.strip()


def _extract_json_array_substring(text: str) -> str | None:
    """Return first top-level [...] substring if present."""
    start = text.find("[")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def parse_edits_payload(raw: str) -> tuple[list[Any], bool]:
    """
    Parse LLM output into a list of edit dicts.
    Returns (edits_raw_list, parse_failed).
    """
    text = _strip_markdown_fences(raw)
    if not text:
        return [], False

    candidates: list[str] = [text]
    arr = _extract_json_array_substring(text)
    if arr and arr != text:
        candidates.append(arr)

    last_error: json.JSONDecodeError | None = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as e:
            last_error = e
            continue
        if isinstance(parsed, dict) and "edits" in parsed:
            edits = parsed["edits"]
            out = list(edits) if isinstance(edits, list) else [edits]
            return out, False
        if isinstance(parsed, list):
            return parsed, False
        if isinstance(parsed, dict):
            return [parsed], False

    return [], last_error is not None


def fill_old_html_from_blocks(
    edits_raw: list[Any],
    blocks: list[DocumentBlock],
) -> list[dict[str, Any]]:
    """Attach old_html from current block HTML when the model omitted it."""
    by_id = {b.block_id: b.html for b in blocks}
    out: list[dict[str, Any]] = []
    for i, e in enumerate(edits_raw):
        if not isinstance(e, dict):
            continue
        row = dict(e)
        tid = row.get("target_block_id")
        if tid and not (row.get("old_html") or "").strip() and tid in by_id:
            row["old_html"] = by_id[tid]
        out.append(row)
    return out
