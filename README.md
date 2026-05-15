# QSForge

**Free Revit Model Quality Check + BQ Draft for Quantity Surveyors.**

QSForge is a Windows desktop tool that takes a `.rvt` file, runs nine
category-aware quality checks for QS workflows, and produces a draft NRM2
Bill of Quantities. Drop a model in, get a verdict and an Excel BQ within
60–120 seconds. No Revit licence required — the DDC converter is bundled.

Built for QS teams in Singapore, Hong Kong, and Malaysia, where you often
have to decide within minutes whether a handed-over Revit model is usable
for take-off.

## Download

Grab the latest installer from
[Releases](https://github.com/liyq0610123-star/qsforge/releases/latest).

On first launch, Windows SmartScreen may show "Windows protected your PC".
This is expected for an unsigned installer — click **More info → Run anyway**.
A signed installer is planned for a later release.

## What it does

- Inspects a `.rvt` for QS-readiness across 9 dimensions (Volume Coverage,
  Level Assignment, Multi-storey vertical elements, Material completeness, etc.)
- Produces a draft NRM2 Bill of Quantities (Excel) for sections H, 11, 14, 17, 28
- Element-ID-level punch list for the BIM team
- Exports a two-page PDF report (executive summary + detailed BIM follow-up)
- Optional 3D preview of the model (powered by three.js)
- Does **not** produce final BQs or fix the model — it tells you whether
  you can trust quantities pulled from it.

## See also

- [User manual (English)](docs/README.md)
- [使用说明 (中文)](docs/QUICK_START_CN.md)
- [Third-party licenses](THIRD-PARTY-NOTICES.md)

## License

[MIT](LICENSE) — free for any use, including commercial.

---

QSForge is the successor to the internal-only **ArchiQS** prototype.
