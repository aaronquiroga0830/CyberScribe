"""
Block-aware document representation for localized edit proposals.
Parse report HTML into blocks (with stable IDs); serialize back; apply accepted edits.
Used for the collaborative editor flow: LLM proposes edits per block, we apply only accepted ones.
"""
import re
from dataclasses import dataclass
from typing import Any


@dataclass
class DocumentBlock:
    """One block in a report document (heading, paragraph, list)."""
    block_id: str
    section_id: str
    block_type: str  # heading | paragraph | bullet_list | numbered_list
    html: str
    order: int


# Match block-level elements: h1-h6, p, ul, ol (with content to closing tag)
_BLOCK_TAG_PATTERN = re.compile(
    r"<(h[1-6]|p|ul|ol)[^>]*>[\s\S]*?</\1>",
    re.IGNORECASE,
)


def _infer_block_type(tag: str, html: str) -> str:
    tag_lower = tag.lower()
    if tag_lower.startswith("h"):
        return "heading"
    if tag_lower == "p":
        return "paragraph"
    if tag_lower == "ul":
        return "bullet_list"
    if tag_lower == "ol":
        return "numbered_list"
    return "paragraph"


def _section_from_heading(html: str) -> str:
    """Extract section label from a heading block for section_id."""
    m = re.search(r"<h[1-6][^>]*>([\s\S]*?)</h[1-6]>", html, re.IGNORECASE)
    if m:
        text = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        return text[:80] if text else ""
    return ""


def parse_html_to_blocks(html: str) -> list[DocumentBlock]:
    """
    Parse report HTML into a list of blocks with stable block_id and section_id.
    Block IDs are section_N_block_M so they are stable across parses when structure is unchanged.
    """
    if not (html or "").strip():
        return []
    blocks: list[DocumentBlock] = []
    current_section = ""
    section_index = -1
    block_index_in_section = 0
    for i, m in enumerate(_BLOCK_TAG_PATTERN.finditer(html)):
        full_match = m.group(0)
        tag = m.group(1).lower()
        block_type = _infer_block_type(tag, full_match)
        if block_type == "heading":
            current_section = _section_from_heading(full_match) or f"section_{section_index + 1}"
            section_index += 1
            block_index_in_section = 0
        else:
            block_index_in_section += 1
        block_id = f"section_{section_index}_block_{block_index_in_section}"
        section_id = current_section or f"section_{section_index}"
        blocks.append(
            DocumentBlock(
                block_id=block_id,
                section_id=section_id,
                block_type=block_type,
                html=full_match,
                order=len(blocks),
            )
        )
    return blocks


def blocks_to_html(blocks: list[DocumentBlock]) -> str:
    """Serialize blocks back to HTML (with newlines between for readability)."""
    return "\n".join(b.html for b in blocks)


def apply_edits_to_blocks(
    blocks: list[DocumentBlock],
    edits: list[dict[str, Any]],
) -> list[DocumentBlock]:
    """
    Apply a list of accepted edits to the block list.
    Each edit has: edit_id, target_block_id, operation, old_html, new_html, status.
    Only edits with status accepted are applied.
    Operations: replace | insert_before | insert_after | delete | noop.
    Returns a new list of blocks (does not mutate input).
    """
    accepted = [e for e in edits if (e.get("status") or "").lower() == "accepted"]
    by_target: dict[str, dict[str, Any]] = {}
    for e in accepted:
        tid = e.get("target_block_id")
        if tid:
            by_target[tid] = e

    # When document is empty but we have an accepted replace (e.g. fallback full-draft), emit one block.
    if not blocks and accepted:
        replace_edits = [e for e in accepted if ((e.get("operation") or "").lower() == "replace") and (e.get("new_html") or "").strip()]
        if replace_edits:
            new_html = (replace_edits[0].get("new_html") or "").strip()
            return [DocumentBlock(block_id="section_0_block_0", section_id="section_0", block_type="paragraph", html=new_html, order=0)]
    if not blocks:
        return []

    result: list[DocumentBlock] = []
    for block in blocks:
        ed = by_target.get(block.block_id)
        op = (ed.get("operation") or "noop").lower() if ed else "noop"

        if op == "delete":
            continue
        if op == "replace" and ed and "new_html" in ed:
            result.append(
                DocumentBlock(
                    block_id=block.block_id,
                    section_id=block.section_id,
                    block_type=block.block_type,
                    html=ed["new_html"],
                    order=len(result),
                )
            )
            continue
        if op == "insert_before" and ed and "new_html" in ed:
            result.append(
                DocumentBlock(
                    block_id=ed.get("edit_id", f"insert_{len(result)}"),
                    section_id=block.section_id,
                    block_type="paragraph",
                    html=ed["new_html"],
                    order=len(result),
                )
            )
        result.append(
            DocumentBlock(
                block_id=block.block_id,
                section_id=block.section_id,
                block_type=block.block_type,
                html=block.html,
                order=len(result),
            )
        )
        if op == "insert_after" and ed and "new_html" in ed:
            result.append(
                DocumentBlock(
                    block_id=ed.get("edit_id", f"insert_{len(result)}"),
                    section_id=block.section_id,
                    block_type="paragraph",
                    html=ed["new_html"],
                    order=len(result),
                )
            )
    return result


PENDING_HIGHLIGHT_START = '<span class="pending-edit-highlight" style="background-color: rgba(255, 193, 7, 0.28); border-radius: 2px; padding: 0 2px;">'
PENDING_HIGHLIGHT_END = "</span>"


def apply_edits_to_blocks_for_preview(
    blocks: list[DocumentBlock],
    edits: list[dict[str, Any]],
) -> list[DocumentBlock]:
    """
    Like apply_edits_to_blocks but treats all edits as applied and wraps edit-sourced
    content in a span so the frontend can show highlights in Quill.
    """
    by_target: dict[str, dict[str, Any]] = {}
    for e in edits:
        tid = e.get("target_block_id")
        if tid:
            by_target[tid] = e

    # When document is empty but we have a replace (e.g. fallback full-draft), show one block with highlight.
    if not blocks and edits:
        replace_edits = [e for e in edits if ((e.get("operation") or "").lower() == "replace") and (e.get("new_html") or "").strip()]
        if replace_edits:
            new_html = (replace_edits[0].get("new_html") or "").strip()
            return [DocumentBlock(block_id="section_0_block_0", section_id="section_0", block_type="paragraph", html=PENDING_HIGHLIGHT_START + new_html + PENDING_HIGHLIGHT_END, order=0)]

    result: list[DocumentBlock] = []
    for block in blocks:
        ed = by_target.get(block.block_id)
        op = (ed.get("operation") or "noop").lower() if ed else "noop"

        if op == "delete":
            continue
        if op == "replace" and ed and "new_html" in ed:
            result.append(
                DocumentBlock(
                    block_id=block.block_id,
                    section_id=block.section_id,
                    block_type=block.block_type,
                    html=PENDING_HIGHLIGHT_START + (ed["new_html"] or "") + PENDING_HIGHLIGHT_END,
                    order=len(result),
                )
            )
            continue
        if op == "insert_before" and ed and "new_html" in ed:
            result.append(
                DocumentBlock(
                    block_id=ed.get("edit_id", f"insert_{len(result)}"),
                    section_id=block.section_id,
                    block_type="paragraph",
                    html=PENDING_HIGHLIGHT_START + (ed["new_html"] or "") + PENDING_HIGHLIGHT_END,
                    order=len(result),
                )
            )
        result.append(
            DocumentBlock(
                block_id=block.block_id,
                section_id=block.section_id,
                block_type=block.block_type,
                html=block.html,
                order=len(result),
            )
        )
        if op == "insert_after" and ed and "new_html" in ed:
            result.append(
                DocumentBlock(
                    block_id=ed.get("edit_id", f"insert_{len(result)}"),
                    section_id=block.section_id,
                    block_type="paragraph",
                    html=PENDING_HIGHLIGHT_START + (ed["new_html"] or "") + PENDING_HIGHLIGHT_END,
                    order=len(result),
                )
            )
    return result
