# Third-Party Notices

QSForge bundles, links to, or otherwise redistributes the following third-party
components. Their respective licenses are reproduced or linked below.

## Python runtime dependencies

| Component | License | Project URL |
|---|---|---|
| Flask | BSD-3-Clause | https://palletsprojects.com/p/flask/ |
| Werkzeug | BSD-3-Clause | https://palletsprojects.com/p/werkzeug/ |
| Jinja2 | BSD-3-Clause | https://palletsprojects.com/p/jinja/ |
| MarkupSafe | BSD-3-Clause | https://palletsprojects.com/p/markupsafe/ |
| itsdangerous | BSD-3-Clause | https://palletsprojects.com/p/itsdangerous/ |
| click | BSD-3-Clause | https://palletsprojects.com/p/click/ |
| pywebview | BSD-3-Clause | https://pywebview.flowrl.com/ |
| openpyxl | MIT | https://openpyxl.readthedocs.io/ |
| pandas | BSD-3-Clause | https://pandas.pydata.org/ |
| numpy | BSD-3-Clause | https://numpy.org/ |
| reportlab | BSD-3-Clause | https://www.reportlab.com/opensource/ |
| matplotlib | Matplotlib License (PSF-based) | https://matplotlib.org/ |
| lxml | BSD-3-Clause | https://lxml.de/ |
| pyarrow | Apache-2.0 | https://arrow.apache.org/ |
| pyreadline3 | BSD-3-Clause | https://github.com/pyreadline3/pyreadline3 |
| pyinstaller | GPLv2 with bootloader exception (output not GPL-encumbered) | https://pyinstaller.org/ |

## Fonts

| Component | License | Project URL |
|---|---|---|
| Noto Sans CJK SC (Regular + Bold) | SIL Open Font License 1.1 (OFL-1.1) | https://github.com/notofonts/noto-cjk |

## External tooling redistributed in `vendor/`

| Component | Notes |
|---|---|
| DDC RvtExporter (datadrivenconstruction.io) | Bundled under `vendor/ddc/`. See `vendor/ddc/LICENSE` (preserved from upstream). **QSForge maintainers must confirm DDC's license permits redistribution inside an MIT-licensed product before each release.** If at any time the DDC license changes and forbids redistribution, the build switches to a first-launch downloader and DDC is no longer shipped inside the installer. |

## Full license text

The full text of each license above can be found in the upstream project. The
MIT License covering QSForge itself is at `LICENSE` in this repository.
