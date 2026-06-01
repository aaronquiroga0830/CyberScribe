"""
Convert HTML content to a Word document (.docx) with basic formatting.
Supports paragraphs, bold/italic/underline, lists (bulleted and numbered), and page margins.
Used when saving or accepting report content for mission partner deliverables.
"""
import html.parser
import logging
import re
from pathlib import Path
from typing import Optional

from docx import Document
from docx.shared import Inches

logger = logging.getLogger(__name__)

_COMMENT_SPAN_RE = re.compile(
    r'<span\s[^>]*\bdata-report-comment\s*=\s*["\'][^"\']*["\'][^>]*>([\s\S]*?)</span>',
    re.IGNORECASE,
)


def _strip_report_comment_spans_for_docx(html: str) -> str:
    """Remove inline comment highlight wrappers so DOCX matches saved body text."""
    if "data-report-comment" not in html:
        return html
    prev = None
    out = html
    for _ in range(500):
        prev = out
        out = _COMMENT_SPAN_RE.sub(r"\1", out, count=1)
        if out == prev:
            break
    return out


def html_to_docx(
    html_content: str,
    output_path: Path,
    margins: Optional[dict[str, float]] = None,
) -> Path:
    """
    Convert HTML string to .docx and write to output_path.
    margins: optional dict with keys top, right, bottom, left (inches).
    Returns output_path.
    """
    doc = Document()
    if margins:
        sect = doc.sections[0]
        if "top" in margins:
            sect.top_margin = Inches(float(margins["top"]))
        if "right" in margins:
            sect.right_margin = Inches(float(margins["right"]))
        if "bottom" in margins:
            sect.bottom_margin = Inches(float(margins["bottom"]))
        if "left" in margins:
            sect.left_margin = Inches(float(margins["left"]))

    if not (html_content or "").strip():
        doc.add_paragraph("")
        doc.save(str(output_path))
        return output_path

    # Normalize: wrap in a single root if fragment
    text = _strip_report_comment_spans_for_docx((html_content or "").strip())
    if not text.startswith("<"):
        doc.add_paragraph(text)
        doc.save(str(output_path))
        return output_path

    # Use a simple parser to walk blocks and inline formatting
    parser = _HTMLToDocxParser(doc)
    try:
        parser.feed(text)
        parser.close()
    except Exception as e:
        logger.warning("html_to_docx parse fallback: %s", e)
        doc.add_paragraph(text.replace("<", "&lt;").replace(">", "&gt;"))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))
    return output_path


class _HTMLToDocxParser(html.parser.HTMLParser):
    """Parse HTML and add paragraphs/runs to a python-docx Document."""

    def __init__(self, doc: Document):
        super().__init__()
        self.doc = doc
        self._current_para = None
        self._list_level = 0
        self._list_style: Optional[str] = None  # 'ul' | 'ol' | None
        self._run_attrs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "p":
            self._current_para = self.doc.add_paragraph()
            self._list_style = None
        elif tag in ("div", "br"):
            if tag == "br" and self._current_para is not None:
                self._current_para.add_run("\n")
            elif tag == "div":
                self._current_para = self.doc.add_paragraph()
        elif tag in ("strong", "b"):
            self._ensure_para()
            self._run_attrs.append("bold")
        elif tag in ("em", "i"):
            self._ensure_para()
            self._run_attrs.append("italic")
        elif tag == "u":
            self._ensure_para()
            self._run_attrs.append("underline")
        elif tag == "ul":
            self._list_level += 1
            self._list_style = "ul"
            self._current_para = self.doc.add_paragraph()
            self._current_para.style = "List Bullet"
        elif tag == "ol":
            self._list_level += 1
            self._list_style = "ol"
            self._current_para = self.doc.add_paragraph()
            self._current_para.style = "List Number"
        elif tag == "li":
            self._current_para = self.doc.add_paragraph()
            self._current_para.style = "List Bullet" if self._list_style == "ul" else "List Number"
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._list_style = None
            self._current_para = self.doc.add_paragraph()
            lvl = min(int(tag[1]), 9)
            try:
                self._current_para.style = f"Heading {lvl}"
            except (KeyError, ValueError):
                pass

    def handle_endtag(self, tag: str) -> None:
        if tag in ("strong", "b", "em", "i", "u") and self._run_attrs:
            self._run_attrs.pop()
        elif tag in ("ul", "ol"):
            self._list_level = max(0, self._list_level - 1)
            if self._list_level == 0:
                self._list_style = None
        elif tag in ("p", "div", "h1", "h2", "h3", "h4", "h5", "h6"):
            self._current_para = None

    def _ensure_para(self):
        if self._current_para is None:
            self._current_para = self.doc.add_paragraph()
        return self._current_para

    def handle_data(self, data: str) -> None:
        if not data:
            return
        self._ensure_para()
        run = self._current_para.add_run(data)
        for a in self._run_attrs:
            if a == "bold":
                run.bold = True
            elif a == "italic":
                run.italic = True
            elif a == "underline":
                run.underline = True
