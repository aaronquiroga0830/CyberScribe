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


def _blank_line_html() -> str:
    """Single empty line in Tiptap (bare <p></p> collapses on load)."""
    return '<p class="template-blank-line"><br></p>'


def _placeholder_paragraph() -> str:
    """Blank line, placeholder, blank line."""
    ph = f'<p class="template-placeholder">{html.escape(_PLACEHOLDER)}</p>'
    return f"{_blank_line_html()}{ph}{_blank_line_html()}"


def _sectioned_placeholder(display_title: str) -> str:
    """Heading, rule, then spaced placeholder (heading always above placeholder)."""
    return (
        f"<h2>{html.escape(display_title)}</h2>"
        f"{_placeholder_paragraph()}"
    )


def build_structured_template_html(report_type: str) -> str:
    """HTML document from seeded section definitions (sort_order)."""
    rows = [r for r in SECTION_DEFINITION_SEED if r[0] == report_type]
    rows.sort(key=lambda r: r[3])
    parts: list[str] = []
    for _rt, section_key, display_title, _order, policy in rows:
        if report_type == "rmp" and section_key == "body_intro":
            continue
        esc_key = html.escape(section_key, quote=True)
        esc_policy = html.escape(policy, quote=True)
        if section_key == "title":
            inner = f"<h1>{html.escape(display_title)}</h1>"
        elif section_key == "body_intro":
            inner = _placeholder_paragraph()
        else:
            inner = _sectioned_placeholder(display_title)
        parts.append(
            f'<section class="report-section" data-section-key="{esc_key}" '
            f'data-section-policy="{esc_policy}">{inner}</section>'
        )
    return "\n".join(parts)


def get_document_template(report_type: str) -> str:
    """Return the document template string for the given report type."""
    if report_type in DOCUMENT_TEMPLATES:
        return build_structured_template_html(report_type)
    return ""


DOCUMENT_TEMPLATES: Dict[str, str] = {
    "rmp": build_structured_template_html("rmp"),
    "timeline": build_structured_template_html("timeline"),
    "aar": build_structured_template_html("aar"),
    "sitrep": build_structured_template_html("sitrep"),
}
