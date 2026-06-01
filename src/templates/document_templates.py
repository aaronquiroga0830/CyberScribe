"""
Document structure templates per report type.
Pre-populated when a mission is created so drafts show headings and placeholders
instead of a blank page. Patch updates apply on top of these templates.

Phase 2 §8.4: each logical section is wrapped in
`<section class="report-section" data-section-key="…" data-section-policy="…">`
so the editor (Tiptap) and downstream tooling share explicit section identity
with `report_section_definitions` / SECTION_DEFINITION_SEED.
"""
from __future__ import annotations

import html
from typing import Dict

from src.section_definitions import SECTION_DEFINITION_SEED

_PLACEHOLDER = "[To be filled from mission data]"


def build_structured_template_html(report_type: str) -> str:
    """HTML document from seeded section definitions (sort_order)."""
    rows = [r for r in SECTION_DEFINITION_SEED if r[0] == report_type]
    rows.sort(key=lambda r: r[3])
    parts: list[str] = []
    for _rt, section_key, display_title, _order, policy in rows:
        esc_key = html.escape(section_key, quote=True)
        esc_policy = html.escape(policy, quote=True)
        if section_key == "title":
            inner = f"<h1>{html.escape(display_title)}</h1>"
        elif section_key == "body_intro":
            inner = f"<p>{html.escape(_PLACEHOLDER)}</p>"
        else:
            inner = (
                f"<h2>{html.escape(display_title)}</h2>"
                f"<p>{html.escape(_PLACEHOLDER)}</p>"
            )
        parts.append(
            f'<section class="report-section" data-section-key="{esc_key}" '
            f'data-section-policy="{esc_policy}">{inner}</section>'
        )
    return "\n".join(parts)


def get_document_template(report_type: str) -> str:
    """Return the document template string for the given report type."""
    return DOCUMENT_TEMPLATES.get(report_type, "")


DOCUMENT_TEMPLATES: Dict[str, str] = {
    "rmp": build_structured_template_html("rmp"),
    "timeline": build_structured_template_html("timeline"),
    "aar": build_structured_template_html("aar"),
    "sitrep": build_structured_template_html("sitrep"),
}
