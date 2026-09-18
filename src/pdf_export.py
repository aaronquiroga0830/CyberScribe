"""Render report HTML to PDF (xhtml2pdf)."""
from __future__ import annotations

from io import BytesIO

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
