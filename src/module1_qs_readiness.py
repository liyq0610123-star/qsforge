"""
Module 1 — QS Readiness Score
==============================
Reads the Module 0 output Excel (QS Element List sheet) and computes
a QS Readiness Score based on 8 dimensions.

Score Dimensions (total 100%):
  1. Level Coverage          20%  — elements with valid Level value
  2. Volume Coverage         20%  — elements with Volume > 0
  3. Material Completeness   15%  — elements with valid Structural Material
  4. Vertical Span           15%  — vertical elements spanning < 3 levels
  5. Dimension Anomaly       10%  — elements with thickness/width above min threshold
  6. Volume Anomaly          10%  — elements with Volume below 0.05 m³
  7. Unit Consistency         5%  — elements with Volume below per-category max
  8. Non-QS Family            5%  — Mass/Generic elements vs total Volume

Run: python module1_qs_readiness.py <path_to_module0_output_excel>
"""

import logging
import pandas as pd
import numpy as np
import sys
import os
from datetime import datetime

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

# Dimension weights (must sum to 100)
WEIGHTS = {
    "Level Coverage":         20,
    "Volume Coverage":        20,
    "Material Completeness":  15,
    "Vertical Span":          20,
    "Volume Anomaly":         10,
    "Unit Consistency":       10,
    "Non-QS Family":           5,
}

# Vertical categories (point + linear need span check)
VERTICAL_CATEGORIES = {
    "Structural Columns",
    "Walls",
    "Structural Foundation",
}

# Categories where dimension check applies
# (category display name → min thickness/width in mm)
DIMENSION_MIN_MM = {
    "Walls":                   50,
    "Floors":                  50,
    "Structural Foundation":   50,
}

# Per-category Volume upper limit for single instance (m³)
# Exceeding this = likely unit error (mm³ instead of m³)
VOLUME_MAX_M3 = {
    "Structural Columns":          500,
    "Structural Framing (Beams)":  100,
    "Walls":                     1000,
    "Floors":                    5000,
    "Structural Foundation":     2000,
}

# Volume lower limit — below this = likely modelling debris
VOLUME_MIN_M3 = 0.05

# Non-QS categories (Mass, Generic etc.)
NON_QS_CATEGORIES = {
    "OST_Mass",
    "OST_GenericModel",
    "OST_DetailComponents",
    "OST_EntourageRvt",
    "OST_Planting",
    "OST_Furniture",
    "OST_FurnitureSystems",
    "OST_SpecialityEquipment",
    "OST_MechanicalEquipment",
    "OST_ElectricalEquipment",
    "OST_LightingFixtures",
    "OST_Parking",
}

# Invalid material values
INVALID_MATERIALS = {"", "none", "default", "generic", "by category", "undefined"}

# Material classification keywords (case-insensitive)
STEEL_KEYWORDS    = [
    "steel", "s275", "s355", "s460", "s235", "grade 43", "grade 50",
    "fe 360", "fe 430", r"\buc\b", r"\bub\b", r"\bchs\b", r"\brhs\b", r"\bshs\b"
]
PRECAST_KEYWORDS  = [
    "precast", "pre-cast", "pre cast", r"\bpc\b", r"\bp/c\b", "prc", "precasted"
]
INSITU_KEYWORDS   = [
    "in situ", "in-situ", "insitu", "in_situ", "cast in situ",
    "cast-in-situ", "cast in place", r"\bcip\b"
]

def classify_material(raw):
    """
    Classify a material string into: steel / precast / insitu / missing / unclassified
    """
    import re
    if not raw or str(raw).strip().lower() in INVALID_MATERIALS:
        return "missing"
    s = str(raw).strip().lower()
    for kw in STEEL_KEYWORDS:
        if re.search(kw, s):
            return "steel"
    for kw in PRECAST_KEYWORDS:
        if re.search(kw, s):
            return "precast"
    for kw in INSITU_KEYWORDS:
        if re.search(kw, s):
            return "insitu"
    return "unclassified"

# DDC column names (as they appear in Module 0 output)
COL_ID         = "Element ID"
COL_CATEGORY   = "Category"
COL_LEVEL      = "Level"
COL_VOLUME     = "Volume (m³)"
COL_AREA       = "Area (m²)"
COL_MATERIAL   = "Structural Material : String"
COL_WIDTH      = "Width : Double"
COL_THICKNESS  = "Thickness : Double"
COL_TOP_LEVEL  = "Top Level : String"
COL_BASE_LEVEL = "Base Level : String"
COL_DQ         = "Data_Quality"


# ─────────────────────────────────────────────
# LOAD
# ─────────────────────────────────────────────

def load_module0(filepath):
    logger.info(f"\n{'='*60}")
    logger.info(f"Loading Module 0 output: {os.path.basename(filepath)}")
    logger.info(f"{'='*60}")

    df = pd.read_excel(filepath, sheet_name="QS Element List")
    logger.info(f"QS elements loaded: {len(df):,}")
    logger.info(f"Categories: {sorted(df[COL_CATEGORY].unique())}")

    # Load Non-QS Elements sheet if present
    try:
        non_qs_df = pd.read_excel(filepath, sheet_name="Non-QS Elements")
        logger.info(f"Non-QS elements loaded: {len(non_qs_df):,}")
    except Exception:
        non_qs_df = None
        logger.warning("  Non-QS Elements sheet not found — Non-QS Family check skipped")

    return df, non_qs_df


# ─────────────────────────────────────────────
# HELPER: build ordered level list from data
# ─────────────────────────────────────────────

def build_level_order(df):
    """
    Extract all level names from the dataset and sort them.
    Tries numeric sort first (B3, B2, B1, G, 1F, 2F...)
    Falls back to alphabetical.
    """
    levels = df[COL_LEVEL].dropna().unique()
    levels = [l for l in levels if l not in
              ("Level_Not_Assigned", "Level_Param_Missing")]

    def level_sort_key(name):
        name = str(name).strip()
        # Extract leading digits or negative numbers
        import re
        m = re.search(r'-?\d+', name)
        return int(m.group()) if m else 0

    try:
        sorted_levels = sorted(levels, key=level_sort_key)
    except Exception:
        sorted_levels = sorted(levels)

    level_index = {lvl: i for i, lvl in enumerate(sorted_levels)}
    return sorted_levels, level_index


# ─────────────────────────────────────────────
# DIMENSION 1: Level Coverage
# ─────────────────────────────────────────────

def check_level_coverage(df):
    total = len(df)
    valid = df[COL_LEVEL].notna() & ~df[COL_LEVEL].isin(
        ["Level_Not_Assigned", "Level_Param_Missing"]
    )
    coverage = valid.sum() / total if total > 0 else 0
    score = round(coverage * 100, 1)

    issues = df[~valid][[COL_ID, COL_CATEGORY, COL_LEVEL]].copy()
    issues["Issue"] = "Missing Level"

    return score, coverage, issues


# ─────────────────────────────────────────────
# DIMENSION 2: Volume Coverage
# ─────────────────────────────────────────────

def check_volume_coverage(df):
    total = len(df)
    vol = pd.to_numeric(df[COL_VOLUME], errors="coerce")
    valid = vol.notna() & (vol > 0)
    coverage = valid.sum() / total if total > 0 else 0
    score = round(coverage * 100, 1)

    issues = df[~valid][[COL_ID, COL_CATEGORY, COL_VOLUME]].copy()
    issues["Issue"] = "Missing or zero Volume"

    return score, coverage, issues


# ─────────────────────────────────────────────
# DIMENSION 3: Material Completeness
# ─────────────────────────────────────────────

def check_material_completeness(df):
    """
    Three-tier material classification:
      Valid (Steel/Precast/In-situ) → full score
      Unclassified (has value but unrecognised) → no score deduction but flagged
      Missing (empty/default/generic) → score deduction
    """
    structural = df[df[COL_CATEGORY].isin([
        "Walls", "Floors", "Structural Columns",
        "Structural Framing (Beams)", "Structural Foundation"
    ])].copy()

    if len(structural) == 0:
        return 100.0, 1.0, pd.DataFrame()

    if COL_MATERIAL not in df.columns:
        return None, None, pd.DataFrame()

    structural["_mat_class"] = structural[COL_MATERIAL].apply(classify_material)

    total        = len(structural)
    n_valid      = (structural["_mat_class"].isin(["steel", "precast", "insitu"])).sum()
    n_unclass    = (structural["_mat_class"] == "unclassified").sum()
    n_missing    = (structural["_mat_class"] == "missing").sum()

    # Score based on Valid only (Missing penalised, Unclassified warned)
    coverage = n_valid / total if total > 0 else 0
    score    = round(coverage * 100, 1)

    logger.info(f"\n  Material breakdown — "
          f"Valid: {n_valid} | Unclassified: {n_unclass} | Missing: {n_missing}")

    # Issues: Missing (error) + Unclassified (warning)
    missing_rows = structural[structural["_mat_class"] == "missing"][
        [COL_ID, COL_CATEGORY, COL_MATERIAL]].copy()
    missing_rows["Issue"] = "Missing or invalid Structural Material"

    unclass_rows = structural[structural["_mat_class"] == "unclassified"][
        [COL_ID, COL_CATEGORY, COL_MATERIAL]].copy()
    unclass_rows["Issue"] = ("Unclassified material — cannot determine Steel/Precast/In-situ; "
                             "formwork will be excluded in BQ Draft")

    issues = pd.concat([missing_rows, unclass_rows], ignore_index=True)

    return score, coverage, issues


# ─────────────────────────────────────────────
# DIMENSION 4: Vertical Span (>= 3 levels)
# ─────────────────────────────────────────────

def check_vertical_span(df, level_index):
    vertical = df[df[COL_CATEGORY].isin(VERTICAL_CATEGORIES)].copy()

    if len(vertical) == 0:
        return 100.0, 1.0, pd.DataFrame()

    if COL_TOP_LEVEL not in df.columns:
        return None, None, pd.DataFrame()

    def span_levels(row):
        base = str(row.get(COL_LEVEL, "")).strip()
        top  = str(row.get(COL_TOP_LEVEL, "")).strip()
        bi   = level_index.get(base)
        ti   = level_index.get(top)
        if bi is None or ti is None:
            return 0
        return abs(ti - bi)

    vertical["_span"] = vertical.apply(span_levels, axis=1)
    anomalous = vertical["_span"] >= 3
    ok_rate   = (~anomalous).sum() / len(vertical)
    score     = round(ok_rate * 100, 1)

    issues = vertical[anomalous][[COL_ID, COL_CATEGORY, COL_LEVEL,
                                   COL_TOP_LEVEL, "_span"]].copy()
    issues = issues.rename(columns={"_span": "Levels Spanned"})
    issues["Issue"] = "Vertical element spans >= 3 levels"

    return score, ok_rate, issues


# ─────────────────────────────────────────────
# DIMENSION 5: Dimension Anomaly
# ─────────────────────────────────────────────

def check_dimension_anomaly(df):
    applicable = df[df[COL_CATEGORY].isin(DIMENSION_MIN_MM.keys())].copy()

    if len(applicable) == 0:
        return 100.0, 1.0, pd.DataFrame()

    # Try actual DDC column names
    dim_col = None
    for col in ["[Type] Width : Double", "Width : Double", "Thickness : Double",
                COL_WIDTH, COL_THICKNESS]:
        if col in df.columns:
            dim_col = col
            break

    if dim_col is None:
        return None, None, pd.DataFrame()

    dim = pd.to_numeric(applicable[dim_col], errors="coerce")

    # DDC exports in mm — check if conversion needed
    # If median > 1000, likely in mm already
    if dim.median() > 1000:
        dim_mm = dim
    else:
        dim_mm = dim * 1000

    def min_threshold(cat):
        return DIMENSION_MIN_MM.get(cat, 0)

    thresholds = applicable[COL_CATEGORY].map(min_threshold)
    valid = dim_mm.notna() & (dim_mm >= thresholds)
    ok_rate = valid.sum() / len(applicable)
    score   = round(ok_rate * 100, 1)

    issues = applicable[~valid][[COL_ID, COL_CATEGORY, dim_col]].copy()
    issues[dim_col] = dim_mm[~valid].round(1)
    issues = issues.rename(columns={dim_col: "Dimension (mm)"})
    issues["Issue"] = "Dimension below minimum threshold"

    return score, ok_rate, issues


# ─────────────────────────────────────────────
# DIMENSION 6: Volume Anomaly (< 0.05 m³)
# ─────────────────────────────────────────────

def check_volume_anomaly(df):
    vol = pd.to_numeric(df[COL_VOLUME], errors="coerce")
    has_vol = vol.notna() & (vol > 0)
    applicable = df[has_vol].copy()
    vol_valid  = vol[has_vol]

    if len(applicable) == 0:
        return 100.0, 1.0, pd.DataFrame()

    anomalous = vol_valid < VOLUME_MIN_M3
    ok_rate   = (~anomalous).sum() / len(applicable)
    score     = round(ok_rate * 100, 1)

    issues = applicable[anomalous][[COL_ID, COL_CATEGORY, COL_VOLUME]].copy()
    issues["Issue"] = f"Volume < {VOLUME_MIN_M3} m³ (likely modelling debris)"

    return score, ok_rate, issues


# ─────────────────────────────────────────────
# DIMENSION 7: Unit Consistency
# ─────────────────────────────────────────────

def check_unit_consistency(df):
    vol = pd.to_numeric(df[COL_VOLUME], errors="coerce")
    has_vol = vol.notna() & (vol > 0)
    applicable = df[has_vol].copy()

    if len(applicable) == 0:
        return 100.0, 1.0, pd.DataFrame()

    def max_vol(cat):
        return VOLUME_MAX_M3.get(cat, 99999)

    maxes     = applicable[COL_CATEGORY].map(max_vol)
    vol_clean = vol[has_vol]
    anomalous = vol_clean > maxes
    ok_rate   = (~anomalous).sum() / len(applicable)
    score     = round(ok_rate * 100, 1)

    issues = applicable[anomalous][[COL_ID, COL_CATEGORY, COL_VOLUME]].copy()
    issues["Issue"] = "Volume exceeds category maximum — possible unit error (mm³ vs m³)"

    return score, ok_rate, issues


# ─────────────────────────────────────────────
# DIMENSION 8: Non-QS Family
# ─────────────────────────────────────────────

def check_non_qs_family(df, non_qs_df):
    """
    Checks Non-QS categories (Mass, Generic etc.) volume
    against total QS volume. Uses the Non-QS Elements sheet
    from Module 0 output which retains these rows.
    """
    qs_vol = pd.to_numeric(df[COL_VOLUME], errors="coerce").fillna(0).sum()

    if non_qs_df is None or len(non_qs_df) == 0:
        return 100.0, 1.0, pd.DataFrame()

    vol_col = "Volume (m³)" if "Volume (m³)" in non_qs_df.columns else COL_VOLUME
    non_qs_vol = pd.to_numeric(non_qs_df[vol_col], errors="coerce").fillna(0).sum()

    total_vol = qs_vol + non_qs_vol
    if total_vol == 0:
        return 100.0, 1.0, pd.DataFrame()

    bad_ratio = non_qs_vol / total_vol
    ok_rate   = 1 - bad_ratio
    score     = round(ok_rate * 100, 1)

    issues = non_qs_df.copy()
    issues["Issue"] = "Non-QS Family (Mass/Generic) with Volume — should not be in model"

    return score, ok_rate, issues


# ─────────────────────────────────────────────
# COMPUTE OVERALL SCORE
# ─────────────────────────────────────────────

def compute_score(results):
    """
    Weighted average of all dimension scores.
    Dimensions with None score (missing column) are excluded
    and their weights redistributed proportionally.
    """
    valid = {k: v for k, v in results.items() if v["score"] is not None}
    total_weight = sum(WEIGHTS[k] for k in valid)

    weighted_sum = sum(
        v["score"] * WEIGHTS[k] / total_weight
        for k, v in valid.items()
    )
    return round(weighted_sum, 1)


def score_label(score):
    if score >= 90: return "Excellent ✅"
    if score >= 75: return "Good 🟡"
    if score >= 60: return "Fair 🟠"
    return "Poor ❌"


# ─────────────────────────────────────────────
# BUILD OUTPUT SHEETS
# ─────────────────────────────────────────────

def build_scorecard(results, overall_score):
    rows = []
    for dim, data in results.items():
        score = data["score"]
        rows.append({
            "Dimension":       dim,
            "Weight (%)":      WEIGHTS[dim],
            "Score (%)":       score if score is not None else "N/A",
            "Weighted Score":  round(score * WEIGHTS[dim] / 100, 2) if score is not None else "N/A",
            "Status":          score_label(score) if score is not None else "⚠️ Column Missing",
            "Issues Found":    len(data["issues"]),
        })

    df = pd.DataFrame(rows)

    # Add overall row
    summary = pd.DataFrame([{
        "Dimension":      "OVERALL QS READINESS",
        "Weight (%)":     100,
        "Score (%)":      overall_score,
        "Weighted Score": overall_score,
        "Status":         score_label(overall_score),
        "Issues Found":   sum(len(d["issues"]) for d in results.values()),
    }])

    return pd.concat([df, summary], ignore_index=True)


def build_issues(results):
    all_issues = []
    for dim, data in results.items():
        if len(data["issues"]) > 0:
            iss = data["issues"].copy()
            iss.insert(0, "Dimension", dim)
            all_issues.append(iss)

    if not all_issues:
        return pd.DataFrame(columns=["Dimension", COL_ID, COL_CATEGORY, "Issue"])

    return pd.concat(all_issues, ignore_index=True)


# ─────────────────────────────────────────────
# EXPORT
# ─────────────────────────────────────────────

def export(scorecard, issues_df, input_path):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    base      = os.path.splitext(os.path.basename(input_path))[0]
    # Remove Module0 suffix if present
    base      = base.replace("_Module0", "")
    out_path  = os.path.join(os.path.dirname(os.path.abspath(input_path)),
                             f"{base}_Module1_{timestamp}.xlsx")

    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        scorecard.to_excel(writer, sheet_name="QS Readiness Score", index=False)
        issues_df.to_excel(writer, sheet_name="Issues Detail",      index=False)

    logger.info(f"\n{'='*60}")
    logger.info(f"Output saved: {out_path}")
    logger.info(f"  Sheet 1 — QS Readiness Score: {len(scorecard)} dimensions")
    logger.info(f"  Sheet 2 — Issues Detail:      {len(issues_df):,} issues")
    logger.info(f"{'='*60}\n")
    return out_path


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        logger.error("Usage: python module1_qs_readiness.py <path_to_module0_excel>")
        sys.exit(1)

    filepath = sys.argv[1]
    if not os.path.exists(filepath):
        logger.error(f"File not found: {filepath}")
        sys.exit(1)

    df, non_qs_df = load_module0(filepath)
    sorted_levels, level_index = build_level_order(df)

    logger.info(f"\nLevel order detected: {sorted_levels}")

    # Run all dimensions
    results = {}

    score, rate, issues = check_level_coverage(df)
    results["Level Coverage"] = {"score": score, "rate": rate, "issues": issues}

    score, rate, issues = check_volume_coverage(df)
    results["Volume Coverage"] = {"score": score, "rate": rate, "issues": issues}

    score, rate, issues = check_material_completeness(df)
    results["Material Completeness"] = {"score": score, "rate": rate, "issues": issues}

    score, rate, issues = check_vertical_span(df, level_index)
    results["Vertical Span"] = {"score": score, "rate": rate, "issues": issues}

    score, rate, issues = check_volume_anomaly(df)
    results["Volume Anomaly"] = {"score": score, "rate": rate, "issues": issues}

    score, rate, issues = check_unit_consistency(df)
    results["Unit Consistency"] = {"score": score, "rate": rate, "issues": issues}

    score, rate, issues = check_non_qs_family(df, non_qs_df)
    results["Non-QS Family"] = {"score": score, "rate": rate, "issues": issues}

    # Overall score
    overall = compute_score(results)

    # Print summary
    logger.info(f"\n{'='*60}")
    logger.info(f"QS READINESS SCORE SUMMARY")
    logger.info(f"{'='*60}")
    for dim, data in results.items():
        s = data["score"]
        label = score_label(s) if s is not None else "N/A"
        logger.info(f"  {dim:<30} {str(s):>6}%   {label}  ({len(data['issues'])} issues)")
    logger.info(f"{'='*60}")
    logger.info(f"  {'OVERALL':.<30} {overall:>6}%   {score_label(overall)}")
    logger.info(f"{'='*60}\n")

    # Build and export
    scorecard = build_scorecard(results, overall)
    issues_df = build_issues(results)
    export(scorecard, issues_df, filepath)


if __name__ == "__main__":
    main()
