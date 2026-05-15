"""
Module 2 — BQ Draft Generator (NRM2)
=====================================
Reads Module 0 output and generates a BQ Draft in NRM2 format.

Material classification per element:
  Steel    → Section H (weight in t), no Formwork, no Rebar
  Precast  → Section 11 (volume in m³), no Formwork, Rebar estimated
  In-situ  → Section 11 (volume in m³), Formwork estimated, Rebar estimated
  Unknown  → Section 11 (volume in m³), no Formwork (conservative), Rebar estimated

All items grouped by Family + Type Name.
Wall Area divided by 2 (DDC exports double-face area; NRM2 requires contact face only).

Output:
  Sheet 1: BQ – All Levels
  Sheet 2+: BQ – {Level}

Run: python module2_bq_draft.py <path_to_module0_excel>
"""

import pandas as pd
import numpy as np
import re
import sys
import os
from datetime import datetime

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

FORMWORK_COEFF = {
    "Structural Foundation":      2.0,
    "Structural Columns":         6.0,
    "Structural Framing (Beams)": 5.0,
    "Floors":                     1.0,   # × Area (single face)
    "Walls":                      1.0,   # × Area/2 (DDC is double face)
    "Stairs":                     3.0,
}

REBAR_COEFF_KG_M3 = {
    "Structural Foundation":      80,
    "Structural Columns":        180,
    "Structural Framing (Beams)":160,
    "Floors":                    120,
    "Walls":                     100,
    "Stairs":                    150,
}

STEEL_DENSITY_KG_M3 = 7850

# Material classification keywords (applied case-insensitive)
STEEL_KEYWORDS   = [
    "steel", "s275", "s355", "s460", "s235",
    "grade 43", "grade 50", "fe 360", "fe 430",
    r"\buc\b", r"\bub\b", r"\bchs\b", r"\brhs\b", r"\bshs\b",
]
PRECAST_KEYWORDS = [
    "precast", "pre-cast", "pre cast", r"\bpc\b", r"\bp/c\b",
    "prc", "precasted",
]
INSITU_KEYWORDS  = [
    "in situ", "in-situ", "insitu", "in_situ",
    "cast in situ", "cast-in-situ", "cast in place", r"\bcip\b",
]

INVALID_MATERIALS = {"", "none", "default", "generic", "by category", "undefined"}

# DDC column names (from Module 0 QS Element List)
COL_ID       = "Element ID"
COL_CATEGORY = "Category"
COL_FAMILY   = "Family"
COL_TYPE     = "Type Name"
COL_LEVEL    = "Level"
COL_VOLUME   = "Volume (m³)"
COL_AREA     = "Area (m²)"
COL_MATERIAL = "Structural Material : String"
COL_STRUCT   = "Structural : Boolean"
COL_WIDTH    = "[Type] Width : Double"
COL_DQ       = "Data_Quality"

STAIR_CATS     = ["Stairs", "Stair Runs", "Stair Landings"]
INVALID_LEVELS = {"Level_Not_Assigned", "Level_Param_Missing", "Non_QS_Element"}

# NRM2 location template per QS category
LOCATION_DESC = {
    "Structural Foundation":      "to {family}; {type_name}",
    "Structural Columns":         "to columns; {family}; {type_name}",
    "Structural Framing (Beams)": "to beams; {family}; {type_name}",
    "Floors":                     "to suspended slabs; {family}; {type_name}",
    "Walls":                      "to walls; {family}; {type_name}",
    "Stairs":                     "to staircases; {family}; {type_name}",
}


# ─────────────────────────────────────────────
# MATERIAL CLASSIFICATION
# ─────────────────────────────────────────────

def classify_material(raw):
    """
    Returns: 'steel' | 'precast' | 'insitu' | 'missing' | 'unclassified'
    """
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


def add_material_class(df):
    """Add _mat_class column to dataframe."""
    df = df.copy()
    if COL_MATERIAL in df.columns:
        df["_mat_class"] = df[COL_MATERIAL].apply(classify_material)
    else:
        df["_mat_class"] = "unclassified"
    return df


# ─────────────────────────────────────────────
# LOAD
# ─────────────────────────────────────────────

def load_module0(filepath):
    print(f"\n{'='*60}")
    print(f"Loading: {os.path.basename(filepath)}")
    df = pd.read_excel(filepath, sheet_name="QS Element List")
    print(f"Rows loaded: {len(df):,}")

    if COL_DQ in df.columns:
        df = df[df[COL_DQ] == "Clean"].copy()
        print(f"Clean elements for BQ: {len(df):,}")

    df[COL_VOLUME] = pd.to_numeric(df[COL_VOLUME], errors="coerce").fillna(0)
    df[COL_AREA]   = pd.to_numeric(df[COL_AREA],   errors="coerce").fillna(0)
    df = add_material_class(df)

    # Print material classification summary
    print(f"\n  Material classification:")
    print(df["_mat_class"].value_counts().to_string())

    return df


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def clean_grade(raw):
    if not raw or str(raw).strip().lower() in INVALID_MATERIALS:
        return "(grade not specified)"
    raw = str(raw).strip()
    m = re.search(r'C?(\d{2,3})/(\d{2})', raw)
    if m:
        return f"Grade C{m.group(1)}/{m.group(2)}"
    m2 = re.search(r'C(\d{2,3})', raw)
    if m2:
        return f"Grade C{m2.group(1)}"
    cleaned = re.sub(r'Concrete_|Cast In Situ|Precast|Cast In Place', '', raw).strip()
    return cleaned if cleaned else "(grade not specified)"


def get_grade(sub):
    if COL_MATERIAL not in sub.columns or len(sub) == 0:
        return "(grade not specified)"
    vals = sub[COL_MATERIAL].dropna().astype(str)
    vals = vals[~vals.str.lower().isin(list(INVALID_MATERIALS))]
    if len(vals) == 0:
        return "(grade not specified)"
    return clean_grade(vals.mode().iloc[0])


def get_steel_grade(sub):
    """Get steel grade string, e.g. S275, S355."""
    if COL_MATERIAL not in sub.columns or len(sub) == 0:
        return "(grade not specified)"
    vals = sub[COL_MATERIAL].dropna().astype(str)
    for v in vals:
        m = re.search(r'S\d{3}', v, re.IGNORECASE)
        if m:
            return m.group().upper()
        m2 = re.search(r'[Gg]rade\s*\d+', v)
        if m2:
            return m2.group()
    return vals.mode().iloc[0] if len(vals) > 0 else "(grade not specified)"


def make_row(description, unit="", qty="", note=""):
    return {
        "Description": description,
        "Unit":        unit,
        "Qty":         round(float(qty), 2) if qty != "" and qty != 0 else "",
        "Rate":        "",
        "Amount":      "",
        "Note":        note,
    }


def section_header(title):
    return make_row(title)


def sub_header(title):
    return make_row(f"  {title}")


def assign_item_refs(rows):
    result  = []
    counter = 0
    for row in rows:
        qty  = row.get("Qty", "")
        unit = row.get("Unit", "")
        desc = str(row.get("Description", ""))
        is_section = (qty == "" and unit == "" and
                      desc.strip().upper().startswith("SECTION"))
        is_sub     = (qty == "" and unit == "")

        if is_section:
            counter = 0
            result.append({"Item": "", **row})
        elif is_sub:
            result.append({"Item": "", **row})
        else:
            ref = chr(65 + counter) if counter < 26 else f"A{chr(65 + counter - 26)}"
            result.append({"Item": ref, **row})
            counter += 1
    return result


def iter_family_type_groups(sub):
    """Yield (family, type_name, group_df) sorted alphabetically."""
    if COL_FAMILY not in sub.columns or COL_TYPE not in sub.columns:
        yield ("", "", sub)
        return
    sub = sub.copy()
    sub["_f"] = sub[COL_FAMILY].fillna("(unknown family)").astype(str)
    sub["_t"] = sub[COL_TYPE].fillna("(unknown type)").astype(str)
    for (f, t), grp in sub.groupby(["_f", "_t"], sort=True):
        yield (f, t, grp)


# ─────────────────────────────────────────────
# SECTION H — STRUCTURAL STEELWORK
# ─────────────────────────────────────────────

def build_section_H(steel_elements, level=None):
    """
    Steel elements → Section H.
    Weight = Volume × 7850 kg/m³ ÷ 1000 → t
    No Formwork. No Rebar.
    """
    label = f" — {level}" if level else " — All Levels"
    rows  = [section_header(f"SECTION H – STRUCTURAL STEELWORK{label}")]

    if len(steel_elements) == 0:
        rows.append(make_row("  (No structural steelwork elements)"))
        return rows

    rows.append(sub_header("Structural Steelwork"))

    for family, type_name, grp in iter_family_type_groups(steel_elements):
        v = grp[COL_VOLUME].sum()
        if v <= 0:
            continue
        t     = v * STEEL_DENSITY_KG_M3 / 1000
        grade = get_steel_grade(grp)
        desc  = f"Structural steelwork {grade}; {family}; {type_name}"
        note  = (f"Weight estimated: {round(v,3)} m³ × {STEEL_DENSITY_KG_M3} kg/m³ ÷ 1000; "
                 f"excludes connections and fittings")
        rows.append(make_row(desc, "t", t, note))

    return rows


# ─────────────────────────────────────────────
# SECTION 11 — IN-SITU CONCRETE
# ─────────────────────────────────────────────

def build_section11(concrete_elements, level=None):
    """
    Concrete elements (in-situ + precast + unknown) → Section 11.
    Only in-situ gets Formwork. All get Rebar (estimated).
    """
    label = f" — {level}" if level else " — All Levels"
    rows  = [section_header(f"SECTION 11 – IN-SITU CONCRETE{label}")]

    if len(concrete_elements) == 0:
        rows.append(make_row("  (No concrete elements)"))
        return rows

    # Split walls: structural vs non-structural
    walls_df = concrete_elements[concrete_elements[COL_CATEGORY] == "Walls"].copy()
    if COL_STRUCT in walls_df.columns:
        sm = walls_df[COL_STRUCT].astype(str).str.lower().isin(["true", "1", "yes"])
        struct_walls     = walls_df[sm]
        non_struct_walls = walls_df[~sm]
    else:
        struct_walls     = walls_df
        non_struct_walls = pd.DataFrame()

    # Stairs combined
    stairs_df = concrete_elements[
        concrete_elements[COL_CATEGORY].isin(STAIR_CATS)].copy()

    cat_subsets = [
        ("Structural Foundation",
         concrete_elements[concrete_elements[COL_CATEGORY] == "Structural Foundation"]),
        ("Structural Columns",
         concrete_elements[concrete_elements[COL_CATEGORY] == "Structural Columns"]),
        ("Structural Framing (Beams)",
         concrete_elements[concrete_elements[COL_CATEGORY] == "Structural Framing (Beams)"]),
        ("Floors",
         concrete_elements[concrete_elements[COL_CATEGORY] == "Floors"]),
        ("Walls",   struct_walls),
        ("Stairs",  stairs_df),
    ]

    # ── Concrete ──
    rows.append(sub_header("Concrete"))
    for cat, sub in cat_subsets:
        if len(sub) == 0:
            continue
        tmpl = LOCATION_DESC.get(cat, "to {family}; {type_name}")
        for family, type_name, grp in iter_family_type_groups(sub):
            v = grp[COL_VOLUME].sum()
            if v <= 0:
                continue
            grade = get_grade(grp)
            mat_types = grp["_mat_class"].unique()
            # Label precast separately
            if "precast" in mat_types and "insitu" not in mat_types:
                conc_type = "Precast concrete"
            elif "precast" in mat_types:
                conc_type = "Reinforced concrete (mixed in-situ/precast)"
            else:
                conc_type = "Reinforced concrete"
            location = tmpl.format(family=family, type_name=type_name)
            desc = f"{conc_type} {grade}; {location}"
            rows.append(make_row(desc, "m³", v))

    # ── Formwork (in-situ only) ──
    rows.append(sub_header("Formwork"))
    has_formwork = False

    for cat, sub in cat_subsets:
        if len(sub) == 0:
            continue
        # Only in-situ gets formwork
        insitu = sub[sub["_mat_class"] == "insitu"]
        if len(insitu) == 0:
            continue

        has_formwork = True
        tmpl  = LOCATION_DESC.get(cat, "to {family}; {type_name}")
        coeff = FORMWORK_COEFF.get(cat, 1.0)
        use_area = cat in ("Floors", "Walls")

        for family, type_name, grp in iter_family_type_groups(insitu):
            if use_area:
                if cat == "Walls":
                    qty  = grp[COL_AREA].sum() / 2  # DDC double face → single face
                    note = "Estimated from wall area ÷ 2 (single contact face)"
                else:
                    qty  = grp[COL_AREA].sum()
                    note = "Estimated from slab area"
            else:
                qty  = grp[COL_VOLUME].sum() * coeff
                note = f"Estimated: Volume × {coeff}"
            if qty <= 0:
                continue
            location = tmpl.format(family=family, type_name=type_name)
            desc = f"Formwork; {location} (estimated)"
            rows.append(make_row(desc, "m²", qty, note))

    if not has_formwork:
        rows.append(make_row(
            "  (No in-situ concrete elements — formwork not applicable)"))

    # ── Reinforcement ──
    rows.append(sub_header("Reinforcement"))
    for cat, sub in cat_subsets:
        if len(sub) == 0:
            continue
        coeff = REBAR_COEFF_KG_M3.get(cat, 0)
        tmpl  = LOCATION_DESC.get(cat, "to {family}; {type_name}")
        for family, type_name, grp in iter_family_type_groups(sub):
            v = grp[COL_VOLUME].sum()
            if v <= 0:
                continue
            t        = v * coeff / 1000
            location = tmpl.format(family=family, type_name=type_name)
            desc     = f"Reinforcement (est. {coeff} kg/m³); {location}"
            note     = f"Estimated: {round(v,2)} m³ × {coeff} kg/m³ ÷ 1000"
            rows.append(make_row(desc, "t", t, note))

    return rows, non_struct_walls


# ─────────────────────────────────────────────
# SECTION 14 — MASONRY
# ─────────────────────────────────────────────

def build_section14(non_struct_walls):
    rows = [section_header("SECTION 14 – MASONRY")]
    if len(non_struct_walls) == 0:
        rows.append(make_row("  (No non-structural walls)"))
        return rows

    for family, type_name, grp in iter_family_type_groups(non_struct_walls):
        a = grp[COL_AREA].sum() / 2  # DDC double face → single face
        if a <= 0:
            continue
        thick_str = ""
        if COL_WIDTH in grp.columns:
            thick = pd.to_numeric(grp[COL_WIDTH], errors="coerce").median()
            if not pd.isna(thick) and thick > 0:
                thick_str = f"; {int(round(thick))}mm thick"
        desc = f"Blockwork/brickwork; {family}; {type_name}{thick_str}"
        rows.append(make_row(desc, "m²", a,
                             "Area = DDC double-face ÷ 2"))
    return rows


# ─────────────────────────────────────────────
# SECTION 17 — WATERPROOFING
# ─────────────────────────────────────────────

def build_section17(df):
    rows  = [section_header("SECTION 17 – WATERPROOFING")]
    roofs = df[df[COL_CATEGORY] == "Roofs"]
    if len(roofs) == 0:
        rows.append(make_row("  (No roof elements)"))
        return rows
    for family, type_name, grp in iter_family_type_groups(roofs):
        a = grp[COL_AREA].sum()
        if a > 0:
            rows.append(make_row(
                f"Waterproofing to roofs; {family}; {type_name}", "m²", a))
    return rows


# ─────────────────────────────────────────────
# SECTION 28 — FINISHES
# ─────────────────────────────────────────────

def build_section28(df):
    rows     = [section_header("SECTION 28 – FINISHES")]
    ceilings = df[df[COL_CATEGORY] == "Ceilings"]
    if len(ceilings) == 0:
        rows.append(make_row("  (No ceiling elements)"))
        return rows
    for family, type_name, grp in iter_family_type_groups(ceilings):
        a = grp[COL_AREA].sum()
        if a > 0:
            rows.append(make_row(
                f"Ceiling finishes; {family}; {type_name}", "m²", a))
    return rows


# ─────────────────────────────────────────────
# BUILD FULL BQ
# ─────────────────────────────────────────────

def build_bq(df, level=None):
    sub = df[df[COL_LEVEL] == level].copy() if level else df.copy()

    # Split steel vs concrete elements
    steel_cats    = {"Structural Columns", "Structural Framing (Beams)"}
    steel_mask    = (sub[COL_CATEGORY].isin(steel_cats) &
                     (sub["_mat_class"] == "steel"))
    steel_df      = sub[steel_mask]
    concrete_df   = sub[~steel_mask]

    all_rows = []

    # Section H — Steel
    all_rows.extend(build_section_H(steel_df, level))

    # Section 11 — Concrete
    s11_rows, non_struct_walls = build_section11(concrete_df, level)
    all_rows.extend(s11_rows)

    # Section 14 — Masonry
    all_rows.extend(build_section14(non_struct_walls))

    # Section 17 — Waterproofing
    all_rows.extend(build_section17(sub))

    # Section 28 — Finishes
    all_rows.extend(build_section28(sub))

    all_rows = assign_item_refs(all_rows)
    return pd.DataFrame(all_rows)[["Item", "Description", "Unit",
                                    "Qty", "Rate", "Amount", "Note"]]


# ─────────────────────────────────────────────
# EXPORT
# ─────────────────────────────────────────────

def export(df, input_path):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    base      = os.path.splitext(os.path.basename(input_path))[0].replace("_Module0", "")
    out_path  = os.path.join(os.path.dirname(os.path.abspath(input_path)),
                             f"{base}_Module2_BQ_{timestamp}.xlsx")

    levels = sorted(
        [l for l in df[COL_LEVEL].unique()
         if l not in INVALID_LEVELS and pd.notna(l)],
        key=lambda x: str(x)
    )

    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        bq_all = build_bq(df, level=None)
        bq_all.to_excel(writer, sheet_name="BQ – All Levels", index=False)
        print(f"  BQ – All Levels: {len(bq_all)} rows")

        for level in levels:
            bq_lvl = build_bq(df, level=level)
            sname  = f"BQ – {level}"[:31]
            bq_lvl.to_excel(writer, sheet_name=sname, index=False)
            print(f"  {sname}: {len(bq_lvl)} rows")

    print(f"\n{'='*60}")
    print(f"BQ Draft saved: {out_path}")
    print(f"  Standard: NRM2  |  Levels: {levels}")
    print(f"  Rate/Amount columns left blank for QS to complete")
    print(f"{'='*60}\n")
    return out_path


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python module2_bq_draft.py <path_to_module0_excel>")
        sys.exit(1)
    filepath = sys.argv[1]
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        sys.exit(1)
    df = load_module0(filepath)
    export(df, filepath)


if __name__ == "__main__":
    main()
