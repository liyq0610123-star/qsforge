"""
Module 2 — quality checks + BQ Draft generation.

Replaces the legacy stub. When called by server._run_job, this:
  1. Generates a BQ Draft Excel using module2_bq_draft (NRM2 format)
  2. Returns a checks summary describing what was generated

If anything goes wrong, returns a safe empty payload so the analysis
finishes successfully with score / inventory still showing.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Any


# Excel sheet names disallow these characters AND have a 31-char limit.
# Revit Level names sometimes include "/" (e.g. "L1/L2" for elements
# spanning two levels), which crashes the BQ write at .to_excel().
_BAD_SHEET_CHARS = re.compile(r"[\\/?*\[\]:]")


def _safe_sheet_name(name: str) -> str:
    s = _BAD_SHEET_CHARS.sub("-", str(name)).strip().strip("'")
    return (s[:31] or "Sheet")


# ─────────────────────────────────────────────
# Public entry — server.py contract
# ─────────────────────────────────────────────

def run_checks(xlsx_path: str | Path) -> Dict[str, Any]:
    """
    Generate BQ Draft and return summary.

    Return shape (locked by server.py + pdf_report):
    {
        "checks":  [{"name": str, "status": str, "message": str}],
        "summary": {"critical": int, "warning": int, "ok": int},
        "bq_draft_path": str | None,
    }
    """
    xlsx_path = str(xlsx_path)
    try:
        return _run(xlsx_path)
    except Exception as e:
        return {
            "checks":  [],
            "summary": {"critical": 0, "warning": 0, "ok": 0},
            "bq_draft_path": None,
            "error":   f"{type(e).__name__}: {e}",
        }


# ─────────────────────────────────────────────
# Implementation
# ─────────────────────────────────────────────

def _run(xlsx_path: str) -> Dict[str, Any]:
    # Local imports so stub can still load if BQ module missing
    import pandas as pd
    import module0_inventory as m0
    import module2_bq_draft as bq

    src = Path(xlsx_path)
    if not src.is_file():
        return {
            "checks":  [],
            "summary": {"critical": 0, "warning": 0, "ok": 0},
            "bq_draft_path": None,
            "error":   f"File not found: {xlsx_path}",
        }

    # 1) Build a Module 0 output Excel in-memory, then feed it to BQ generator.
    #    We don't write the Module 0 Excel (server.py owns last_result.json).
    df = m0._prepare_instance_df(xlsx_path)[0]
    df = m0.tag_qs_categories(df, verbose=False)
    df, _ = m0.filter_non_instances(df, verbose=False)
    df = m0.assign_qs_level(df, verbose=False)
    df = m0.assign_data_quality(df, verbose=False)
    qs_df = df[df["Is_QS_Element"]].copy()

    element_list = m0.build_element_list(qs_df)

    # 2) BQ Draft module loads via load_module0 which expects an Excel.
    #    We replicate the relevant prep here without re-reading from disk.
    element_list[bq.COL_VOLUME] = pd.to_numeric(
        element_list[bq.COL_VOLUME], errors="coerce").fillna(0)
    element_list[bq.COL_AREA] = pd.to_numeric(
        element_list[bq.COL_AREA], errors="coerce").fillna(0)
    # Include ALL QS elements in the BQ draft (not just "Clean" ones).
    # This is a draft — the QS team will review; filtering here would produce
    # an empty BQ for models with widespread data quality issues.
    element_list = bq.add_material_class(element_list)

    # 3) Output path: alongside the source xlsx (predictable for users)
    out_dir = src.parent
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    base = src.stem.replace("_Module0", "")
    out_path = out_dir / f"{base}_BQ_Draft_{timestamp}.xlsx"

    # 4) Write BQ workbook (one sheet per Level + an All Levels sheet)
    levels = sorted(
        [l for l in element_list[bq.COL_LEVEL].unique()
         if l not in bq.INVALID_LEVELS and pd.notna(l)],
        key=lambda x: str(x),
    )

    section_counts = {"H": 0, "11": 0, "14": 0, "17": 0, "28": 0}

    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        bq_all = bq.build_bq(element_list, level=None)
        bq_all.to_excel(writer, sheet_name="BQ – All Levels", index=False)

        # Tally items per Section by walking rows in order, tracking current section
        current_section = None
        for _, row in bq_all.iterrows():
            desc = str(row.get("Description", "")).strip().upper()
            if desc.startswith("SECTION H"):
                current_section = "H"; continue
            if desc.startswith("SECTION 11"):
                current_section = "11"; continue
            if desc.startswith("SECTION 14"):
                current_section = "14"; continue
            if desc.startswith("SECTION 17"):
                current_section = "17"; continue
            if desc.startswith("SECTION 28"):
                current_section = "28"; continue
            # Count only data rows (have Item ref and Unit)
            item = str(row.get("Item", "")).strip()
            unit = str(row.get("Unit", "")).strip()
            if current_section and item and unit:
                section_counts[current_section] = section_counts.get(current_section, 0) + 1

        for level in levels:
            bq_lvl = bq.build_bq(element_list, level=level)
            sheet_name = _safe_sheet_name(f"BQ – {level}")
            bq_lvl.to_excel(writer, sheet_name=sheet_name, index=False)

    # 5) Build checks summary
    section_titles = {
        "H":  "Section H — Structural Steelwork",
        "11": "Section 11 — In-situ Concrete",
        "14": "Section 14 — Masonry",
        "17": "Section 17 — Waterproofing",
        "28": "Section 28 — Finishes",
    }

    checks = []
    crit = warn = ok = 0
    for sec_key, count in section_counts.items():
        title = section_titles[sec_key]
        if count > 0:
            checks.append({
                "label":    title,
                "severity": "OK",
                "summary":  f"{count} BQ items generated",
                "total":    count,
            })
            ok += 1
        else:
            checks.append({
                "label":    title,
                "severity": "OK",
                "summary":  "No applicable elements in model",
                "total":    0,
            })

    # Section 11 is mandatory for QS work — flag if empty
    if section_counts.get("11", 0) == 0:
        checks[1] = {
            "label":    section_titles["11"],
            "severity": "WARNING",
            "summary":  "No concrete elements found — Section 11 is empty",
            "total":    0,
        }
        warn += 1
        ok = max(0, ok - 1)

    return {
        "checks":  checks,
        "summary": {"critical": crit, "warning": warn, "ok": ok},
        "bq_draft_path": str(out_path),
    }
