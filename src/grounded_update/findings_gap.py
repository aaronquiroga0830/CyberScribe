"""
RMP Findings: detect numbered finding list continuation and validate the next line.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_FINDING_RE = re.compile(
    r"Finding\s+(\d+)\s*:\s*(.+?)\s*\(Risk:\s*(\w+)\)",
    re.I,
)


@dataclass(frozen=True)
class FindingContinuation:
    next_num: int
    target_risk: str
    last_line: str
    existing_findings: tuple[str, ...]


def _parse_all_findings(text: str) -> list[tuple[int, str, str]]:
    out: list[tuple[int, str, str]] = []
    for m in _FINDING_RE.finditer(text or ""):
        try:
            num = int(m.group(1))
        except ValueError:
            continue
        body = (m.group(2) or "").strip()
        risk = (m.group(3) or "").strip()
        if body and risk:
            out.append((num, body, risk))
    return out


def try_parse_finding_continuation(
    before_cursor: str,
    after_cursor: str,
) -> FindingContinuation | None:
    """
    When the cursor sits after Finding N (append to the list), return specs for Finding N+1
    with the same risk level as Finding N.
    """
    findings = _parse_all_findings(before_cursor)
    if not findings:
        return None

    last_num, last_body, last_risk = findings[-1]
    next_num = last_num + 1

    after_findings = _parse_all_findings(after_cursor)
    if any(num >= next_num for num, _, _ in after_findings):
        return None

    after_stripped = (after_cursor or "").strip()
    if after_stripped:
        if re.search(rf"Finding\s+{next_num}\s*:", after_cursor, re.I):
            return None
        if not re.match(r"^(Recommendations|Findings)\b", after_stripped, re.I):
            return None

    existing = tuple(
        f"Finding {n}: {body} (Risk: {risk})." for n, body, risk in findings
    )
    return FindingContinuation(
        next_num=next_num,
        target_risk=last_risk,
        last_line=existing[-1],
        existing_findings=existing,
    )


def build_findings_retrieval_query(next_num: int, target_risk: str) -> str:
    return (
        f"Finding {next_num} {target_risk} risk cyber mission assessment "
        "crew log findings evidence vulnerability"
    )


def build_findings_continuation_prompt(
    action: str,
    cont: FindingContinuation,
    evidence: str,
) -> str:
    risk = cont.target_risk
    num = cont.next_num
    existing_block = "\n".join(f"- {line}" for line in cont.existing_findings)
    return "\n".join(
        [
            f"You are writing the NEXT numbered finding in an RMP Findings section (Finding {num}).",
            "",
            "Grounding rules (mandatory):",
            f"- Output EXACTLY ONE finding line in this format: Finding {num}: <concise description> (Risk: {risk}).",
            f"- The risk level MUST be {risk} (same as the previous finding).",
            "- Use ONLY facts supported by the evidence excerpts below.",
            "- Do NOT repeat or paraphrase any existing finding listed below.",
            "- Do NOT output recommendations, executive summary, section headings, or meta commentary.",
            "- No markdown fences, no bullet lists, no preamble.",
            "",
            "---",
            "",
            "Existing findings (do NOT repeat):",
            existing_block,
            "",
            f"Previous finding (continue after this; match risk {risk}):",
            cont.last_line,
            "",
            "---",
            "",
            "Evidence excerpts:",
            evidence or "(empty — output: "
            f"Finding {num}: TBD — not stated in source material (Risk: {risk}).)",
            "",
            "---",
            "",
            f"Assist action: {action}",
            "",
            f"Respond with that single Finding {num} line only.",
        ]
    )


def validate_finding_suggestion(
    raw: str,
    *,
    next_num: int,
    target_risk: str,
    existing_findings: tuple[str, ...],
) -> tuple[str | None, list[str]]:
    warnings: list[str] = []
    t = (raw or "").strip()
    if not t:
        return None, ["Finding assist returned empty text."]

    line = t.splitlines()[0].strip()
    m = re.match(
        rf"^Finding\s+{next_num}\s*:\s*(.+?)\s*\(Risk:\s*(\w+)\)\.?\s*$",
        line,
        re.I,
    )
    if not m:
        warnings.append(
            f"Line did not match required 'Finding {next_num}: ... (Risk: ...).' format."
        )
        return None, warnings

    got_risk = m.group(2).strip()
    if got_risk.lower() != target_risk.lower():
        warnings.append(
            f"Risk level was {got_risk!r}; expected {target_risk!r} to match the previous finding."
        )
        return None, warnings

    body_lower = m.group(1).strip().lower()
    for existing in existing_findings:
        existing_body = _FINDING_RE.search(existing)
        if existing_body and existing_body.group(2).strip().lower() == body_lower:
            warnings.append("Suggestion repeats an existing finding description.")
            return None, warnings

    if not line.endswith("."):
        line = line + "."
    return line, warnings


def filter_docs_for_findings_gap(docs: list[Any], existing_findings: tuple[str, ...]) -> list[Any]:
    """Prefer chunks that mention risk/finding vocabulary; drop near-duplicates of existing text."""
    existing_lower = " ".join(existing_findings).lower()
    scored: list[tuple[int, Any]] = []
    for d in docs:
        body = (getattr(d, "page_content", None) or str(d)).strip()
        if not body:
            continue
        lower = body.lower()
        score = 0
        if "risk" in lower:
            score += 2
        if "finding" in lower or "vulnerabilit" in lower or "expos" in lower:
            score += 2
        if any(word in lower for word in ("medium", "high", "critical", "low")):
            score += 1
        if body.lower()[:80] in existing_lower:
            score -= 5
        scored.append((score, d))
    scored.sort(key=lambda x: x[0], reverse=True)
    out = [d for s, d in scored if s >= 0][:14]
    return out or docs[:14]
