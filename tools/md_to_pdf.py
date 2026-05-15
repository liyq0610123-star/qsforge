"""
Minimal, good-enough Markdown → PDF converter for QSForge manuals.

Scope — we only support the subset of Markdown our docs actually use:
  * H1 / H2 / H3 headings
  * Paragraphs with **bold**, *italic*, `code`, [link](url)
  * Unordered lists (-, *) and ordered lists (1.)
  * GFM-style tables (pipe separator, header + --- row)
  * Horizontal rules (---)
  * Blockquotes (>)
  * Fenced code blocks (```)

CJK support: we pick the first available Windows font that contains
Chinese glyphs (YaHei → YaHei Bold → SimHei → SimSun) and fall back to
Helvetica when nothing Chinese is available. Output stays compact so a
150-line manual produces a 3-4 page PDF.

Usage:
    python tools/md_to_pdf.py <input.md> <output.pdf> [--title "Display title"]
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


# ── Brand palette (matches the in-app UI) ──────────────────────────────────
NAVY     = colors.HexColor("#0F172A")
INK      = colors.HexColor("#1E293B")
MUTED    = colors.HexColor("#64748B")
ACCENT   = colors.HexColor("#3B82F6")
BG_SOFT  = colors.HexColor("#F1F5F9")
BG_CODE  = colors.HexColor("#F8FAFC")
HAIRLINE = colors.HexColor("#CBD5E1")


# ── Font discovery ──────────────────────────────────────────────────────────
# Prefer fonts bundled inside the QSForge install. This guarantees Chinese
# text renders on any Windows machine — including English Windows where
# YaHei / SimHei / SimSun are not installed.
_BUNDLED_FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

_CJK_FONT_CANDIDATES = [
    (_BUNDLED_FONT_DIR / "NotoSansCJKsc-Regular.otf",
     _BUNDLED_FONT_DIR / "NotoSansCJKsc-Bold.otf"),
    (Path(r"C:\Windows\Fonts\msyh.ttc"),
     Path(r"C:\Windows\Fonts\msyhbd.ttc")),
    (Path(r"C:\Windows\Fonts\simhei.ttf"),
     Path(r"C:\Windows\Fonts\simhei.ttf")),
    (Path(r"C:\Windows\Fonts\simsun.ttc"),
     Path(r"C:\Windows\Fonts\simsun.ttc")),
]

FONT_REGULAR = "Helvetica"
FONT_BOLD = "Helvetica-Bold"


def _register_cjk_fonts():
    """Register a CJK-capable font pair with reportlab.

    Returns (regular_name, bold_name). Falls back to Helvetica if no CJK
    font is available so reportlab still has *some* font to reach for.
    """
    for regular, bold in _CJK_FONT_CANDIDATES:
        if regular.exists() and bold.exists():
            try:
                pdfmetrics.registerFont(TTFont("QSForgeCJK", str(regular)))
                pdfmetrics.registerFont(TTFont("QSForgeCJK-Bold", str(bold)))
                return "QSForgeCJK", "QSForgeCJK-Bold"
            except Exception:
                continue
    return "Helvetica", "Helvetica-Bold"


def _register_fonts() -> None:
    """Register Chinese-capable fonts; falls back to Helvetica if none found."""
    global FONT_REGULAR, FONT_BOLD
    FONT_REGULAR, FONT_BOLD = _register_cjk_fonts()


# ── Styles (built after fonts are registered) ──────────────────────────────
def _build_styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "body": ParagraphStyle(
            "body", parent=base["BodyText"],
            fontName=FONT_REGULAR, fontSize=10, leading=14,
            textColor=INK, spaceAfter=6,
        ),
        "h1": ParagraphStyle(
            "h1", parent=base["Heading1"],
            fontName=FONT_BOLD, fontSize=20, leading=24,
            textColor=NAVY, spaceBefore=6, spaceAfter=10,
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Heading2"],
            fontName=FONT_BOLD, fontSize=14, leading=18,
            textColor=NAVY, spaceBefore=14, spaceAfter=6,
        ),
        "h3": ParagraphStyle(
            "h3", parent=base["Heading3"],
            fontName=FONT_BOLD, fontSize=11, leading=15,
            textColor=NAVY, spaceBefore=10, spaceAfter=4,
        ),
        "li": ParagraphStyle(
            "li", parent=base["BodyText"],
            fontName=FONT_REGULAR, fontSize=10, leading=14,
            textColor=INK, leftIndent=14, bulletIndent=2, spaceAfter=2,
        ),
        "quote": ParagraphStyle(
            "quote", parent=base["BodyText"],
            fontName=FONT_REGULAR, fontSize=10, leading=14,
            textColor=MUTED, leftIndent=12, spaceAfter=6,
        ),
        "code": ParagraphStyle(
            "code", parent=base["Code"],
            fontName="Courier", fontSize=9, leading=12,
            textColor=INK, backColor=BG_CODE, leftIndent=6,
            borderPadding=4, spaceAfter=6,
        ),
        "cell": ParagraphStyle(
            "cell", parent=base["BodyText"],
            fontName=FONT_REGULAR, fontSize=9, leading=12,
            textColor=INK, spaceAfter=0,
        ),
        "cell_head": ParagraphStyle(
            "cell_head", parent=base["BodyText"],
            fontName=FONT_BOLD, fontSize=9, leading=12,
            textColor=NAVY, spaceAfter=0,
        ),
        "title": ParagraphStyle(
            "title", parent=base["Title"],
            fontName=FONT_BOLD, fontSize=26, leading=30,
            textColor=NAVY, alignment=0, spaceAfter=4,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", parent=base["BodyText"],
            fontName=FONT_REGULAR, fontSize=11, leading=14,
            textColor=MUTED, spaceAfter=20,
        ),
    }


# ── Inline Markdown → reportlab mini-HTML ──────────────────────────────────
_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD        = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC      = re.compile(r"(?<!\*)\*(?!\*)([^*]+)\*")
_LINK        = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def _escape(text: str) -> str:
    return (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;"))


def _render_inline(text: str) -> str:
    """Markdown inline → reportlab mini-HTML. Order matters."""
    # Temporarily remove inline code so formatting inside isn't touched.
    placeholders: List[str] = []
    def _code_sub(m: re.Match) -> str:
        placeholders.append(m.group(1))
        return f"\x00{len(placeholders) - 1}\x00"
    text = _INLINE_CODE.sub(_code_sub, text)

    # Now escape the remaining text.
    text = _escape(text)

    # Links → reportlab <link>. We only emit a real clickable link when the
    # target is an absolute URL (http/https/mailto); anchor links like
    # "#section-slug" would raise "format not resolved" at save time because
    # we don't register PDF bookmarks, so we render them as plain bold text.
    def _link_sub(m: re.Match) -> str:
        label, target = m.group(1), m.group(2)
        if re.match(r"(?i)^(https?:|mailto:)", target):
            return (f'<link href="{target}" color="#3B82F6">'
                    f'<u>{label}</u></link>')
        return f"<b>{label}</b>"
    text = _LINK.sub(_link_sub, text)
    text = _BOLD.sub(r"<b>\1</b>", text)
    text = _ITALIC.sub(r"<i>\1</i>", text)

    # Restore code placeholders, escaped and styled.
    def _restore(m: re.Match) -> str:
        idx = int(m.group(1))
        return (f'<font face="Courier" color="#334155" backColor="#F1F5F9">'
                f' {_escape(placeholders[idx])} </font>')
    text = re.sub(r"\x00(\d+)\x00", _restore, text)
    return text


# ── Block-level parser ─────────────────────────────────────────────────────
@dataclass
class Block:
    kind: str
    data: object


def _parse(md: str) -> List[Block]:
    lines = md.replace("\r\n", "\n").split("\n")
    out: List[Block] = []
    i = 0

    def _is_table_header(idx: int) -> bool:
        if idx + 1 >= len(lines):
            return False
        if "|" not in lines[idx]:
            return False
        sep = lines[idx + 1]
        # separator row is |---|---| with optional colons; accept if it's
        # nothing but pipes, dashes, colons and spaces.
        return (re.fullmatch(r"[\s|:\-]+", sep) is not None
                and "-" in sep
                and "|" in sep)

    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip()

        # Fenced code block
        if line.startswith("```"):
            buf: List[str] = []
            i += 1
            while i < len(lines) and not lines[i].lstrip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1   # skip closing fence
            out.append(Block("code", "\n".join(buf)))
            continue

        # Horizontal rule
        if re.fullmatch(r"-{3,}|_{3,}|\*{3,}", line.strip()):
            out.append(Block("hr", None))
            i += 1
            continue

        # Heading
        m = re.match(r"(#{1,6})\s+(.*)", line)
        if m:
            level = min(3, len(m.group(1)))   # cap at H3; docs don't need more
            out.append(Block(f"h{level}", m.group(2).strip()))
            i += 1
            continue

        # Table (header row + separator + body rows)
        if _is_table_header(i):
            header = _split_row(lines[i])
            i += 2                            # skip separator row
            rows: List[List[str]] = []
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append(_split_row(lines[i]))
                i += 1
            out.append(Block("table", (header, rows)))
            continue

        # Blockquote (group consecutive >)
        if line.lstrip().startswith(">"):
            buf2: List[str] = []
            while i < len(lines) and lines[i].lstrip().startswith(">"):
                buf2.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            out.append(Block("quote", "\n".join(buf2).strip()))
            continue

        # Unordered list (group consecutive -/*)
        if re.match(r"\s*[-*+]\s+", line):
            items: List[str] = []
            while i < len(lines) and re.match(r"\s*[-*+]\s+", lines[i]):
                items.append(re.sub(r"^\s*[-*+]\s+", "", lines[i]))
                i += 1
            out.append(Block("ul", items))
            continue

        # Ordered list
        if re.match(r"\s*\d+\.\s+", line):
            items2: List[str] = []
            while i < len(lines) and re.match(r"\s*\d+\.\s+", lines[i]):
                items2.append(re.sub(r"^\s*\d+\.\s+", "", lines[i]))
                i += 1
            out.append(Block("ol", items2))
            continue

        # Blank line
        if not line.strip():
            out.append(Block("blank", None))
            i += 1
            continue

        # Paragraph (fold soft line breaks into spaces until a blank / new block)
        buf3 = [line.strip()]
        i += 1
        while i < len(lines):
            nxt = lines[i]
            if (not nxt.strip()
                    or nxt.startswith("#")
                    or nxt.startswith("```")
                    or re.fullmatch(r"-{3,}|_{3,}|\*{3,}", nxt.strip())
                    or re.match(r"\s*[-*+]\s+", nxt)
                    or re.match(r"\s*\d+\.\s+", nxt)
                    or nxt.lstrip().startswith(">")
                    or _is_table_header(i)):
                break
            buf3.append(nxt.strip())
            i += 1
        out.append(Block("p", " ".join(buf3)))

    return out


def _split_row(line: str) -> List[str]:
    # strip leading/trailing | then split; preserve inner pipes escaped as \|
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    parts = re.split(r"(?<!\\)\|", s)
    return [p.replace(r"\|", "|").strip() for p in parts]


# ── Build reportlab story from blocks ──────────────────────────────────────
def _build_story(blocks: List[Block], styles: dict, content_width: float) -> List:
    story: List = []
    for b in blocks:
        if b.kind == "blank":
            continue

        if b.kind == "hr":
            story.append(Spacer(1, 4))
            story.append(HRFlowable(width="100%", thickness=0.5,
                                    color=HAIRLINE, spaceBefore=0, spaceAfter=6))
            continue

        if b.kind in ("h1", "h2", "h3"):
            text = _render_inline(b.data)
            story.append(Paragraph(text, styles[b.kind]))
            if b.kind == "h1":
                story.append(HRFlowable(width="100%", thickness=1.2,
                                        color=ACCENT, spaceBefore=0, spaceAfter=8))
            continue

        if b.kind == "p":
            story.append(Paragraph(_render_inline(b.data), styles["body"]))
            continue

        if b.kind == "ul":
            for item in b.data:
                story.append(Paragraph("• " + _render_inline(item), styles["li"]))
            story.append(Spacer(1, 4))
            continue

        if b.kind == "ol":
            for n, item in enumerate(b.data, 1):
                story.append(Paragraph(f"{n}. " + _render_inline(item), styles["li"]))
            story.append(Spacer(1, 4))
            continue

        if b.kind == "quote":
            # Render the quote as a single paragraph with a left rule.
            inner = Paragraph(_render_inline(b.data.replace("\n", " ")), styles["quote"])
            tbl = Table([[inner]], colWidths=[content_width])
            tbl.setStyle(TableStyle([
                ("LEFTPADDING",  (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING",   (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
                ("LINEBEFORE",   (0, 0), (0, -1), 2, ACCENT),
                ("BACKGROUND",   (0, 0), (-1, -1), BG_SOFT),
            ]))
            story.append(tbl)
            story.append(Spacer(1, 6))
            continue

        if b.kind == "code":
            text = _escape(b.data).replace("\n", "<br/>")
            story.append(Paragraph(
                f'<font face="Courier">{text}</font>', styles["code"]))
            continue

        if b.kind == "table":
            header, rows = b.data
            # Auto column widths: give every column an equal share.
            ncols = max(len(header), max((len(r) for r in rows), default=0))
            cw = content_width / ncols
            # Pad ragged rows so the Table doesn't throw.
            def _pad(row: List[str]) -> List[str]:
                return row + [""] * (ncols - len(row))
            data = [
                [Paragraph(_render_inline(c), styles["cell_head"]) for c in _pad(header)]
            ] + [
                [Paragraph(_render_inline(c), styles["cell"])     for c in _pad(r)]
                for r in rows
            ]
            tbl = Table(data, colWidths=[cw] * ncols, repeatRows=1)
            tbl.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, 0),  BG_SOFT),
                ("LINEBELOW",     (0, 0), (-1, 0),  0.8, NAVY),
                ("LINEBELOW",     (0, 0), (-1, -1), 0.3, HAIRLINE),
                ("LEFTPADDING",   (0, 0), (-1, -1), 6),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
                ("TOPPADDING",    (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ]))
            # Keep the table header with at least one data row.
            story.append(KeepTogether([tbl]))
            story.append(Spacer(1, 8))
            continue

    return story


# ── Cover + page frame ─────────────────────────────────────────────────────
def _make_cover(title: str, subtitle: str, styles: dict) -> List:
    return [
        Spacer(1, 20),
        Paragraph(_escape(title), styles["title"]),
        HRFlowable(width="40%", thickness=2, color=ACCENT,
                   spaceBefore=2, spaceAfter=8),
        Paragraph(_escape(subtitle), styles["subtitle"]),
    ]


def _on_page(canvas, doc) -> None:
    """Footer: page N / total is not trivial with SimpleDocTemplate;
    we just print 'QSForge  ·  Page N'."""
    canvas.saveState()
    canvas.setFont(FONT_REGULAR, 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(20 * mm, 12 * mm, "QSForge")
    canvas.drawRightString(
        doc.pagesize[0] - 20 * mm, 12 * mm,
        f"Page {doc.page}",
    )
    canvas.setStrokeColor(HAIRLINE)
    canvas.setLineWidth(0.4)
    canvas.line(20 * mm, 15 * mm, doc.pagesize[0] - 20 * mm, 15 * mm)
    canvas.restoreState()


# ── Public entry point ─────────────────────────────────────────────────────
def convert(md_path: Path, pdf_path: Path, display_title: Optional[str] = None) -> None:
    _register_fonts()
    styles = _build_styles()
    md_text = md_path.read_text(encoding="utf-8")

    # Strip the very first H1 so we don't print the title twice — the cover
    # renders it already. Keep body H1s if a doc has multiple top sections.
    blocks = _parse(md_text)
    subtitle = f"Source: {md_path.name}   ·   Generated by QSForge build pipeline"
    title = display_title
    for b in blocks:
        if b.kind == "h1":
            if title is None:
                title = b.data
            blocks.remove(b)
            break
    title = title or md_path.stem

    page_size = A4
    margin = 20 * mm
    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=page_size,
        leftMargin=margin, rightMargin=margin,
        topMargin=margin, bottomMargin=margin + 6 * mm,
        title=title,
        author="QSForge",
    )
    content_width = page_size[0] - 2 * margin
    story = _make_cover(title, subtitle, styles) \
          + _build_story(blocks, styles, content_width)

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)


def _cli() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input",  type=Path, help="input .md file")
    ap.add_argument("output", type=Path, help="output .pdf file")
    ap.add_argument("--title", default=None,
                    help="display title for the cover (defaults to first H1)")
    args = ap.parse_args()

    if not args.input.is_file():
        print(f"ERROR: not a file: {args.input}", file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)

    convert(args.input, args.output, args.title)
    size_kb = args.output.stat().st_size / 1024
    print(f"Wrote {args.output}  ({size_kb:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
