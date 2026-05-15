"""
QSForge - Module 3b: PDF Report

Generates a two-section PDF from the analysis payload produced by
server._run_job (Module 0 + Module 2 + Score).

Section A — Executive Summary (QS audience):
    file header · verdict card · dimension bars · top blockers · narrative

Section B — Detailed Report (BIM audience):
    each of the nine checks with severity, summary, by-category breakdown,
    and a sample of Revit Element IDs; followed by Module 0 readiness flags
    and an inventory summary.

Public API:
    generate_pdf(data, output_path, source_name=None) -> Path
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
    KeepTogether,
)
from reportlab.platypus.flowables import Flowable

import paths as app_paths


# ── Font discovery ──────────────────────────────────────────────────────────
# Prefer fonts bundled inside the QSForge install. This guarantees Chinese
# text renders on any Windows machine — including English Windows where
# YaHei / SimHei / SimSun are not installed.
_BUNDLED_FONT_DIR = app_paths.resource_dir() / "assets" / "fonts"

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

# Module-level font names — set by _register_cjk_fonts() at PDF generation time.
FONT_REGULAR = "Helvetica"
FONT_BOLD = "Helvetica-Bold"


def _register_cjk_fonts():
    """Register a CJK font pair with reportlab. Returns (regular, bold).

    Updates the module-level FONT_REGULAR / FONT_BOLD globals so they can be
    consumed by the canvas-level draws inside the custom Flowables.
    """
    global FONT_REGULAR, FONT_BOLD
    for regular, bold in _CJK_FONT_CANDIDATES:
        if regular.exists() and bold.exists():
            try:
                pdfmetrics.registerFont(TTFont("QSForgeCJK", str(regular)))
                pdfmetrics.registerFont(TTFont("QSForgeCJK-Bold", str(bold)))
                FONT_REGULAR, FONT_BOLD = "QSForgeCJK", "QSForgeCJK-Bold"
                return FONT_REGULAR, FONT_BOLD
            except Exception:
                continue
    FONT_REGULAR, FONT_BOLD = "Helvetica", "Helvetica-Bold"
    return FONT_REGULAR, FONT_BOLD


# ── Palette (matches the UI) ────────────────────────────────────────────────
NAVY        = colors.HexColor("#0F172A")
SURFACE     = colors.HexColor("#1E2A44")
SURFACE_2   = colors.HexColor("#2D3B5A")
BORDER      = colors.HexColor("#334155")
TEXT        = colors.HexColor("#E2E8F0")
MUTED       = colors.HexColor("#94A3B8")
ACCENT      = colors.HexColor("#3B82F6")
SUCCESS     = colors.HexColor("#10B981")
WARNING     = colors.HexColor("#F59E0B")
DANGER      = colors.HexColor("#EF4444")

SEV_COLORS = {"CRITICAL": DANGER, "WARNING": WARNING, "OK": SUCCESS}

VERDICT_COLOR_MAP = {
    "success": SUCCESS, "warning": WARNING, "danger": DANGER,
}

MAX_IDS_PER_CHECK = 100  # cap Element IDs printed in the PDF
MAX_ITEMS_PER_CHECK = 20  # cap item rows (multi-storey / unhosted / nested)
MAX_LAYER_TYPES = 15     # cap type rows in layer-materials check
MAX_INVENTORY_ROWS = 25  # cap inventory table


# ── Styles ──────────────────────────────────────────────────────────────────
def _styles():
    base = getSampleStyleSheet()
    return {
        "h1": ParagraphStyle("h1", parent=base["Heading1"],
                             fontName=FONT_BOLD, fontSize=18, leading=22,
                             textColor=NAVY, spaceAfter=2),
        "h2": ParagraphStyle("h2", parent=base["Heading2"],
                             fontName=FONT_BOLD, fontSize=13, leading=16,
                             textColor=NAVY, spaceBefore=14, spaceAfter=6),
        "h3": ParagraphStyle("h3", parent=base["Heading3"],
                             fontName=FONT_BOLD, fontSize=11, leading=14,
                             textColor=NAVY, spaceBefore=10, spaceAfter=2),
        "meta": ParagraphStyle("meta", parent=base["Normal"],
                               fontName=FONT_REGULAR, fontSize=9, leading=12,
                               textColor=MUTED),
        "body": ParagraphStyle("body", parent=base["Normal"],
                               fontName=FONT_REGULAR, fontSize=10, leading=14,
                               textColor=NAVY, alignment=TA_LEFT),
        "small": ParagraphStyle("small", parent=base["Normal"],
                                fontName=FONT_REGULAR, fontSize=8.5, leading=11,
                                textColor=MUTED),
        "ids": ParagraphStyle("ids", parent=base["Normal"],
                              fontName="Courier", fontSize=8, leading=10.5,
                              textColor=NAVY),
        "verdict_label": ParagraphStyle("verdict_label", parent=base["Heading1"],
                                        fontName=FONT_BOLD, fontSize=22, leading=26,
                                        textColor=NAVY),
        "verdict_extra": ParagraphStyle("verdict_extra", parent=base["Normal"],
                                        fontName=FONT_REGULAR, fontSize=11, leading=14,
                                        textColor=MUTED),
    }


# ── Custom Flowables ────────────────────────────────────────────────────────
class ScoreDisk(Flowable):
    """A 36mm circle with the overall score centered — mimics the UI dial."""

    def __init__(self, score: int, outline: colors.Color):
        super().__init__()
        self.score = score
        self.outline = outline
        self.size = 36 * mm

    def wrap(self, _aw, _ah):
        return self.size, self.size

    def draw(self):
        c = self.canv
        r = self.size / 2
        c.saveState()
        c.setFillColor(colors.HexColor("#F8FAFC"))
        c.setStrokeColor(self.outline)
        c.setLineWidth(2.5)
        c.circle(r, r, r - 2, stroke=1, fill=1)
        c.setFillColor(NAVY)
        c.setFont(FONT_BOLD, 26)
        c.drawCentredString(r, r - 2, str(self.score))
        c.setFillColor(MUTED)
        c.setFont(FONT_REGULAR, 8)
        c.drawCentredString(r, r - 15, "/ 100")
        c.restoreState()


class DimensionBar(Flowable):
    """A compact score progress bar with label + weight + numeric value."""

    WIDTH = 165 * mm
    HEIGHT = 8 * mm

    def __init__(self, label: str, weight: int, score: int):
        super().__init__()
        self.label = label
        self.weight = weight
        self.score = max(0, min(100, int(score)))

    def wrap(self, _aw, _ah):
        return self.WIDTH, self.HEIGHT

    def draw(self):
        c = self.canv
        # Label on the left
        c.setFont(FONT_REGULAR, 9)
        c.setFillColor(NAVY)
        c.drawString(0, self.HEIGHT / 2 - 2, self.label)
        # Weight — right after label
        c.setFont(FONT_REGULAR, 8)
        c.setFillColor(MUTED)
        c.drawString(58 * mm, self.HEIGHT / 2 - 2, f"{self.weight}%")

        # Bar
        bar_x, bar_w = 70 * mm, 70 * mm
        bar_y, bar_h = 1 * mm, 3.5 * mm
        c.setFillColor(colors.HexColor("#E2E8F0"))
        c.setStrokeColor(BORDER)
        c.setLineWidth(0.3)
        c.rect(bar_x, bar_y, bar_w, bar_h, stroke=1, fill=1)

        fill_color = (SUCCESS if self.score >= 85
                      else WARNING if self.score >= 50
                      else DANGER)
        c.setFillColor(fill_color)
        c.setStrokeColor(fill_color)
        fill_w = bar_w * (self.score / 100.0)
        if fill_w > 0:
            c.rect(bar_x, bar_y, fill_w, bar_h, stroke=0, fill=1)

        # Value on the right
        c.setFont(FONT_BOLD, 9)
        c.setFillColor(NAVY)
        c.drawRightString(bar_x + bar_w + 15 * mm, self.HEIGHT / 2 - 2, f"{self.score}/100")


class SeverityBadge(Flowable):
    """Small pill used in tables — [CRITICAL] / [WARNING] / [OK]."""

    def __init__(self, severity: str):
        super().__init__()
        self.severity = severity
        self.h = 4.5 * mm
        self.w = 18 * mm

    def wrap(self, _aw, _ah):
        return self.w, self.h

    def draw(self):
        c = self.canv
        color = SEV_COLORS.get(self.severity, MUTED)
        c.saveState()
        c.setFillColor(color)
        c.roundRect(0, 0, self.w, self.h, 1.2 * mm, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont(FONT_BOLD, 7)
        c.drawCentredString(self.w / 2, self.h / 2 - 2, self.severity)
        c.restoreState()


# ── Page header/footer ──────────────────────────────────────────────────────
def _on_page(canvas, doc):
    canvas.saveState()
    # Footer
    canvas.setFont(FONT_REGULAR, 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(20 * mm, 12 * mm, "Generated by QSForge — Revit Model Quality Check")
    canvas.drawRightString(A4[0] - 20 * mm, 12 * mm, f"Page {doc.page}")
    # Separator
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.3)
    canvas.line(20 * mm, 15 * mm, A4[0] - 20 * mm, 15 * mm)
    canvas.restoreState()


# ── Helpers ─────────────────────────────────────────────────────────────────
def _verdict_color(verdict: Dict[str, Any]) -> colors.Color:
    return VERDICT_COLOR_MAP.get((verdict or {}).get("color", ""), MUTED)


def _get_check(data: Dict[str, Any], check_id: str) -> Dict[str, Any]:
    for c in (data.get("module2") or {}).get("checks", []):
        if c.get("id") == check_id:
            return c
    return {}


def _escape(text: Optional[str]) -> str:
    if text is None:
        return ""
    return (str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))


def _rank_blockers(checks: List[Dict[str, Any]], limit: int = 3) -> List[Dict[str, Any]]:
    sev_rank = {"CRITICAL": 0, "WARNING": 1, "OK": 2}
    return sorted(
        [c for c in checks if c.get("severity") != "OK" and (c.get("total") or 0) > 0],
        key=lambda c: (sev_rank.get(c.get("severity"), 99), -(c.get("total") or 0)),
    )[:limit]


# ── Section A: Executive Summary ────────────────────────────────────────────
def _exec_summary(data: Dict[str, Any], source_name: Optional[str], S: dict) -> List[Flowable]:
    story: List[Flowable] = []
    score = data.get("score") or {}
    verdict = score.get("verdict") or {}
    v_color = _verdict_color(verdict)

    # Header block
    story.append(Paragraph("QSForge Model Quality Report", S["h1"]))
    story.append(Paragraph(_escape(source_name or "(unnamed file)"), S["body"]))
    story.append(Paragraph(
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}    ·    "
        f"QS entities: {(data.get('file') or {}).get('qs_entity_count', 0):,}    ·    "
        f"Categories: {len(data.get('categories') or [])}",
        S["meta"]
    ))
    story.append(Spacer(1, 10 * mm))

    # Verdict (score disk + label block) — laid out with an invisible table
    disk = ScoreDisk(score.get("overall", 0), v_color)

    label = Paragraph(
        f'<font color="#{v_color.hexval()[2:]}"><b>{verdict.get("icon","")} '
        f'{_escape(verdict.get("label","Unknown"))}</b></font>',
        S["verdict_label"]
    )
    extra_hrs = score.get("extra_qs_hours")
    extra_line = ""
    if isinstance(extra_hrs, int):
        extra_line = (f'Estimated <b>+{extra_hrs} hour{"" if extra_hrs == 1 else "s"}</b> '
                      f'extra QS effort to recover this model.')
    extra_para = Paragraph(extra_line, S["verdict_extra"])

    # Sub stat: critical/warning counts
    m2 = data.get("module2") or {}
    summ = m2.get("summary") or {}
    sub = Paragraph(
        f'<font color="#{DANGER.hexval()[2:]}"><b>{summ.get("critical",0)}</b></font> critical  ·  '
        f'<font color="#{WARNING.hexval()[2:]}"><b>{summ.get("warning",0)}</b></font> warning  ·  '
        f'<font color="#{SUCCESS.hexval()[2:]}"><b>{summ.get("ok",0)}</b></font> ok  '
        f'<font color="#{MUTED.hexval()[2:]}">(across 9 quality checks)</font>',
        S["body"]
    )

    verdict_tbl = Table(
        [[disk, [label, Spacer(1, 3 * mm), extra_para, Spacer(1, 3 * mm), sub]]],
        colWidths=[42 * mm, 128 * mm],
    )
    verdict_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(verdict_tbl)
    story.append(Spacer(1, 10 * mm))

    # Dimension bars
    story.append(Paragraph("Score Breakdown", S["h2"]))
    for d in score.get("dimensions", []):
        story.append(DimensionBar(d["label"], d["weight"], d["score"]))
        story.append(Spacer(1, 2 * mm))

    # Top blockers
    checks = m2.get("checks", [])
    blockers = _rank_blockers(checks, limit=3)
    story.append(Paragraph("Top Blockers", S["h2"]))
    if not blockers:
        story.append(Paragraph(
            "No blocking issues detected. The model is clean across all nine quality checks.",
            S["body"]
        ))
    else:
        rows = [[SeverityBadge(c.get("severity", "")),
                 Paragraph(f'<b>{_escape(c.get("label",""))}</b><br/>'
                           f'<font size=8 color="#{MUTED.hexval()[2:]}">{_escape(c.get("summary",""))}</font>',
                           S["body"])]
                for c in blockers]
        blockers_tbl = Table(rows, colWidths=[22 * mm, 148 * mm])
        blockers_tbl.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LINEBELOW", (0, 0), (-1, -2), 0.3, BORDER),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(blockers_tbl)

    # Narrative
    story.append(Paragraph("What this means for QTO", S["h2"]))
    for para in _narrative_paragraphs(data):
        story.append(Paragraph(para, S["body"]))
        story.append(Spacer(1, 3 * mm))

    return story


def _narrative_paragraphs(data: Dict[str, Any]) -> List[str]:
    score = data.get("score") or {}
    verdict = score.get("verdict") or {}
    code = verdict.get("code", "UNKNOWN")
    extra = score.get("extra_qs_hours")
    m2_summ = (data.get("module2") or {}).get("summary") or {}

    paragraphs = []
    if code == "READY":
        paragraphs.append(
            "The model is <b>ready for quantity take-off</b>. All volumetric elements "
            "have Volume and Level data, and no CAD contamination was detected."
        )
    elif code == "CONDITIONAL":
        paragraphs.append(
            "The model is <b>conditionally ready</b> for QTO. Some categories have gaps "
            "that will require manual handling or a short clarification loop with the "
            "BIM team. Review the Detailed Report section before issuing rates."
        )
    elif code == "HIGH_RISK":
        paragraphs.append(
            "This model is <b>high-risk for QTO</b>. Significant data is missing — "
            "running quantity take-off against it will produce unreliable totals. "
            "We recommend returning the model to the BIM team with the Element ID "
            "lists from the Detailed Report, then re-submitting for a clean pass."
        )
    elif code == "DO_NOT_USE":
        paragraphs.append(
            "This model is <b>not usable</b> for quantity take-off in its current state. "
            "Fundamental attributes (Level, Volume, Material) are absent on the majority "
            "of elements. Request a corrected model before any costing work."
        )
    else:
        paragraphs.append("Scoring did not complete — see the Detailed Report for the raw checks.")

    # Weakness + hours.
    weakest = sorted(
        [d for d in score.get("dimensions", []) if d.get("id") != "coordinate_system"],
        key=lambda d: d.get("score", 100),
    )[:2]
    if weakest and isinstance(extra, int) and extra > 0:
        names = ", ".join(f"<b>{_escape(d['label'])}</b>" for d in weakest)
        paragraphs.append(
            f"Biggest weaknesses: {names}. Plan roughly <b>+{extra} hour"
            f"{'s' if extra != 1 else ''}</b> of extra QS effort if you "
            f"proceed without a model fix."
        )

    # Next step line.
    m2_crit = m2_summ.get("critical", 0)
    m2_warn = m2_summ.get("warning", 0)
    if code != "READY" and (m2_crit + m2_warn) > 0:
        paragraphs.append(
            f"<b>Next step:</b> share the Element ID lists in the Detailed Report with "
            f"the BIM team ({m2_crit} critical, {m2_warn} warning). They can paste the "
            f"IDs directly into Revit's <i>Select by ID</i> dialog to locate each element."
        )

    return paragraphs


# ── Section B: Detailed Report ──────────────────────────────────────────────
def _detail_report(data: Dict[str, Any], S: dict) -> List[Flowable]:
    story: List[Flowable] = [Paragraph("Detailed Report", S["h1"]),
                             Spacer(1, 4 * mm)]

    checks = (data.get("module2") or {}).get("checks", [])
    for c in checks:
        story.extend(_render_check(c, S))

    # Module 0 readiness flags
    issues = data.get("issues") or []
    if issues:
        story.append(PageBreak())
        story.append(Paragraph("QS Readiness Flags (Module 0)", S["h2"]))
        story.append(Paragraph(
            "High-level flags derived from per-category coverage. "
            "These partially overlap with the quality checks above.",
            S["small"]
        ))
        story.append(Spacer(1, 3 * mm))
        sev_rank = {"CRITICAL": 0, "WARNING": 1}
        issues_sorted = sorted(issues, key=lambda i: (sev_rank.get(i.get("severity"), 99),
                                                      i.get("category_label", "")))
        rows = [["Severity", "Category", "Message"]]
        for i in issues_sorted:
            rows.append([
                i.get("severity", ""),
                i.get("category_label", ""),
                i.get("message", ""),
            ])
        tbl = Table(rows, colWidths=[22 * mm, 38 * mm, 110 * mm], repeatRows=1)
        tbl.setStyle(_table_style(header=True))
        # Paint severity cells
        for r_idx, row in enumerate(rows[1:], start=1):
            sev = row[0]
            tbl.setStyle(TableStyle([
                ("TEXTCOLOR", (0, r_idx), (0, r_idx), SEV_COLORS.get(sev, MUTED)),
                ("FONTNAME", (0, r_idx), (0, r_idx), FONT_BOLD),
            ]))
        story.append(tbl)

    # Inventory summary
    categories = data.get("categories") or []
    if categories:
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph("Inventory by Category", S["h2"]))
        rows = [["Category", "Count", "Vol Cov %", "Lvl Cov %", "Vol m³", "Area m²"]]
        shown = categories[:MAX_INVENTORY_ROWS]
        for c in shown:
            vol_cov = c.get("volume", {}).get("coverage_pct")
            lvl_cov = 100 - (c.get("no_level_pct") or 0)
            rows.append([
                c.get("label", ""),
                f"{c.get('count', 0):,}",
                "—" if (vol_cov is None) else f"{vol_cov:.0f}%",
                f"{lvl_cov:.0f}%",
                (f"{c['volume']['total']:,.1f}"
                 if c.get("volume", {}).get("total") else "—"),
                (f"{c['area']['total']:,.1f}"
                 if c.get("area", {}).get("total") else "—"),
            ])
        inv_tbl = Table(rows, colWidths=[55 * mm, 20 * mm, 20 * mm, 20 * mm, 27 * mm, 28 * mm],
                        repeatRows=1)
        inv_tbl.setStyle(_table_style(header=True, align_numeric=(1, 5)))
        story.append(inv_tbl)
        if len(categories) > MAX_INVENTORY_ROWS:
            story.append(Paragraph(
                f"Showing {MAX_INVENTORY_ROWS} of {len(categories)} categories. "
                f"See the QSForge UI for the complete inventory.",
                S["small"]
            ))

    # Final note
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(
        "Note: Element IDs in this report are truncated for readability. "
        "Open the analysis in QSForge and use the <b>Copy IDs</b> button on any "
        "check to get the full list on your clipboard — paste directly into "
        "Revit's <i>Select by ID</i> dialog.",
        S["small"]
    ))
    return story


def _render_check(c: Dict[str, Any], S: dict) -> List[Flowable]:
    block: List[Flowable] = []
    sev = c.get("severity", "OK")

    # Title row: severity pill + label
    title_tbl = Table(
        [[SeverityBadge(sev),
          Paragraph(f'<b>{_escape(c.get("label",""))}</b>', S["h3"])]],
        colWidths=[22 * mm, 148 * mm],
    )
    title_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    summary_para = Paragraph(_escape(c.get("summary", "")), S["body"])
    desc = c.get("description") or ""
    desc_para = Paragraph(_escape(desc), S["small"]) if desc else None

    intro_flow = [title_tbl, Spacer(1, 2 * mm), summary_para]
    if desc_para is not None:
        intro_flow.append(Spacer(1, 1.5 * mm))
        intro_flow.append(desc_para)

    block.append(KeepTogether(intro_flow))
    block.append(Spacer(1, 3 * mm))

    # By-category breakdown
    by_cat = c.get("by_category") or {}
    if by_cat:
        keys = list(by_cat.keys())
        first = by_cat[keys[0]]
        is_pct = "missing" in first
        if is_pct:
            rows = [["Category", "Missing", "Total", "%"]]
            for k in keys:
                info = by_cat[k]
                rows.append([
                    info.get("label", k),
                    f"{info.get('missing', 0):,}",
                    f"{info.get('total', 0):,}",
                    f"{info.get('pct', 0)}%",
                ])
            widths = [70 * mm, 30 * mm, 30 * mm, 20 * mm]
        else:
            rows = [["Category", "Count"]]
            for k in keys:
                info = by_cat[k]
                rows.append([info.get("label", k), f"{info.get('count', 0):,}"])
            widths = [120 * mm, 30 * mm]

        tbl = Table(rows, colWidths=widths, repeatRows=1)
        tbl.setStyle(_table_style(header=True, align_numeric=range(1, len(rows[0]))))
        block.append(tbl)
        block.append(Spacer(1, 3 * mm))

    # Items sample (multi-storey / unhosted / nested)
    items = c.get("items_sample") or []
    if items and c.get("id") != "layer_materials":
        block.append(Paragraph(
            f"<b>Affected elements</b> — showing up to {MAX_ITEMS_PER_CHECK} of {len(items):,}",
            S["small"]
        ))
        rows = _items_rows(c.get("id", ""), items[:MAX_ITEMS_PER_CHECK])
        tbl = Table(rows, colWidths=_items_widths(c.get("id", "")), repeatRows=1)
        tbl.setStyle(_table_style(header=True))
        block.append(tbl)
        block.append(Spacer(1, 3 * mm))

    # Layer-materials nested table
    if c.get("id") == "layer_materials" and items:
        block.append(Paragraph(
            f"<b>Assembly types with missing layer materials</b> — showing up to "
            f"{MAX_LAYER_TYPES} of {len(items):,}",
            S["small"]
        ))
        for t in items[:MAX_LAYER_TYPES]:
            block.append(Paragraph(
                f'<b>{_escape(t.get("type_name",""))}</b>  '
                f'<font size=8 color="#{MUTED.hexval()[2:]}">'
                f'{_escape(t.get("category_label",""))} · '
                f'{t.get("element_count",0):,} element(s) · '
                f'{t.get("empty_layers",0)} empty layer(s)</font>',
                S["body"]
            ))
            layer_rows = [["Layer", "Filled", "Empty", "% Empty", "Materials seen"]]
            for l in (t.get("layers") or []):
                mats = ", ".join(l.get("sample_materials") or []) or "—"
                layer_rows.append([
                    l.get("column", ""),
                    f"{l.get('filled', 0):,}",
                    f"{l.get('empty', 0):,}",
                    f"{l.get('pct_empty', 0)}%",
                    mats,
                ])
            layer_tbl = Table(
                layer_rows,
                colWidths=[45 * mm, 20 * mm, 20 * mm, 20 * mm, 60 * mm],
                repeatRows=1,
            )
            layer_tbl.setStyle(_table_style(header=True, align_numeric=(1, 2, 3)))
            block.append(layer_tbl)
            block.append(Spacer(1, 3 * mm))

    # Element IDs sample
    ids = c.get("element_ids_sample") or []
    if ids:
        shown = ids[:MAX_IDS_PER_CHECK]
        total = c.get("total", len(ids))
        header_txt = (f"<b>Revit Element IDs</b> — first {len(shown):,}"
                      + (f" of {total:,}" if total > len(shown) else ""))
        block.append(Paragraph(header_txt, S["small"]))
        block.append(Paragraph(", ".join(str(x) for x in shown), S["ids"]))
        if total > len(shown):
            block.append(Paragraph(
                f"+{total - len(shown):,} more — use <b>Copy IDs</b> in the QSForge "
                f"UI for the full list.",
                S["small"]
            ))

    block.append(Spacer(1, 6 * mm))
    return block


def _items_rows(check_id: str, items: List[Dict[str, Any]]) -> List[List[str]]:
    if check_id == "multi_storey_vertical":
        rows = [["Element ID", "Category", "Type", "Base → Top"]]
        for it in items:
            rows.append([
                str(it.get("id", "")),
                str(it.get("category", "")).replace("OST_", ""),
                str(it.get("type_name", "")),
                f'{it.get("base","—")} → {it.get("top","—")}',
            ])
    elif check_id == "nested_subcomponents":
        rows = [["Element ID", "Category", "Type", "Host Id"]]
        for it in items:
            rows.append([
                str(it.get("id", "")),
                str(it.get("category", "")).replace("OST_", ""),
                str(it.get("type_name", "")),
                str(it.get("host", "")),
            ])
    else:  # unhosted
        rows = [["Element ID", "Category", "Type"]]
        for it in items:
            rows.append([
                str(it.get("id", "")),
                str(it.get("category", "")).replace("OST_", ""),
                str(it.get("type_name", "")),
            ])
    return rows


def _items_widths(check_id: str):
    if check_id in ("multi_storey_vertical",):
        return [25 * mm, 30 * mm, 55 * mm, 60 * mm]
    if check_id in ("nested_subcomponents",):
        return [25 * mm, 30 * mm, 60 * mm, 55 * mm]
    return [25 * mm, 40 * mm, 105 * mm]


def _table_style(header: bool = True, align_numeric=None) -> TableStyle:
    ts = [
        ("GRID", (0, 0), (-1, -1), 0.3, BORDER),
        ("FONTNAME", (0, 0), (-1, -1), FONT_REGULAR),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (-1, -1), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if header:
        ts += [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E2E8F0")),
            ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
            ("TEXTCOLOR", (0, 0), (-1, 0), NAVY),
        ]
    if align_numeric:
        for col in align_numeric:
            ts.append(("ALIGN", (col, 0), (col, -1), "RIGHT"))
    return TableStyle(ts)


# ── Public API ──────────────────────────────────────────────────────────────
def generate_pdf(data: Dict[str, Any],
                 output_path: str | Path,
                 source_name: Optional[str] = None) -> Path:
    """Render the analysis payload to a PDF file at `output_path`."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    _register_cjk_fonts()
    S = _styles()

    doc = SimpleDocTemplate(
        str(out),
        pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=18 * mm, bottomMargin=22 * mm,
        title="QSForge Model Quality Report",
        author="QSForge",
    )

    story: List[Flowable] = []
    story.extend(_exec_summary(data, source_name, S))
    story.append(PageBreak())
    story.extend(_detail_report(data, S))

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    return out


# ── CLI / smoke test ────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    import json

    if len(sys.argv) < 3:
        print("Usage: python pdf_report.py <last_result.json> <output.pdf>")
        sys.exit(2)

    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    data = json.loads(src.read_text(encoding="utf-8"))
    out = generate_pdf(
        data,
        dst,
        source_name=(data.get("file") or {}).get("path") or src.name,
    )
    print(f"PDF written: {out}")
