"""
Module 2c — Overall QS Readiness Score for QSForge UI / PDF.

Uses Module 1 (module1_qs_readiness) seven-dimension framework when the source
DDC Excel is still available on disk. Falls back to legacy severity-counting
if Module 1 cannot run (file missing, exception, etc.).

The return shape is locked by the frontend / pdf_report — do not change keys.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict


# ─────────────────────────────────────────────
# Verdict thresholds (unchanged from legacy)
# ─────────────────────────────────────────────

def _verdict_for(overall: int) -> Dict[str, str]:
    if overall >= 85:
        return {"label": "Ready for QS",          "icon": "✅", "color": "success", "code": "READY"}
    if overall >= 65:
        return {"label": "Conditionally Ready",   "icon": "⚠",  "color": "warning", "code": "CONDITIONAL"}
    if overall >= 40:
        return {"label": "High Risk",             "icon": "🔴", "color": "warning", "code": "RISK"}
    return     {"label": "Do Not Use",            "icon": "❌", "color": "danger",  "code": "NO_USE"}


# ─────────────────────────────────────────────
# Legacy fallback (kept for safety)
# ─────────────────────────────────────────────

def _legacy_score(data: Dict[str, Any]) -> Dict[str, Any]:
    issues = data.get("issues") or []
    crit = sum(1 for i in issues if i.get("severity") == "CRITICAL")
    warn = sum(1 for i in issues if i.get("severity") == "WARNING")

    base = 100.0
    base -= min(55.0, crit * 18.0)
    base -= min(35.0, warn * 7.0)
    overall = int(max(0, min(100, round(base))))

    dim_score = max(0, min(100, overall + 5))
    dimensions = [
        {"id": "qs_readiness",      "label": "QS Readiness",       "weight": 40, "score": overall},
        {"id": "geometry",          "label": "Geometry Integrity", "weight": 25, "score": dim_score},
        {"id": "cad",               "label": "CAD Contamination",  "weight": 20, "score": dim_score},
        {"id": "structure",         "label": "Model Structure",    "weight": 10, "score": dim_score},
        {"id": "coordinate_system", "label": "Coordinate System",  "weight": 5,  "score": dim_score},
    ]

    extra = min(48, crit * 6 + warn * 3)
    return {
        "overall": overall,
        "verdict": _verdict_for(overall),
        "dimensions": dimensions,
        "extra_qs_hours": int(extra) if extra > 0 else None,
        "engine": "legacy_severity",
    }


# ─────────────────────────────────────────────
# Module 1 powered scoring (preferred path)
# ─────────────────────────────────────────────

def _group_issues(iss, lookup_df,
                  id_col: str = "Element ID",
                  family_col: str = "Family",
                  type_col: str = "Type Name",
                  cat_col: str = "Category",
                  max_groups: int = 30,
                  ids_per_group: int = 50) -> list:
    """
    Group an issues DataFrame by Family + Type Name, returning a list of
    ``{family, type, category, count, ids}`` dicts (largest groups first).

    *iss* may already contain Family / Type columns (Non-QS check). When it
    doesn't (Level / Volume / Material / Span / etc.), the caller passes
    ``lookup_df`` (typically ``element_list``) and we left-join on Element ID
    to recover them.
    """
    try:
        if iss is None or len(iss) == 0:
            return []
        import pandas as pd
        df = iss.copy()
        if id_col not in df.columns:
            return []
        df[id_col] = pd.to_numeric(df[id_col], errors="coerce")
        df = df.dropna(subset=[id_col])
        df[id_col] = df[id_col].astype(int)

        need_meta = family_col not in df.columns or type_col not in df.columns
        if need_meta and lookup_df is not None and id_col in lookup_df.columns:
            cols = [id_col]
            for c in (family_col, type_col, cat_col):
                if c in lookup_df.columns:
                    cols.append(c)
            meta = lookup_df[cols].copy()
            meta[id_col] = pd.to_numeric(meta[id_col], errors="coerce")
            meta = meta.dropna(subset=[id_col])
            meta[id_col] = meta[id_col].astype(int)
            meta = meta.drop_duplicates(subset=[id_col])
            df = df.merge(meta, on=id_col, how="left", suffixes=("", "_lk"))
            for c in (family_col, type_col, cat_col):
                lk = f"{c}_lk"
                if lk in df.columns:
                    if c not in df.columns:
                        df[c] = df[lk]
                    else:
                        df[c] = df[c].fillna(df[lk])
                    df.drop(columns=[lk], inplace=True)

        if family_col not in df.columns:
            df[family_col] = "(no family)"
        if type_col not in df.columns:
            df[type_col] = "(no type)"
        if cat_col not in df.columns:
            df[cat_col] = ""

        df[family_col] = df[family_col].fillna("(no family)").astype(str)
        df[type_col]   = df[type_col].fillna("(no type)").astype(str)
        df[cat_col]    = df[cat_col].fillna("").astype(str)

        groups = []
        for (fam, typ, cat), grp in df.groupby([family_col, type_col, cat_col], dropna=False):
            ids = grp[id_col].dropna().astype(int).tolist()
            if not ids:
                continue
            groups.append({
                "family":   fam or "(no family)",
                "type":     typ or "(no type)",
                "category": cat or "",
                "count":    int(len(grp)),
                "ids":      ids[:ids_per_group],
            })
        groups.sort(key=lambda g: (-g["count"], g["family"], g["type"]))
        return groups[:max_groups]
    except Exception:
        return []


def _module1_score(data: Dict[str, Any]) -> Dict[str, Any] | None:
    """
    Run all 7 Module 1 dimension checks against the source DDC Excel
    (path is in data["file"]["path"]). Returns None if Module 1 cannot run
    so the caller can fall back gracefully.
    """
    src_path = (data.get("file") or {}).get("path")
    if not src_path or not os.path.isfile(src_path):
        return None

    try:
        # Local imports keep this module importable even if Module 1 / 2 are missing
        import pandas as pd
        import module0_inventory as m0
        import module1_qs_readiness as m1
    except Exception:
        return None

    try:
        # Run Module 0 pipeline once to get the QS DataFrame Module 1 expects
        df = m0._prepare_instance_df(src_path)[0]
        df = m0.tag_qs_categories(df, verbose=False)
        df, _ = m0.filter_non_instances(df, verbose=False)
        df = m0.assign_qs_level(df, verbose=False)
        df = m0.assign_data_quality(df, verbose=False)

        qs_df = df[df["Is_QS_Element"]].copy()
        non_qs_df = df[~df["Is_QS_Element"]].copy()

        # Build the same DataFrames Module 1 reads from the Excel
        element_list = m0.build_element_list(qs_df)
        non_qs_min = non_qs_df[[m0.COL_ID, m0.COL_CATEGORY,
                                m0.COL_FAMILY, m0.COL_TYPE,
                                m0.COL_VOLUME, m0.COL_AREA]].copy()
        non_qs_min = non_qs_min.rename(columns={
            m0.COL_ID: "Element ID", m0.COL_CATEGORY: "Category (OST)",
            m0.COL_FAMILY: "Family", m0.COL_TYPE: "Type Name",
            m0.COL_VOLUME: "Volume (m³)", m0.COL_AREA: "Area (m²)",
        })

        # Module 1 dimension checks — capture element IDs for BIM team
        sorted_levels, level_index = m1.build_level_order(element_list)

        results = {}
        s, r, iss = m1.check_level_coverage(element_list)
        results["Level Coverage"]        = {"score": s, "issues": int(len(iss)), "groups": _group_issues(iss, element_list)}
        s, r, iss = m1.check_volume_coverage(element_list)
        results["Volume Coverage"]       = {"score": s, "issues": int(len(iss)), "groups": _group_issues(iss, element_list)}
        s, r, iss = m1.check_material_completeness(element_list)
        results["Material Completeness"] = {"score": s, "issues": int(len(iss)), "groups": _group_issues(iss, element_list)}
        s, r, iss = m1.check_vertical_span(element_list, level_index)
        results["Vertical Span"]         = {"score": s, "issues": int(len(iss)), "groups": _group_issues(iss, element_list)}
        s, r, iss = m1.check_volume_anomaly(element_list)
        results["Volume Anomaly"]        = {"score": s, "issues": int(len(iss)), "groups": _group_issues(iss, element_list)}
        s, r, iss = m1.check_unit_consistency(element_list)
        results["Unit Consistency"]      = {"score": s, "issues": int(len(iss)), "groups": _group_issues(iss, element_list)}
        s, r, iss = m1.check_non_qs_family(element_list, non_qs_min)
        # Non-QS issues already carry Family / Type Name; lookup_df helps when missing
        results["Non-QS Family"]         = {"score": s, "issues": int(len(iss)), "groups": _group_issues(iss, non_qs_min, cat_col="Category (OST)")}

        # Weighted overall (mirrors Module 1 WEIGHTS)
        valid = {k: v for k, v in results.items() if v["score"] is not None}
        total_weight = sum(m1.WEIGHTS[k] for k in valid)
        overall = sum(v["score"] * m1.WEIGHTS[k] / total_weight
                      for k, v in valid.items()) if total_weight else 0
        overall_int = int(round(overall))
        overall_int = max(0, min(100, overall_int))

        # Expose all 7 Module 1 dimensions directly
        _dim_ids = {
            "Level Coverage":         "level_coverage",
            "Volume Coverage":        "volume_coverage",
            "Material Completeness":  "material_completeness",
            "Vertical Span":          "vertical_span",
            "Volume Anomaly":         "volume_anomaly",
            "Unit Consistency":       "unit_consistency",
            "Non-QS Family":          "non_qs_family",
        }
        dimensions = [
            {
                "id":     _dim_ids.get(k, k.lower().replace(" ", "_")),
                "label":  k,
                "weight": m1.WEIGHTS[k],
                "score":  v["score"] if v["score"] is not None else 100,
            }
            for k, v in results.items()
        ]

        # Estimate extra QS hours using legacy issue counts
        issues = data.get("issues") or []
        crit = sum(1 for i in issues if i.get("severity") == "CRITICAL")
        warn = sum(1 for i in issues if i.get("severity") == "WARNING")
        extra = min(48, crit * 6 + warn * 3)

        return {
            "overall": overall_int,
            "verdict": _verdict_for(overall_int),
            "dimensions": dimensions,
            "extra_qs_hours": int(extra) if extra > 0 else None,
            "module1_detail": results,
            "engine": "module1_qs_readiness",
        }
    except Exception:
        return None


# ─────────────────────────────────────────────
# Public entry — server.py contract
# ─────────────────────────────────────────────

def compute_score(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute overall QS Readiness Score.
    Tries Module 1 first; falls back to legacy severity counting.
    Always returns the locked frontend shape:
      overall, verdict, dimensions, extra_qs_hours
    """
    result = _module1_score(data)
    if result is None:
        return _legacy_score(data)
    return result
