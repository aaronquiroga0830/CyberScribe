"""Render report HTML to PDF (xhtml2pdf)."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

from xhtml2pdf import pisa


def html_to_pdf_bytes(html: str, *, base_url: str | None = None) -> bytes:
    buf = BytesIO()
    status = pisa.CreatePDF(
        html,
        dest=buf,
        path=base_url or None,
    )
    if status.err:
        raise ValueError("PDF generation failed")
    return buf.getvalue()


def write_html_to_pdf_file(html: str, out_path: Path, *, base_url: str | None = None) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    data = html_to_pdf_bytes(html, base_url=base_url)
    out_path.write_bytes(data)
    return out_path
