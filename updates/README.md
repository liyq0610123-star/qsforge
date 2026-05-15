# QSForge Update Manifest

This folder holds the JSON manifest that the QSForge desktop app reads to
discover new versions of the app itself and the bundled DDC converter
(`RvtExporter.exe`).

## How it fits together

```
QSForge app  ──HTTPS GET──▶  manifest.json  ──compare──▶  current vs. latest
                                                              │
                                                              ▼
                                              if newer → "Update available" toast
                                                       → user clicks "Download & install"
                                                       → QSForge downloads the artefact,
                                                         verifies SHA-256, then either:
                                                         • DDC: swaps vendor\ddc\ in place
                                                         • App: runs the Inno installer
                                                                with /SILENT /RESTARTAPPS
```

The manifest URL is configured in `_version.py`:

```python
DEFAULT_MANIFEST_URL = "https://raw.githubusercontent.com/.../updates/manifest.json"
```

It can be overridden at runtime per machine via the
`QSFORGE_UPDATE_MANIFEST_URL` environment variable (set it to an empty
string to disable update checks entirely on a particular machine).

## Releasing a new QSForge version

1. Bump `QSFORGE_VERSION` in `_version.py`.
2. Run `.\build.ps1` — produces `installer\output\QSForge-Setup-<ver>.exe`.
3. Compute the SHA-256:
   ```powershell
   Get-FileHash installer\output\QSForge-Setup-1.0.0.exe -Algorithm SHA256
   ```
4. Upload the `.exe` to your GitHub Releases / OSS / VPS.
5. Edit your live `manifest.json` (copy of `manifest.example.json`):
   - Update `qsforge.version`, `installer_url`, `sha256`, `size_bytes`.
6. Commit & push the manifest. End users see the new version on their
   next QSForge launch (silent check) or whenever they click the
   "Updates" pill in the header.

## Releasing a new DDC version

DDC is shipped as a zip of the entire `DDC_CONVERTER_REVIT\` folder
(everything inside `vendor\ddc\` in a built QSForge).

1. Get the new DDC build from datadrivenconstruction.io.
2. Zip the folder so its root contains `RvtExporter.exe` directly:
   ```powershell
   Compress-Archive -Path "C:\path\to\DDC_CONVERTER_REVIT\*" `
                    -DestinationPath "DDC-18.2.0.zip"
   ```
   (The updater also tolerates a single top-level wrapper folder, so a zip
   that contains `DDC_CONVERTER_REVIT\RvtExporter.exe` at its root is fine
   too.)
3. Compute SHA-256, upload, edit `manifest.json`'s `ddc` section the same
   way as the QSForge section.
4. Optionally bump `DDC_BUNDLED_VERSION` in `_version.py` so any *new*
   QSForge installer ships with the new DDC out of the box (otherwise
   first-run users still get whatever DDC was bundled when the installer
   was built — which is fine, the in-app updater will catch them up).

## Manifest schema

See `manifest.example.json`. Required fields per component:

| Field            | Type    | Notes                                          |
| ---------------- | ------- | ---------------------------------------------- |
| `version`        | string  | Semver-ish (e.g. `1.2.0`). Compared with `>`.  |
| `installer_url`  | string  | (QSForge only) HTTPS URL to the `.exe`         |
| `package_url`    | string  | (DDC only) HTTPS URL to the `.zip`             |
| `sha256`         | string  | Hex (lowercase or upper). Used for verification.|
| `size_bytes`     | integer | Used for "free disk space" pre-flight + UI.    |

Optional fields:

| Field                | Used in        | Notes                            |
| -------------------- | -------------- | -------------------------------- |
| `released_at`        | UI             | ISO date string                  |
| `release_notes_url`  | UI (link out)  | Tag / changelog URL              |
| `release_notes`      | UI (inline)    | Short description                |

## Safety guarantees

- Every download is verified by SHA-256 before being applied. If a CDN
  returns a corrupt file, the updater wipes it and refuses to install.
- All HTTPS requests use Python's `urllib` with TLS verification on by
  default — **never** disable this.
- DDC updates keep the previous folder under `vendor\ddc-backup\` so a
  user can roll back from the in-app menu (`POST /api/updates/rollback_ddc`).
- QSForge updates run the bundled Inno Setup installer with
  `/SILENT /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS`. Inno will close the
  current instance, replace files, and re-open the new one.
