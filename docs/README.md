# QSForge

**Revit Model Quality Check for Quantity Surveyors**

QSForge is a Windows desktop tool that inspects a `.rvt` file and produces a one-page verdict on whether the model is usable for quantity take-off (QTO), plus a detailed issue list with Revit Element IDs so the BIM team can fix the model without a round of emails.

Typical run on a 200 MB / 70,000-element project: **60 to 120 seconds from drop to verdict**. No Revit license required.

Built for QS teams in Singapore, Hong Kong and Malaysia, where it is common to be handed a Revit model mid-bid and have to decide within minutes whether to build the BOQ from it, or negotiate a clean model first.

---

## Table of contents

1. [What the app does](#what-the-app-does)
2. [Who should use it](#who-should-use-it)
3. [Installation](#installation)
4. [Quick start](#quick-start)
5. [Understanding the result screen](#understanding-the-result-screen)
6. [The 9 quality checks](#the-9-quality-checks)
7. [Scoring and verdict](#scoring-and-verdict)
8. [Working with the BIM team](#working-with-the-bim-team)
9. [Exporting a PDF report](#exporting-a-pdf-report)
10. [Troubleshooting](#troubleshooting)
11. [What QSForge does NOT do](#what-qsforge-does-not-do)
12. [Privacy](#privacy)

---

## What the app does

QSForge answers two questions, for two different audiences, from a single `.rvt` drop:

**For QS:** *Can I trust quantities pulled from this model? Roughly how much extra effort will I spend if I proceed?*

**For BIM:** *Which specific Revit elements are missing volume, level, or material information, and where exactly are they in the model?*

Under the hood it runs the Revit file through a local converter, streams the resulting data through nine category-aware quality checks, and assigns a 0–100 score across five weighted dimensions (QS Readiness, Geometry Integrity, CAD Contamination, Model Structure, Coordinate System).

Every issue the tool flags includes the corresponding **Revit Element ID**, so your BIM team can paste the IDs into Revit's *Select by ID* dialog (`AD` shortcut, or `Manage → Inquiry → Select by ID`) and jump straight to the element.

---

## Who should use it

| Role | Why |
|---|---|
| **Cost Manager / QS lead** | Decide go/no-go on a model in 60 seconds before you commit hours to QTO. |
| **Senior QS / BOQ specialist** | See exactly which categories have gaps before setting up schedules. |
| **BIM Manager / Revit modeller** | Get a prioritized, Element-ID-level punch list of QS-relevant modelling issues. |
| **Bid / Tender team** | Attach the PDF report to a clarification request to the client's BIM team. |

---

## Installation

### System requirements

- Windows 10 or 11 (64-bit)
- Microsoft **Edge WebView2 Runtime** (pre-installed on Windows 10/11; if missing, the OS offers to install it on first launch, or grab it free from [Microsoft](https://developer.microsoft.com/en-us/microsoft-edge/webview2/))
- ~700 MB free disk space (the DDC converter is bundled)

QSForge ships with the DDC Revit converter included — nothing else to install.

### Option A — Installer (recommended)

1. Run `QSForge-Setup.exe`
2. Follow the prompts — default install location is `%LOCALAPPDATA%\QSForge\` (no admin rights needed)
3. Launch from the Start Menu or desktop shortcut

### Option B — Portable

1. Extract `QSForge.zip` to any folder (e.g. `C:\QSForge\`)
2. Double-click `QSForge.exe`
3. Windows SmartScreen may prompt "Unknown publisher" on first launch — click **More info → Run anyway**. The app is unsigned because it's an internal tool; future releases can be code-signed if needed.

### Advanced: pointing to a different DDC copy

By default QSForge uses the DDC binary bundled next to `QSForge.exe` in `vendor\ddc\`. If you need to override that (e.g. to test a newer DDC release), set the `QSFORGE_DDC_EXE` environment variable to the full path of a `RvtExporter.exe` and restart QSForge. The env var takes precedence over the bundled copy.

---

## Quick start

1. Launch **QSForge**
2. **Drop a `.rvt` file** onto the window (or click to browse)
3. Wait 60–120 seconds — the converter runs DDC under the hood, no Revit needed
4. Read the verdict
5. If you need to share: click **Export PDF**

That's the whole workflow.

---

## Understanding the result screen

After analysis, QSForge lands on **QS View** by default. There is also a **BIM View** tab — the top of the page (verdict + 5 dimension bars) is identical in both views; the bottom changes.

### QS View (top of the screen — what you see first)

**Verdict Card**

| Element | Meaning |
|---|---|
| Big number (left) | Overall score 0–100 |
| Label next to it | Ready / Conditionally Ready / High Risk / Do Not Use |
| "+X hours extra QS effort" | Rough estimate of additional QS work if you proceed with the model as-is. This is a heuristic, not a quote. |
| 5 horizontal bars | Weighted score per dimension — green ≥85, amber 50–84, red <50 |

Click any dimension bar to expand the component scores that make it up.

**What this means for QTO** — a plain-English paragraph summarizing the model's suitability and your next move.

**Top Blockers** — up to 3 critical/warning checks that are holding the score back, each with a *Fix in BIM view →* button that jumps to the detailed check below.

### BIM View (click the tab to switch)

Three panels, top to bottom:

1. **Quality Checks** — all 9 checks with severity, summary counts, by-category breakdown, and the first 100 affected Element IDs. Every card has a **Copy IDs** button that copies the full list to the clipboard.
2. **QS Readiness Flags** — higher-level category-coverage issues (from Module 0). Partially overlaps with the checks above.
3. **Inventory by Category** — per-category count / volume / area / coverage % breakdown, to see what's actually in the model.

---

## The 9 quality checks

| # | Check | What it looks for | Why QS cares |
|---|---|---|---|
| 1 | **Volume Coverage** | Elements in volumetric categories (walls, floors, slabs, beams, columns, footings) that have no computable Volume. | Zero volume → zero concrete quantity. |
| 2 | **Level Assignment** | Elements with no Level / Base Constraint / Reference Level. | Without a level you can't build a level-by-level BOQ or tall/low separation. |
| 3 | **Mass Elements** | Conceptual `OST_Mass*` objects still present. | Mass = concept design. They look solid but contain no usable quantities. |
| 4 | **Generic Models** | Elements in `OST_GenericModel`. | Unclassified; can't be scheduled or priced from a standard rate book. |
| 5 | **Multi-storey Vertical Elements** | Columns or walls whose Base Constraint and Top Constraint span **more than one level apart**. | A single 3-storey column breaks level-by-level take-off and is invisible to standard schedules. |
| 6 | **Unhosted Doors & Windows** | Doors / windows whose Host Id is empty or the host was deleted. | Orphan openings create phantom quantities and misaligned wall deductions. |
| 7 | **Nested Sub-components** | Family sub-components that can't be measured independently (shared Host Id with a parent). | Double counts if you schedule both parent and children. |
| 8 | **Material by Family-Type** | Elements with no Material / Structural Material assigned. | No material → no concrete grade, no finish, nothing to map to a rate. |
| 9 | **Wall & Floor Layer Materials** | Assembly types (walls, floors, roofs, ceilings) where one or more compound-layer materials are empty. | Layer-by-layer take-off (blockwork + render + paint) breaks when layers are blank. |

Each check is one of:

| Severity | Meaning | UI colour |
|---|---|---|
| **CRITICAL** | Measurement is impossible / heavily wrong for this aspect. | Red |
| **WARNING** | Measurable with manual care, but expect gaps and re-checks. | Amber |
| **OK** | Clean for QTO purposes. | Green |

---

## Scoring and verdict

The overall score is a weighted sum. Weights reflect what actually matters for QTO:

| Dimension | Weight | Drives |
|---|---|---|
| **QS Readiness** | 40% | Can you even schedule this model? (Volume + Level + Material) |
| **Geometry Integrity** | 25% | Is the modelled geometry trustworthy? (Multi-storey, Nested, Hosting) |
| **CAD Contamination** | 20% | Is the model still in concept stage? (Mass, Generic, raw CAD imports) |
| **Model Structure** | 10% | Are assemblies layered properly? (Walls, Floors, Roofs, Ceilings) |
| **Coordinate System** | 5%  | Is there a usable project origin? |

### Verdict thresholds

| Score | Verdict | Meaning |
|---|---|---|
| **85–100** | **Ready for QS** | Use the model. Expect normal QTO effort. |
| **65–84**  | **Conditionally Ready** | Use it, but budget a manual pass for missing levels/materials. Send the Top Blockers list to BIM as a courtesy. |
| **40–64**  | **High Risk** | Do a pass-back to BIM first. Proceeding will burn significant extra QS hours and you'll have to explain variance later. |
| **0–39**   | **Do Not Use** | Return the model. BOQ built from this will not survive audit. |

---

## Working with the BIM team

QSForge is designed so your pass-back email **does not require any Revit knowledge from your side**. The flow:

1. Analyse the model
2. In BIM View, scroll to any non-green check (or use *Fix in BIM view →* buttons in QS View)
3. Click **Copy IDs** — the list goes straight to your clipboard
4. Paste into the email body, alongside the check name (e.g. "Please review level assignment for these 11,446 elements: 1001234, 1001235, ...")
5. Or click **Export PDF** and attach that

The BIM team pastes the IDs into Revit's *Manage → Inquiry → Select by ID* dialog. Revit highlights every element. They filter, fix, and republish.

---

## Exporting a PDF report

Click **Export PDF** (top-right of the results screen). A Windows save dialog appears — pick any folder. After ~1 second the PDF opens in your default reader.

The PDF is two sections:

- **Page 1 — Executive Summary** — verdict card, dimension bars, top 3 blockers, narrative. Send this to decision-makers.
- **Page 2+ — Detailed Report** — every check with severity, by-category tables, and the first 100 affected Element IDs. Send this to BIM.

Element ID lists in the PDF are capped at 100 per check to keep the file readable. For the full list (can be 10,000+ IDs), use the **Copy IDs** button in BIM View — the clipboard has no such limit.

---

## Troubleshooting

### "Windows protected your PC" / SmartScreen warning on first launch

Expected on unsigned apps. Click **More info → Run anyway**. Windows will remember and stop warning you.

### The window appears then disappears immediately

A crash. Check the file `qsforge_crash.log` next to `QSForge.exe` — it contains a timestamped boot trace and any unhandled exception. Send the last ~20 lines to support.

### DDC error: "RvtExporter.exe not found"

This should not happen with a normal install — DDC is bundled at `vendor\ddc\RvtExporter.exe` next to `QSForge.exe`. If the message appears:

1. Verify the `vendor\ddc\` folder exists next to `QSForge.exe` and contains `RvtExporter.exe` plus ~165 DLLs (~600 MB). If it is missing, your antivirus probably quarantined part of it — whitelist the install folder and reinstall.
2. If you intentionally moved DDC elsewhere, set the `QSFORGE_DDC_EXE` environment variable (see [Advanced: pointing to a different DDC copy](#advanced-pointing-to-a-different-ddc-copy)) and restart QSForge.

### DDC runs for 2+ minutes then fails

Large models (250 MB+) can legitimately take that long. If it fails, check `qsforge_rvtexporter_last.txt` — QSForge writes it to several locations (project folder, model folder, Desktop, `%LOCALAPPDATA%\QSForge\logs\`). The file contains the exporter's full stderr/stdout. Common causes:
- The `.rvt` is password-protected
- The model is a workshared central file without being detached first
- Revit version mismatch (DDC supports up to a specific build — check the DDC release notes)

**Mitigation for workshared files:** open in Revit once, *File → Save As → Detach from Central → Save*, then run QSForge on the detached copy.

### Analysis finishes but UI stays on the "Analyzing" page

Extremely rare after the dual-event-source + polling fix, but if it happens: close the window, relaunch, try again. The `last_result.json` file next to `QSForge.exe` contains the completed analysis even if the UI failed to render.

### UI looks broken / stuck at a blank screen

Close and relaunch. QSForge wipes its WebView2 cache on every startup, so a bad cached state cannot persist.

### Scores seem too harsh / too generous

The scoring weights are tuned for straightforward structural/architectural models typical in SG/HK/MY residential and commercial projects. MEP-heavy or highly-modelled feasibility studies may score differently than your intuition — always cross-check the **Top Blockers** panel before accepting the verdict.

---

## What QSForge does NOT do

Setting expectations honestly:

- ❌ **It does not produce quantities or a BOQ.** It tells you whether you *could*.
- ❌ **It does not fix the model.** It tells the BIM team exactly what to fix, at element-ID granularity.
- ❌ **It does not check MEP coordination, clash detection, code compliance, or BIM execution-plan conformance.** Use Navisworks, Solibri, or your existing tools for that.
- ❌ **It does not validate pricing, rate books, or WBS mapping.** Those are separate QS tools.
- ❌ **It does not require or use the internet.** Everything runs locally.
- ❌ **It does not modify the `.rvt`.** Read-only — the original file is never changed.

---

## Privacy

QSForge runs **100% locally**. Nothing leaves your machine.

- No internet calls
- No telemetry
- No cloud storage
- No licence server check
- No background updater

The only files it creates are:

| File | Location | Purpose |
|---|---|---|
| `last_result.json` | next to `QSForge.exe` | Last analysis payload — useful for audit / re-exporting the PDF without re-running DDC |
| `qsforge_crash.log` | next to `QSForge.exe` | Boot trace + any unhandled exception, for support |
| `.webview-data\` | next to `QSForge.exe` | Browser cache — wiped and recreated on every launch |
| `qsforge_rvtexporter_last.txt` | several locations (first one that can be written) | DDC's stderr/stdout after a failed conversion — for support only |

You can delete any of these at any time. None of them contain anything from outside your machine.

---

## Version & support

This README describes QSForge v1.0. See the included `QUICK_START_CN.md` for a concise Chinese-language quick-start, or contact your internal QSForge support channel for help.

---

## License

QSForge is free and open source under the [MIT License](../LICENSE). See
[THIRD-PARTY-NOTICES.md](../THIRD-PARTY-NOTICES.md) for the licenses of
bundled dependencies (Flask, openpyxl, reportlab, Noto Sans CJK SC, etc.)
and for the redistribution status of the DDC RvtExporter under `vendor/ddc/`.
