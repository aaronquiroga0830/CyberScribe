"""
Clean retrieved context before sending to the LLM to avoid junk (PDF signatures,
hex blobs, UUIDs, base64) that causes repetition and hallucination.
"""
import re


# Lines that are mostly hex/encoding/signature noise get dropped
HEX_LINE = re.compile(r"^[\s=0-9A-Fa-f_\-]{30,}$")  # long hex-like lines
UUID_OR_SIG = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(_envelope|&signature|=|$)", re.I)
SIGNATURE_ENVELOPE = re.compile(r"envelope\s*=\s*false|signature\s*=", re.I)


def _is_junk_line(line: str) -> bool:
    s = line.strip()
    if len(s) < 20:
        return False
    # Long line that's mostly hex/equals/underscores
    if HEX_LINE.match(s):
        return True
    # Signature/envelope/UUID blobs
    if UUID_OR_SIG.search(s) or SIGNATURE_ENVELOPE.search(s):
        return True
    # Same short pattern repeated many times (e.g. =E9B7A1... repeated)
    if len(s) > 100:
        first_30 = s[:30]
        if s.count(first_30) >= 3:
            return True
    return False


def clean_context_for_llm(context: str) -> str:
    """
    Remove lines that look like encoded/signature/hex junk from retrieved context.
    Keeps substantive narrative so the LLM doesn't copy or repeat garbage.
    """
    if not context or not context.strip():
        return context
    lines = context.split("\n")
    kept = [ln for ln in lines if not _is_junk_line(ln)]
    return "\n".join(kept).strip() or context  # fallback to original if we stripped everything
