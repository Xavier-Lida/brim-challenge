"""On-demand PDF rendering for expense reports (Feature 4).

Flat text layout matching the frontend reference PDF: one line per metadata field,
``$``-prefixed amounts, typographic dashes in the body, and a space-aligned
transactions block (no bordered table). Uses bundled DejaVu fonts for Unicode.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fpdf import FPDF

ROOT = Path(__file__).resolve().parent.parent
FONTS_DIR = ROOT / "fonts"
_DEJAVU_REGULAR = FONTS_DIR / "DejaVuSans.ttf"
_DEJAVU_BOLD = FONTS_DIR / "DejaVuSans-Bold.ttf"
_DEJAVU_MONO = FONTS_DIR / "DejaVuSansMono.ttf"

_EN_DASH = "\u2013"  # period separator (reference: 2025-09-09 – 2025-09-21)

# Filename-only: fold punctuation so Content-Disposition stays latin-1-safe.
_FILENAME_PUNCT = {
    "\u2014": "-",
    "\u2013": "-",
    "\u2026": "...",
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
}

# Transaction columns (monospace); tuned to the reference sample rows.
_TX_DATE_W = 11
_TX_MERCH_W = 29
_TX_CAT_W = 15
_TX_CITY_W = 16
_TX_AMT_W = 10


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\r", " ").replace("\n", " ").strip()


def _sanitize_filename(value: Any) -> str:
    text = _text(value)
    for src, dst in _FILENAME_PUNCT.items():
        text = text.replace(src, dst)
    return text.encode("latin-1", "replace").decode("latin-1")


def _fmt_money(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return _text(value)


def _trunc(value: Any, width: int, *, ellipsis: str = "\u2026") -> str:
    s = _text(value)
    if len(s) <= width:
        return s
    if width <= 1:
        return s[:width]
    return s[: width - 1] + ellipsis


def _register_fonts(pdf: FPDF) -> None:
    if not _DEJAVU_REGULAR.is_file():
        raise FileNotFoundError(
            f"Missing font {_DEJAVU_REGULAR}. Run scripts/fetch_fonts.py or add DejaVu TTFs under fonts/."
        )
    pdf.add_font("DejaVu", "", str(_DEJAVU_REGULAR))
    if _DEJAVU_BOLD.is_file():
        pdf.add_font("DejaVu", "B", str(_DEJAVU_BOLD))
    if _DEJAVU_MONO.is_file():
        pdf.add_font("DejaVuMono", "", str(_DEJAVU_MONO))


def report_pdf_filename(report: dict) -> str:
    title = _sanitize_filename(report.get("title") or report.get("id") or "expense-report")
    safe = re.sub(r'[\\/:*?"<>|]+', "_", title).strip().strip(".")
    safe = re.sub(r"\s+", " ", safe) or "expense-report"
    return f"{safe}.pdf"


def _transaction_header(currency: str) -> str:
    return f"Date Merchant Category City Amount ({currency})"


def _transaction_row(t: dict) -> str:
    date = _trunc(t.get("date"), _TX_DATE_W).ljust(_TX_DATE_W)
    merchant = _trunc(t.get("merchant_name"), _TX_MERCH_W).ljust(_TX_MERCH_W)
    category = _trunc(t.get("merchant_category"), _TX_CAT_W).ljust(_TX_CAT_W)
    city = _trunc(t.get("city"), _TX_CITY_W).ljust(_TX_CITY_W)
    amount = f"${_fmt_money(t.get('amount'))}"
    amount = amount.rjust(_TX_AMT_W)
    return f"{date}{merchant}{category}{city}{amount}"


def _write_line(pdf: FPDF, line: str, *, line_h: float = 5.5) -> None:
    pdf.set_x(pdf.l_margin)
    usable = pdf.w - pdf.l_margin - pdf.r_margin
    if not line:
        pdf.ln(line_h)
        return
    if pdf.get_string_width(line) <= usable:
        pdf.cell(0, line_h, line, new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.multi_cell(usable, line_h, line, new_x="LMARGIN", new_y="NEXT")


def render_report_pdf(report: dict) -> bytes:
    currency = _text(report.get("currency")) or "CAD"
    date_from = _text(report.get("date_from"))
    date_to = _text(report.get("date_to"))
    period = f"{date_from} {_EN_DASH} {date_to}" if date_from and date_to else date_from or date_to

    metadata_lines = [
        "Expense Report",
        _text(report.get("title")),
        f"Period {period}",
        f"Total amount ${_fmt_money(report.get('total_amount'))} {currency}",
        f"Status {_text(report.get('status'))}",
        f"Employee {_text(report.get('employee_name'))}",
        f"Department {_text(report.get('department_name'))}",
        f"AI recommendation {_text(report.get('ai_recommendation'))}",
        f"AI reasoning {_text(report.get('ai_reasoning'))}",
    ]

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    _register_fonts(pdf)
    pdf.add_page()

    pdf.set_font("DejaVu", "", 11)
    for line in metadata_lines:
        _write_line(pdf, line)

    pdf.ln(3)
    _write_line(pdf, "Transactions")

    transactions = report.get("transactions") or []
    pdf.set_font("DejaVuMono", "", 9)
    _write_line(pdf, _transaction_header(currency), line_h=5)
    for t in transactions:
        _write_line(pdf, _transaction_row(t), line_h=5)

    return bytes(pdf.output())
