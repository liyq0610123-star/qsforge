"""
Module 0 — DDC Data Structuring for QS Review
==============================================
Parses DDC (DataDrivenConstruction) Excel export and produces
a QS-readable structured output with 3 sheets:
  Sheet 1 - QS Element List (full detail, sortable)
  Sheet 2 - Summary by Level x Category
  Sheet 3 - Data Quality Issues (for BIM team)

Column names are based on real DDC output analysis.
Run: python module0_inventory.py <path_to_ddc_excel>
"""

import logging
import pandas as pd
import numpy as np
import sys
import os
from datetime import datetime
from pathlib import Path
from collections import defaultdict

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# CONFIG: DDC column names (verified from real DDC output)
# ─────────────────────────────────────────────

# Maps OST category → the correct DDC column for Level
LEVEL_PARAM_BY_CATEGORY = {
    "OST_Walls":                "Base Constraint : String",
    "OST_StructuralColumns":    "Base Level : String",
    "OST_StructuralFraming":    "Reference Level : String",
    "OST_Floors":               "Level : String",
    "OST_StructuralFoundation": "Level : String",
    "OST_Roofs":                "Base Level : String",
    "OST_Ceilings":             "Level : String",
    "OST_Stairs":               "Base Level : String",
    "OST_StairsRuns":           None,   # No level param in DDC
    "OST_StairsLandings":       None,   # No level param in DDC
}

# Human-readable display names for QS output
CATEGORY_DISPLAY = {
    "OST_Walls":                "Walls",
    "OST_StructuralColumns":    "Structural Columns",
    "OST_StructuralFraming":    "Structural Framing (Beams)",
    "OST_Floors":               "Floors",
    "OST_StructuralFoundation": "Structural Foundation",
    "OST_Roofs":                "Roofs",
    "OST_Ceilings":             "Ceilings",
    "OST_Stairs":               "Stairs",
    "OST_StairsRuns":           "Stair Runs",
    "OST_StairsLandings":       "Stair Landings",
}

QS_CATEGORIES = set(LEVEL_PARAM_BY_CATEGORY.keys())

# QSForge server / PDF expect these sets (aligned with legacy Module 0).
WARNING_CATEGORIES = frozenset({
    "OST_GenericModel",
    "OST_MassWallsAll",
    "OST_MassFloorsAll",
    "OST_MassGlazingAll",
    "OST_MassRoof",
    "OST_Mass",
})
VOLUMETRIC_CATEGORIES = frozenset({
    "OST_Walls", "OST_Floors", "OST_Roofs", "OST_StructuralColumns",
    "OST_StructuralFraming", "OST_StructuralFoundation", "OST_Ceilings",
})


class ParserError(Exception):
    """Raised when a DDC Excel file cannot be parsed for QSForge."""

# DDC column names for key QS parameters
COL_ID       = "ID"
COL_CATEGORY = "Category : String"
COL_FAMILY   = "Family : String"
COL_TYPE     = "Type Name : String"
COL_VOLUME   = "Volume : Double"
COL_AREA     = "Area : Double"


# ─────────────────────────────────────────────
# STEP 1: LOAD
# ─────────────────────────────────────────────

def _prepare_instance_df(filepath):
    """
    Read DDC workbook, dedupe column labels, drop definition / null-ID rows.
    Returns (df, stats).
    """
    df = pd.read_excel(filepath)
    raw_rows = len(df)
    if COL_ID not in df.columns:
        raise ParserError(f"Required column {COL_ID!r} not found in Excel.")

    seen = {}
    new_cols = []
    for col in df.columns:
        if col in seen:
            seen[col] += 1
            new_cols.append(f"{col}_dup{seen[col]}")
        else:
            seen[col] = 0
            new_cols.append(col)
    df.columns = new_cols

    before = len(df)
    df = df[df[COL_ID].notna() & (df[COL_ID] != 0)].copy()
    df[COL_ID] = df[COL_ID].astype(int)
    dropped_ids = before - len(df)
    return df, {
        "raw_rows": raw_rows,
        "rows_after_id_filter": len(df),
        "skipped_no_category": dropped_ids,
        "total_columns": len(new_cols),
    }


def load_ddc(filepath):
    logger.info(f"\n{'='*60}")
    logger.info(f"Loading: {os.path.basename(filepath)}")
    logger.info(f"{'='*60}")

    df, stats = _prepare_instance_df(filepath)
    logger.info(f"Raw rows: {stats['raw_rows']:,}  |  Columns: {stats['total_columns']}")
    logger.info(
        f"After removing null/zero IDs: {stats['rows_after_id_filter']:,} rows "
        f"(removed {stats['skipped_no_category']})"
    )

    return df


# ─────────────────────────────────────────────
# STEP 2: FILTER NON-QS CATEGORIES
# ─────────────────────────────────────────────

def tag_qs_categories(df, *, verbose=True):
    """
    Instead of filtering, tag each row as QS or Non-QS.
    Is_QS_Element = True  → structural/architectural QS element
    Is_QS_Element = False → Mass, Generic, SketchLines etc.
    Both kept so Module 1 can detect Non-QS Family volume.
    """
    df = df.copy()
    df["Is_QS_Element"] = df[COL_CATEGORY].isin(QS_CATEGORIES)

    qs_count     = df["Is_QS_Element"].sum()
    non_qs_count = (~df["Is_QS_Element"]).sum()

    if verbose:
        logger.info(f"\n{'='*60}")
        logger.info(f"Category Tagging")
        logger.info(f"{'='*60}")
        logger.info(f"QS elements:     {qs_count:,} rows")
        logger.info(f"Non-QS elements: {non_qs_count:,} rows ({df[~df['Is_QS_Element']][COL_CATEGORY].nunique()} categories)")
        logger.info(f"\nTop non-QS categories:")
        logger.info(df[~df["Is_QS_Element"]][COL_CATEGORY].value_counts().head(10).to_string())

    return df


# ─────────────────────────────────────────────
# STEP 2b: FILTER NON-INSTANCES (Phase Created check)
# ─────────────────────────────────────────────

def filter_non_instances(df, *, verbose=True):
    """
    In Revit, every placed instance MUST have a Phase Created value.
    Rows with empty Phase Created are Family definitions, system elements,
    or corrupt data — not real instances. Remove them entirely.
    """
    COL_PHASE = "Phase Created : String"

    if COL_PHASE not in df.columns:
        if verbose:
            logger.warning(f"\n  WARNING: '{COL_PHASE}' column not found — skipping instance filter")
        return df.copy(), pd.DataFrame()

    has_phase = (
        df[COL_PHASE].notna() &
        (df[COL_PHASE].astype(str).str.strip() != "") &
        (df[COL_PHASE].astype(str).str.strip() != "None")
    )

    clean_df = df[has_phase].copy()
    empty_df = df[~has_phase].copy()

    if verbose:
        logger.info(f"\n{'='*60}")
        logger.info(f"Instance Filter (Phase Created)")
        logger.info(f"{'='*60}")
        logger.info(f"Real instances kept: {len(clean_df):,}")
        logger.info(f"Non-instances removed: {len(empty_df):,} (Phase Created is empty)")

    return clean_df, empty_df


# ─────────────────────────────────────────────
# STEP 3: ASSIGN QS_LEVEL PER CATEGORY
# ─────────────────────────────────────────────

def assign_qs_level(df, *, verbose=True):
    df = df.copy()
    df["QS_Level"] = "Level_Not_Assigned"

    # Only assign levels for QS elements
    for cat, level_col in LEVEL_PARAM_BY_CATEGORY.items():
        mask = df[COL_CATEGORY] == cat

        if level_col is None:
            df.loc[mask, "QS_Level"] = "Level_Param_Missing"
            continue

        if level_col not in df.columns:
            df.loc[mask, "QS_Level"] = "Level_Param_Missing"
            if verbose:
                logger.warning(f"  WARNING: Expected column '{level_col}' not found for {cat}")
            continue

        has_level = (
            df[level_col].notna() &
            (df[level_col].astype(str).str.strip() != "") &
            (df[level_col].astype(str).str.strip() != "None")
        )

        df.loc[mask & has_level, "QS_Level"] = df.loc[mask & has_level, level_col].astype(str)

    # Non-QS elements get a special level tag
    df.loc[~df["Is_QS_Element"], "QS_Level"] = "Non_QS_Element"

    return df


# ─────────────────────────────────────────────
# STEP 4: DATA QUALITY FLAGS
# ─────────────────────────────────────────────

def assign_data_quality(df, *, verbose=True):
    df = df.copy()

    # Volume validity
    if COL_VOLUME in df.columns:
        has_vol = df[COL_VOLUME].notna() & (pd.to_numeric(df[COL_VOLUME], errors="coerce") > 0)
    else:
        has_vol = pd.Series(False, index=df.index)

    has_level = ~df["QS_Level"].isin(["Level_Not_Assigned", "Level_Param_Missing"])

    conditions = [
        has_level & has_vol,
        ~has_level & has_vol,
        has_level & ~has_vol,
        ~has_level & ~has_vol,
    ]
    labels = ["Clean", "Missing_Level", "Missing_Volume", "Missing_Both"]
    df["Data_Quality"] = np.select(conditions, labels, default="Unknown")

    if verbose:
        logger.info(f"\n{'='*60}")
        logger.info(f"Data Quality Summary")
        logger.info(f"{'='*60}")
        logger.info(df["Data_Quality"].value_counts().to_string())

    return df


# ─────────────────────────────────────────────
# QSForge JSON API — used by server.py (Module 0 contract)
# ─────────────────────────────────────────────

def _pct(n, total):
    return (n / total * 100.0) if total else 0.0


def parse(filepath, do_export: bool = False):
    """Return the Module 0 dict consumed by Flask scoring + the desktop UI.

    When *do_export* is True, also writes a Module 0 Excel file alongside
    the source xlsx and includes its path as ``module0_export_path`` in the
    result.  Errors during export are silenced so the main analysis always
    completes.
    """
    src = Path(filepath)
    if not src.is_file():
        raise ParserError(f"Excel file not found: {src}")

    df, stats = _prepare_instance_df(filepath)
    df = tag_qs_categories(df, verbose=False)
    df, _ = filter_non_instances(df, verbose=False)
    df = assign_qs_level(df, verbose=False)
    df = assign_data_quality(df, verbose=False)

    qs_df = df[df["Is_QS_Element"]].copy()
    non_qs_df = df[~df["Is_QS_Element"]].copy()
    skipped_non_qs = int((~df["Is_QS_Element"]).sum())

    all_categories = (
        df[COL_CATEGORY].value_counts().astype(int).to_dict()
    )
    all_categories = {str(k): int(v) for k, v in all_categories.items()}

    no_level_mask = qs_df["QS_Level"].isin(
        ["Level_Not_Assigned", "Level_Param_Missing"]
    )

    COL_LEN = "Length : Double"

    categories = []
    cat_totals = {}

    for cat_key, grp in qs_df.groupby(COL_CATEGORY):
        n = len(grp)
        nl = int(no_level_mask.loc[grp.index].sum())

        vol = pd.to_numeric(grp[COL_VOLUME], errors="coerce") if COL_VOLUME in grp.columns else pd.Series(np.nan, index=grp.index)
        if vol.notna().any():
            med = vol.median()
            if pd.notna(med) and med > 1000:
                vol = vol / 1e9
        vol_valid = vol.notna() & (vol > 0)
        vol_count = int(vol_valid.sum())
        vol_sum = float(vol[vol_valid].sum())

        area = pd.to_numeric(grp[COL_AREA], errors="coerce") if COL_AREA in grp.columns else pd.Series(np.nan, index=grp.index)
        if area.notna().any():
            med_a = area.median()
            if pd.notna(med_a) and med_a > 10000:
                area = area / 1e6
        area_valid = area.notna() & (area > 0)
        area_count = int(area_valid.sum())
        area_sum = float(area[area_valid].sum())

        le_seq = pd.Series(0.0, index=grp.index)
        len_count = 0
        if COL_LEN in grp.columns:
            le_seq = pd.to_numeric(grp[COL_LEN], errors="coerce")
            len_valid = le_seq.notna() & (le_seq > 0)
            len_count = int(len_valid.sum())
            len_sum = float(le_seq[len_valid].sum())
        else:
            len_sum = 0.0

        cat_totals[cat_key] = {
            "count": n, "no_level_count": nl,
            "vol_count": vol_count, "vol": vol_sum,
            "area_count": area_count, "area": area_sum,
            "len_count": len_count, "len": len_sum,
        }

        label = CATEGORY_DISPLAY.get(cat_key, str(cat_key).replace("OST_", ""))
        categories.append({
            "key": cat_key,
            "label": label,
            "count": n,
            "volume": {
                "total": round(vol_sum, 3),
                "count": vol_count,
                "coverage_pct": round(_pct(vol_count, n), 1),
            },
            "area": {
                "total": round(area_sum, 3),
                "count": area_count,
                "coverage_pct": round(_pct(area_count, n), 1),
            },
            "length": {
                "total": round(len_sum, 3),
                "count": len_count,
                "coverage_pct": round(_pct(len_count, n), 1),
            },
            "no_level_count": nl,
            "no_level_pct": round(_pct(nl, n), 1),
            "is_warning_category": cat_key in WARNING_CATEGORIES,
            "is_volumetric": cat_key in VOLUMETRIC_CATEGORIES,
        })

    categories.sort(key=lambda c: c["label"].lower())

    plain_tree = {}
    for cat_key, grp in qs_df.groupby(COL_CATEGORY):
        plain_tree[cat_key] = {}
        for lv, g2 in grp.groupby("QS_Level"):
            lv_s = str(lv)
            plain_tree[cat_key][lv_s] = {}
            for typ, g3 in g2.groupby(COL_TYPE):
                typ_s = str(typ if typ is not None else "Unknown")
                vol = pd.to_numeric(g3[COL_VOLUME], errors="coerce") if COL_VOLUME in g3.columns else pd.Series(dtype=float)
                if vol.notna().any():
                    mv = vol.median()
                    if pd.notna(mv) and mv > 1000:
                        vol = vol / 1e9
                vok = vol.notna() & (vol > 0)
                area = pd.to_numeric(g3[COL_AREA], errors="coerce") if COL_AREA in g3.columns else pd.Series(dtype=float)
                if area.notna().any():
                    ma = area.median()
                    if pd.notna(ma) and ma > 10000:
                        area = area / 1e6
                aok = area.notna() & (area > 0)
                le = pd.to_numeric(g3[COL_LEN], errors="coerce") if COL_LEN in g3.columns else pd.Series(dtype=float)
                lok = le.notna() & (le > 0)
                plain_tree[cat_key][lv_s][typ_s] = {
                    "count":      len(g3),
                    "vol":        round(float(vol[vok].sum()), 3),
                    "area":       round(float(area[aok].sum()), 3),
                    "len":        round(float(le[lok].sum()), 3),
                    "vol_count":  int(vok.sum()),
                    "area_count": int(aok.sum()),
                    "len_count":  int(lok.sum()),
                }

    mass_detected = {
        c: all_categories.get(c, 0)
        for c in WARNING_CATEGORIES
        if all_categories.get(c, 0) > 0
    }

    def _groups_for(mask, max_groups=20, ids_per_group=50):
        """Return Family+Type groups for elements in qs_df matching *mask*.

        Each group: {family, type, count, ids} (largest first).
        """
        try:
            sub = qs_df[mask].copy()
            if len(sub) == 0:
                return []
            fam = sub[COL_FAMILY].fillna("(no family)").astype(str) if COL_FAMILY in sub.columns else pd.Series("(no family)", index=sub.index)
            typ = sub[COL_TYPE].fillna("(no type)").astype(str) if COL_TYPE in sub.columns else pd.Series("(no type)", index=sub.index)
            sub = sub.assign(_fam=fam, _typ=typ)
            groups = []
            for (f, t), grp in sub.groupby(["_fam", "_typ"], dropna=False):
                ids = pd.to_numeric(grp[COL_ID], errors="coerce").dropna().astype(int).tolist()
                if not ids:
                    continue
                groups.append({
                    "family": f or "(no family)",
                    "type":   t or "(no type)",
                    "count":  int(len(grp)),
                    "ids":    ids[:ids_per_group],
                })
            groups.sort(key=lambda g: (-g["count"], g["family"], g["type"]))
            return groups[:max_groups]
        except Exception:
            return []

    vol_col_present = COL_VOLUME in qs_df.columns
    no_vol_mask = pd.Series(False, index=qs_df.index)
    if vol_col_present:
        _vol = pd.to_numeric(qs_df[COL_VOLUME], errors="coerce")
        no_vol_mask = _vol.isna() | (_vol <= 0)

    issues = []
    for c in categories:
        ck = c["key"]
        label = c["label"]
        ct = cat_totals[ck]
        if ct["count"] == 0:
            continue
        cat_mask = qs_df[COL_CATEGORY] == ck
        if ct["no_level_count"] == ct["count"]:
            issues.append({
                "severity": "CRITICAL",
                "category_key": ck,
                "category_label": label,
                "message": "0% of entities have Level assigned",
                "groups": _groups_for(cat_mask & no_level_mask),
                "total_affected": ct["no_level_count"],
            })
        elif ct["no_level_count"] > 0:
            issues.append({
                "severity": "WARNING",
                "category_key": ck,
                "category_label": label,
                "message": f"{_pct(ct['no_level_count'], ct['count']):.0f}% of entities missing Level",
                "groups": _groups_for(cat_mask & no_level_mask),
                "total_affected": ct["no_level_count"],
            })
        if ck in VOLUMETRIC_CATEGORIES and ct["vol_count"] == 0:
            issues.append({
                "severity": "CRITICAL",
                "category_key": ck,
                "category_label": label,
                "message": "No Volume data — cannot calculate quantities",
                "groups": _groups_for(cat_mask & no_vol_mask),
                "total_affected": ct["count"],
            })
        elif ck in VOLUMETRIC_CATEGORIES and ct["vol_count"] < ct["count"]:
            miss = ct["count"] - ct["vol_count"]
            issues.append({
                "severity": "WARNING",
                "category_key": ck,
                "category_label": label,
                "message": f"{_pct(miss, ct['count']):.0f}% of entities missing Volume",
                "groups": _groups_for(cat_mask & no_vol_mask),
                "total_affected": miss,
            })
        if ck == "OST_GenericModel" and ct["count"] > 0:
            issues.append({
                "severity": "WARNING",
                "category_key": ck,
                "category_label": label,
                "message": f"{ct['count']} Generic Models found — unclassified elements, review required",
                "groups": _groups_for(cat_mask),
                "total_affected": ct["count"],
            })

    flags = {
        "has_critical": any(i["severity"] == "CRITICAL" for i in issues),
        "has_warning": any(i["severity"] == "WARNING" for i in issues),
    }

    # Per-element list — needed by Module 3's 3D viewer for click-to-inspect,
    # color-by-family/category, and category filter. We project a small set
    # of columns (id + identity + geometry) to keep the JSON payload bounded
    # for large models. Translates Revit OST_* category keys to human
    # display names so the frontend doesn't need its own mapping.
    _id_col      = COL_ID
    _level_col   = COL_LEVEL_OUT  if 'COL_LEVEL_OUT' in globals() else "Level"
    _family_col  = COL_FAMILY
    _type_col    = COL_TYPE
    _vol_col     = COL_VOLUME
    _area_col    = COL_AREA
    _mat_col     = "Structural Material : String"
    _wall_w_col  = "Width : Double"
    _thick_col   = "Thickness : Double"
    _length_col  = "Length : Double"
    _dq_col      = "Data_Quality"
    qs_element_list = []
    try:
        for _, row in qs_df.iterrows():
            cat_key = row.get(COL_CATEGORY)
            cat_label = CATEGORY_DISPLAY.get(cat_key, str(cat_key) if cat_key else "")
            entry = {
                "Element ID": int(row[_id_col]) if not pd.isna(row.get(_id_col)) else None,
                "Category":   cat_label,
                "Family":     str(row.get(_family_col, "")) if not pd.isna(row.get(_family_col)) else "",
                "Type Name":  str(row.get(_type_col,   "")) if not pd.isna(row.get(_type_col))   else "",
                "Level":      str(row.get(_level_col,  "")) if not pd.isna(row.get(_level_col))  else "",
            }
            for k_in, k_out in [
                (_vol_col, "Volume (m³)"),
                (_area_col, "Area (m²)"),
                (_length_col, "Length (m)"),
                (_wall_w_col, "Width (mm)"),
                (_thick_col, "Thickness (mm)"),
            ]:
                if k_in in qs_df.columns:
                    v = row.get(k_in)
                    if pd.notna(v):
                        try:
                            entry[k_out] = float(v)
                        except (TypeError, ValueError):
                            pass
            if _mat_col in qs_df.columns:
                m = row.get(_mat_col)
                if pd.notna(m) and str(m).strip():
                    entry["Structural Material"] = str(m)
            if _dq_col in qs_df.columns:
                dq = row.get(_dq_col)
                if pd.notna(dq) and str(dq).strip():
                    entry["Data_Quality"] = str(dq)
            qs_element_list.append(entry)
    except Exception:
        # Element list is additive — never block the analysis on serialisation.
        qs_element_list = []

    return {
        "file": {
            "path": str(src.resolve()),
            "sheet_name": "",
            "total_columns": stats["total_columns"],
            "total_rows": stats["raw_rows"],
            "skipped_no_category": stats["skipped_no_category"],
            "skipped_non_qs": skipped_non_qs,
            "qs_entity_count": int(len(qs_df)),
            "unique_categories_total": len(all_categories),
        },
        "categories": categories,
        "tree": plain_tree,
        "all_categories": all_categories,
        "mass_detected": mass_detected,
        "issues": issues,
        "flags": flags,
        "qs_element_list": qs_element_list,
        "module0_export_path": _do_export(filepath, qs_df, non_qs_df) if do_export else None,
    }


def _do_export(filepath, qs_df, non_qs_df):
    """Run export_server(); return path string or None on failure."""
    try:
        return str(export_server(str(filepath), qs_df, non_qs_df))
    except Exception:
        return None


# ─────────────────────────────────────────────
# STEP 5: BUILD OUTPUT SHEETS
# ─────────────────────────────────────────────

def build_element_list(df):
    """Sheet 1: Full element list, sorted for QS reading."""
    df = df.copy()
    df["Category_Display"] = df[COL_CATEGORY].map(CATEGORY_DISPLAY)

    # Core QS columns only (DDC has 1000+ columns — keep it readable)
    core_cols = [
        "QS_Level", "Category_Display", COL_FAMILY, COL_TYPE, COL_ID,
        COL_VOLUME, COL_AREA, "Data_Quality"
    ]
    # Add a small set of useful supplementary columns if they exist
    supplementary = [
        "Base Level : String", "Top Level : String",
        "Base Offset : Double", "Top Offset : Double",
        "Workset : String", "Design Option : String",
        "Phase Created : String", "Mark : String",
        "Structural Material : String", "Material Grade : String",
        "[Type] Width : Double",
        "UniqueId : String",
    ]
    extra_cols = [c for c in supplementary if c in df.columns and c not in core_cols]
    out = df[core_cols + extra_cols].copy()

    # Rename for QS readability
    out = out.rename(columns={
        "QS_Level":       "Level",
        "Category_Display": "Category",
        COL_FAMILY:       "Family",
        COL_TYPE:         "Type Name",
        COL_ID:           "Element ID",
        COL_VOLUME:       "Volume (m³)",
        COL_AREA:         "Area (m²)",
    })

    # Sort: Level → Category → Family → Type
    sort_cols = ["Level", "Category", "Family", "Type Name"]
    sort_cols = [c for c in sort_cols if c in out.columns]
    out = out.sort_values(sort_cols, na_position="last").reset_index(drop=True)

    # Convert volume from mm³ to m³ if values look like mm³ (DDC exports in mm)
    if "Volume (m³)" in out.columns:
        vol = pd.to_numeric(out["Volume (m³)"], errors="coerce")
        if vol.median() > 1000:  # likely in mm³ or mm² — convert
            out["Volume (m³)"] = (vol / 1e9).round(3)
        else:
            out["Volume (m³)"] = vol.round(3)

    if "Area (m²)" in out.columns:
        area = pd.to_numeric(out["Area (m²)"], errors="coerce")
        if area.median() > 10000:
            out["Area (m²)"] = (area / 1e6).round(1)
        else:
            out["Area (m²)"] = area.round(1)

    return out


def build_summary(df):
    """Sheet 2: Summary by Level x Category."""
    df = df.copy()
    df["Category_Display"] = df[COL_CATEGORY].map(CATEGORY_DISPLAY)

    if COL_VOLUME in df.columns:
        vol = pd.to_numeric(df[COL_VOLUME], errors="coerce")
        if vol.median() > 1000:
            df["_vol"] = vol / 1e9
        else:
            df["_vol"] = vol
    else:
        df["_vol"] = np.nan

    if COL_AREA in df.columns:
        area = pd.to_numeric(df[COL_AREA], errors="coerce")
        if area.median() > 10000:
            df["_area"] = area / 1e6
        else:
            df["_area"] = area
    else:
        df["_area"] = np.nan

    has_level = ~df["QS_Level"].isin(["Level_Not_Assigned", "Level_Param_Missing"])
    has_vol   = df["_vol"].notna() & (df["_vol"] > 0)

    summary = df.groupby(["QS_Level", "Category_Display"], sort=True).agg(
        Count        = (COL_ID, "count"),
        Total_Volume = ("_vol", "sum"),
        Total_Area   = ("_area", "sum"),
    ).reset_index()

    # Coverage per group
    level_ok = df[has_level].groupby(["QS_Level", "Category_Display"]).size().reset_index(name="_level_ok")
    vol_ok   = df[has_vol].groupby(["QS_Level", "Category_Display"]).size().reset_index(name="_vol_ok")

    summary = summary.merge(level_ok, on=["QS_Level", "Category_Display"], how="left")
    summary = summary.merge(vol_ok,   on=["QS_Level", "Category_Display"], how="left")
    summary["_level_ok"] = summary["_level_ok"].fillna(0)
    summary["_vol_ok"]   = summary["_vol_ok"].fillna(0)

    summary["Level Coverage %"]  = (summary["_level_ok"] / summary["Count"] * 100).round(0).astype(int)
    summary["Volume Coverage %"] = (summary["_vol_ok"]   / summary["Count"] * 100).round(0).astype(int)
    summary["Total_Volume"]      = summary["Total_Volume"].round(2)
    summary["Total_Area"]        = summary["Total_Area"].round(0)

    summary = summary.rename(columns={
        "QS_Level":         "Level",
        "Category_Display": "Category",
        "Total_Volume":     "Volume (m³)",
        "Total_Area":       "Area (m²)",
    })

    return summary[["Level", "Category", "Count", "Level Coverage %",
                    "Volume Coverage %", "Volume (m³)", "Area (m²)"]]


def build_issues(df):
    """Sheet 3: Data quality issues for BIM team."""
    df = df.copy()
    df["Category_Display"] = df[COL_CATEGORY].map(CATEGORY_DISPLAY)

    issues = df[df["Data_Quality"] != "Clean"][[
        COL_ID, "Category_Display", COL_TYPE, COL_FAMILY,
        "QS_Level", COL_VOLUME, COL_AREA, "Data_Quality"
    ]].copy()

    issues = issues.rename(columns={
        COL_ID:             "Element ID",
        "Category_Display": "Category",
        COL_TYPE:           "Type Name",
        COL_FAMILY:         "Family",
        "QS_Level":         "Level Status",
        COL_VOLUME:         "Volume",
        COL_AREA:           "Area",
    })

    # Add remediation hint
    hints = {
        "Missing_Level":   "Check element's Level/Base Constraint in Revit",
        "Missing_Volume":  "Check element's geometry — Volume parameter is empty",
        "Missing_Both":    "Element has no Level and no Volume — review in Revit",
    }
    issues["Recommended Action"] = issues["Data_Quality"].map(hints)

    return issues.sort_values(["Data_Quality", "Category"]).reset_index(drop=True)


# ─────────────────────────────────────────────
# STEP 6: EXPORT
# ─────────────────────────────────────────────

def export_server(xlsx_path: str, qs_df, non_qs_df) -> str:
    """
    Generate Module 0 structured Excel alongside the source DDC xlsx.
    Called by server.py after parse() so users can open the full element list.
    Returns the output path.
    """
    element_list = build_element_list(qs_df)
    summary      = build_summary(qs_df)
    issues_df    = build_issues(qs_df)
    return export(element_list, summary, issues_df, non_qs_df, xlsx_path)


def export(element_list, summary, issues, non_qs_df, input_path):
    timestamp  = datetime.now().strftime("%Y%m%d_%H%M")
    base_name  = os.path.splitext(os.path.basename(input_path))[0]
    out_path   = os.path.join(os.path.dirname(os.path.abspath(input_path)),
                              f"{base_name}_Module0_{timestamp}.xlsx")

    # Non-QS sheet: keep key columns only
    non_qs_out = non_qs_df[[COL_ID, COL_CATEGORY, COL_FAMILY, COL_TYPE, COL_VOLUME, COL_AREA]].copy()
    non_qs_out = non_qs_out.rename(columns={
        COL_ID:       "Element ID",
        COL_CATEGORY: "Category (OST)",
        COL_FAMILY:   "Family",
        COL_TYPE:     "Type Name",
        COL_VOLUME:   "Volume (m³)",
        COL_AREA:     "Area (m²)",
    })

    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        element_list.to_excel(writer, sheet_name="QS Element List",    index=False)
        summary.to_excel(writer,      sheet_name="Summary",             index=False)
        issues.to_excel(writer,       sheet_name="Data Quality Issues", index=False)
        non_qs_out.to_excel(writer,   sheet_name="Non-QS Elements",     index=False)

    logger.info(f"\n{'='*60}")
    logger.info(f"Output saved: {out_path}")
    logger.info(f"  Sheet 1 — QS Element List:      {len(element_list):,} rows")
    logger.info(f"  Sheet 2 — Summary:              {len(summary):,} rows")
    logger.info(f"  Sheet 3 — Data Quality Issues:  {len(issues):,} rows")
    logger.info(f"  Sheet 4 — Non-QS Elements:      {len(non_qs_out):,} rows")
    logger.info(f"{'='*60}\n")
    return out_path


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        logger.error("Usage: python module0_inventory.py <path_to_ddc_excel>")
        sys.exit(1)

    filepath = sys.argv[1]
    if not os.path.exists(filepath):
        logger.error(f"File not found: {filepath}")
        sys.exit(1)

    # Pipeline
    df       = load_ddc(filepath)
    df       = tag_qs_categories(df)
    df, _    = filter_non_instances(df)
    df       = assign_qs_level(df)
    df       = assign_data_quality(df)

    # QS elements only for main sheets
    qs_df    = df[df["Is_QS_Element"]].copy()

    element_list = build_element_list(qs_df)
    summary      = build_summary(qs_df)
    issues       = build_issues(qs_df)

    # Sheet 4: Non-QS elements (for Module 1 Non-QS Family check)
    non_qs_df = df[~df["Is_QS_Element"]].copy()

    export(element_list, summary, issues, non_qs_df, filepath)


if __name__ == "__main__":
    main()
