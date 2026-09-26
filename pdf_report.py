"""PDF report builder — original layout (page-1 summary + sector tables)
with each sector's 1-day sector return shown in its header band."""
from __future__ import annotations

import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph,
                                SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from wishlist_config import (IST, WISHLIST_SECTORS, validate_stock_data,
                             dip_label, sector_metrics)

# ═══════════════════════════════════════════════════════════════════════════════
# LAYER 6 — PDF REPORT (single document, easy to read and share)
# ═══════════════════════════════════════════════════════════════════════════════

# Light print-friendly palette.
PDF_BG_HEADER  = colors.HexColor("#1F2937")
PDF_BG_ZEBRA  = colors.HexColor("#F1F5F9")
PDF_TEXT       = colors.HexColor("#111827")
PDF_TEXT_SUB   = colors.HexColor("#6B7280")
PDF_GREEN      = colors.HexColor("#15803D")
PDF_YELLOW     = colors.HexColor("#B45309")
PDF_ORANGE     = colors.HexColor("#EA580C")
PDF_RED        = colors.HexColor("#DC2626")
PDF_GOLD       = colors.HexColor("#A16207")

# NOTE: column widths must sum to <= 559 (A4 595.28 - 2x18 margins).
# Current total: 558.
COLS = [
    ("STOCK",        118, TA_LEFT),
    ("PRICE (Rs.)",   60, TA_RIGHT),
    ("DAY CHG",       54, TA_RIGHT),
    ("52W HIGH",      60, TA_RIGHT),
    ("% FROM HIGH",   80, TA_RIGHT),
    ("52W LOW",       60, TA_RIGHT),
    ("DAY H/L",       60, TA_RIGHT),
    ("FLAG",          66, TA_RIGHT),
]

_ss = {
    "title":  ParagraphStyle("t",  fontName="Helvetica-Bold", fontSize=20,
                             leading=24, spaceAfter=6,
                             textColor=PDF_TEXT, alignment=TA_CENTER),
    "sub":    ParagraphStyle("s",  fontName="Helvetica", fontSize=10,
                             textColor=PDF_TEXT_SUB, alignment=TA_CENTER),
    "sect":   ParagraphStyle("se", fontName="Helvetica-Bold", fontSize=11,
                             textColor=colors.white),
    "cell":   ParagraphStyle("c",  fontName="Helvetica", fontSize=9,
                             textColor=PDF_TEXT),
    "cellb":  ParagraphStyle("cb", fontName="Helvetica-Bold", fontSize=9,
                             textColor=PDF_TEXT),
    "small":  ParagraphStyle("sm", fontName="Helvetica", fontSize=7,
                             textColor=PDF_TEXT_SUB),
    "smallb": ParagraphStyle("smb", fontName="Helvetica-Bold", fontSize=7,
                             textColor=PDF_TEXT_SUB),
    "cellr":  ParagraphStyle("cr", fontName="Helvetica", fontSize=9,
                             textColor=PDF_TEXT, alignment=TA_RIGHT),
    "cellrb": ParagraphStyle("crb", fontName="Helvetica-Bold", fontSize=9,
                             textColor=PDF_TEXT, alignment=TA_RIGHT),
}


def _dip_color(pct: float):
    a = abs(pct)
    if a >= 15: return PDF_RED
    if a >= 10: return PDF_ORANGE
    if a >= 5:  return PDF_YELLOW
    return PDF_GREEN


def _rgb(t) -> colors.Color:
    return colors.Color(t[0] / 255, t[1] / 255, t[2] / 255)


def _summary_section(quotes: dict) -> list:
    """Data-health + dip distribution + 52W flag summary blocks."""
    valid  = {s: q for s, q in quotes.items() if validate_stock_data(q)}
    cached = [s for s, q in valid.items() if q.get("source") == "cache"]
    failed = [s for s, q in quotes.items() if not validate_stock_data(q)]
    new_hi = [s for s, q in valid.items() if q.get("new_52w_high")]
    new_lo = [s for s, q in valid.items() if q.get("new_52w_low")]

    bands = [
        ("NEAR PEAK  (< 5% from high)", lambda p: abs(p) < 5,   PDF_GREEN),
        ("MINOR DIP  (5–9%)",          lambda p: 5 <= abs(p) < 10, PDF_YELLOW),
        ("MEDIUM DIP (10–14%)",        lambda p: 10 <= abs(p) < 15, PDF_ORANGE),
        ("DEEP DIP   (15–19%)",        lambda p: 15 <= abs(p) < 20, PDF_RED),
        ("CRASH ZONE (20%+)",          lambda p: abs(p) >= 20, PDF_RED),
    ]

    rows: list = [["DIP BAND", "#", "STOCKS"]]
    styles = [
        ("BACKGROUND", (0, 0), (-1, 0), PDF_BG_HEADER),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, 0), 8),
        ("INNERGRID",  (0, 0), (-1, -1), 0.4, colors.white),
        ("BOX",        (0, 0), (-1, -1), 0.6, PDF_BG_HEADER),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for i, (label, match, colr) in enumerate(bands):
        n = sum(1 for q in valid.values() if match(q["pct_from_high"]))
        syms = ", ".join(sorted(s for s, q in valid.items()
                                if match(q["pct_from_high"]))) or "—"
        syms_par = Paragraph(syms, ParagraphStyle(
            "sy", fontName="Helvetica", fontSize=7.5, textColor=PDF_TEXT))
        rows.append([label, str(n), syms_par])
        styles.append(("TEXTCOLOR", (0, i + 1), (0, i + 1), colr))
        styles.append(("FONTNAME",  (1, i + 1), (1, i + 1), "Helvetica-Bold"))
        styles.append(("FONTSIZE", (0, i + 1), (-1, i + 1), 7.5))

    health = (f"Live: {len(valid) - len(cached)}/{len(quotes)}"
              + (f"  •  Cached: {len(cached)}" if cached else "")
              + (f"  •  Unavailable: {len(failed)}" if failed else ""))
    out = [Paragraph(health, _ss["sub"]), Spacer(1, 6)]

    if new_hi or new_lo:
        flags = []
        if new_hi:
            flags.append("NEW 52W HIGH: " + ", ".join(sorted(new_hi)))
        if new_lo:
            flags.append("NEW 52W LOW: " + ", ".join(sorted(new_lo)))
        out.append(Paragraph("  |  ".join(flags), ParagraphStyle(
            "fl", fontName="Helvetica-Bold", fontSize=8.5, alignment=TA_CENTER,
            textColor=PDF_GOLD if new_hi else PDF_RED)))
        out.append(Spacer(1, 6))

    tbl = Table(rows, colWidths=[140, 28, 391])
    tbl.setStyle(TableStyle(styles))
    out += [tbl, Spacer(1, 14)]
    return out


def _sector_section(sec: dict, quotes: dict) -> list:
    """One sector: colored header band (with 1-day sector return) + stock table."""
    accent = _rgb(sec["color"])

    m = sector_metrics(sec, quotes)
    if m:
        right_txt = (f"1D RETURN {m['avg_day']:+.2f}%  •  "
                     f"{m['n']} stock" + ("s" if m["n"] > 1 else ""))
    else:
        right_txt = f"{len(sec['stocks'])} stock"
        if len(sec["stocks"]) > 1:
            right_txt += "s"
    head = Table([[sec["sector"], right_txt]],
                 colWidths=[390, 168])
    head.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, -1), accent),
        ("TEXTCOLOR",   (0, 0), (-1, -1), colors.white),
        ("FONTNAME",    (0, 0), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE",    (0, 0), (0, 0), 10.5),
        ("FONTSIZE",    (1, 0), (1, 0), 8),
        ("ALIGN",       (1, 0), (1, 0), "RIGHT"),
        ("TOPPADDING",  (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))

    data = [[Paragraph(c, ParagraphStyle(
                "h", fontName="Helvetica-Bold", fontSize=7.5,
                textColor=colors.white)) for c, _, _ in COLS]]
    row_colors: list[tuple] = []

    for i, stk in enumerate(sec["stocks"]):
        sym, name, note = stk["symbol"], stk["name"], stk.get("note", "")
        q = quotes.get(sym, {})

        if not validate_stock_data(q):
            src = q.get("source", "error")
            label = "CACHED DATA" if src == "cache" else "DATA UNAVAILABLE"
            colr = PDF_YELLOW if src == "cache" else PDF_RED
            st = ParagraphStyle("e", fontName="Helvetica-Bold", fontSize=8,
                                textColor=colr)
            row = ([Paragraph(f"{sym} — {label}", st)] +
                  [Paragraph("—", _ss["cellr"]) for _ in COLS[1:]])
            row_colors.append((i + 1, colr))
        else:
            pfh = q["pct_from_high"]
            dc  = _dip_color(pfh)
            stock_html = (f'<font name="Helvetica-Bold" size="9">{sym}</font>'
                         f'<br/><font size="7" color="#6B7280">{name}</font>')
            if note:
                ncol = "#DC2626" if note == "EXITING" else "#B45309"
                stock_html += (f'<br/><font name="Helvetica-Bold" size="6.5" '
                               f'color="{ncol}">[{note.upper()}]</font>')

            dip_style = ParagraphStyle(
                "d", fontName="Helvetica-Bold", fontSize=9, alignment=TA_RIGHT,
                textColor=dc)
            pct_html = (f"{pfh:+.2f}%<br/>"
                        f'<font name="Helvetica" size="6.5" color="#6B7280">'
                        f'{dip_label(pfh)}</font>')

            if q.get("source") == "cache":
                pct_html += ('<br/><font size="6.5" color="#B45309">'
                             '[CACHED]</font>')

            pc = q["p_change"]
            day_style = ParagraphStyle(
                "g", fontName="Helvetica-Bold", fontSize=9, alignment=TA_RIGHT,
                textColor=PDF_GREEN if pc > 0 else
                          (PDF_RED if pc < 0 else PDF_TEXT_SUB))

            flag = ""
            if q.get("new_52w_high"):
                flag = "NEW 52W HIGH"
            elif q.get("new_52w_low"):
                flag = "NEW 52W LOW"

            row = [
                Paragraph(stock_html, _ss["cell"]),
                Paragraph(f"{q['last_price']:,.2f}", _ss["cellrb"]),
                Paragraph(f"{pc:+.2f}%", day_style),
                Paragraph(f"{q['high_52w']:,.2f}", _ss["cellr"]),
                Paragraph(pct_html, dip_style),
                Paragraph(f"{q['low_52w']:,.2f}", _ss["cellr"]),
                Paragraph(f"H {q['day_high']:,.0f}<br/>L {q['day_low']:,.0f}",
                          _ss["cellr"]),
                Paragraph(flag, ParagraphStyle(
                    "f", fontName="Helvetica-Bold", fontSize=7, alignment=TA_RIGHT,
                    textColor=PDF_GOLD if q.get("new_52w_high") else
                              (PDF_RED if q.get("new_52w_low") else PDF_TEXT_SUB))),
            ]
            row_colors.append((i + 1, _dip_color(pfh)))

        data.append(row)

    tbl = Table(data, colWidths=[w for _, w, _ in COLS], repeatRows=1)
    style = [
        ("BACKGROUND",    (0, 0), (-1, 0), PDF_BG_HEADER),
        ("INNERGRID",     (0, 0), (-1, -1), 0.4, colors.HexColor("#E5E7EB")),
        ("BOX",           (0, 0), (-1, -1), 0.6, colors.HexColor("#9CA3AF")),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
    ]
    for r in range(2, len(data), 2):
        style.append(("BACKGROUND", (0, r), (-1, r), PDF_BG_ZEBRA))
    # subtle left accent stripe colored by dip severity
    for row_idx, colr in row_colors:
        style.append(("LINEBEFORE", (0, row_idx), (0, row_idx), 2.2, colr))
    tbl.setStyle(TableStyle(style))

    return [KeepTogether([head, Spacer(1, 2), tbl]), Spacer(1, 12)]


def build_pdf_report(quotes: dict) -> bytes:
    """Build the full multi-page PDF report. Returns PDF bytes."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18, rightMargin=18, topMargin=36, bottomMargin=34,
        title="Wishlist Stock Tracker",
        author="Wishlist Daily Tracker",
    )
    now = datetime.now(IST)
    date_str = now.strftime("%d %b %Y  |  %I:%M %p IST")

    def _footer(canvas, _doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(PDF_TEXT_SUB)
        canvas.drawString(18, 22, "Data via Yahoo Finance (NSE). "
                                  "Not financial advice. Educational only.")
        canvas.drawRightString(A4[0] - 18, 22, f"Page {canvas.getPageNumber()}")
        canvas.restoreState()

    def _top_header(canvas, _doc):
        # Running header on continuation pages only (page 1 has the title).
        if canvas.getPageNumber() == 1:
            return
        canvas.saveState()
        canvas.setFont("Helvetica-Bold", 7)
        canvas.setFillColor(PDF_TEXT_SUB)
        canvas.drawCentredString(A4[0] / 2, A4[1] - 16,
                                  f"Wishlist Stock Tracker — {date_str}")
        canvas.restoreState()

    def _page_decor(canvas, doc_):
        _top_header(canvas, doc_)
        _footer(canvas, doc_)

    story = [
        Paragraph("WISHLIST STOCK TRACKER", _ss["title"]),
        Paragraph(f"Sector-wise 52W High/Low analysis  •  Daily dip monitor  "
                   f"•  {date_str}", _ss["sub"]),
        Spacer(1, 12),
    ]
    story += _summary_section(quotes)
    story.append(PageBreak())
    for sec in WISHLIST_SECTORS:
        story += _sector_section(sec, quotes)

    doc.build(story, onFirstPage=_page_decor, onLaterPages=_page_decor)
    buf.seek(0)
    return buf.read()
