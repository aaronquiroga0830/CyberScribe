"""
Merge LLM-generated content into the current draft (template) so that the
skeleton structure is preserved and only filled or revised sections are updated.
"""
import re

PLACEHOLDER = "[To be filled from mission data]"


def _split_blocks(text: str) -> list[str]:
    """Split text into blocks by double newlines or by HTML block boundaries."""
    if not (text or "").strip():
        return []
    # Normalize and split by double newline
    normalized = (text or "").replace("\r\n", "\n").strip()
    blocks = re.split(r"\n\s*\n", normalized)
    return [b.strip() for b in blocks if b.strip()]


def _is_filled(block: str) -> bool:
    """True if the block has substantive content (not empty or placeholder)."""
    if not block or len(block) < 3:
        return False
    stripped = block.strip()
    if stripped.lower() == PLACEHOLDER.lower():
        return False
    if PLACEHOLDER.lower() in stripped.lower() and len(stripped) < 100:
        return False
    return True


def merge_llm_into_draft(current_draft: str, llm_output: str) -> str:
    """
    Merge LLM output into the current draft (template). Preserves the template
    structure; replaces only blocks that the LLM has filled or revised.
    If merge is not possible or LLM output is empty, returns current_draft.
    """
    if not (llm_output or "").strip():
        return current_draft or ""
    draft_blocks = _split_blocks(current_draft or "")
    llm_blocks = _split_blocks(llm_output or "")
    if not draft_blocks:
        return llm_output.strip()
    if not llm_blocks:
        return current_draft or ""

    merged: list[str] = []
    n = max(len(draft_blocks), len(llm_blocks))
    for i in range(n):
        draft_block = draft_blocks[i] if i < len(draft_blocks) else ""
        llm_block = llm_blocks[i] if i < len(llm_blocks) else ""
        if _is_filled(llm_block):
            merged.append(llm_block)
        else:
            merged.append(draft_block if draft_block else llm_block)

    return "\n\n".join(merged)
