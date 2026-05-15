"""
QSForge — Single source of truth for version numbers and update channel.

Why one file
-------------
Every other place that needs a version (Inno Setup script, Flask /api/version
endpoint, the about dialog, the update manifest comparator) reads from here
so we can bump the version in exactly one location at release time.

How to release a new version
----------------------------
1. Bump QSFORGE_VERSION below.
2. If a new DDC build is also being shipped, bump DDC_BUNDLED_VERSION.
3. Run ``.\build.ps1`` — the installer script picks up the new version
   automatically (see installer\\qsforge.iss).
4. Upload the produced ``QSForge-Setup-<ver>.exe`` to GitHub Releases under
   tag ``v<ver>`` and upload ``manifest.json`` alongside it.

Update channel
--------------
The default points at the public GitHub Releases manifest. Override at
runtime via the ``QSFORGE_UPDATE_MANIFEST_URL`` environment variable. Set
that env var to an empty string to disable update checks (air-gapped use).
"""

from __future__ import annotations

import os

# Public version of the QSForge desktop app. Compared against the manifest's
# "qsforge.version" field at update-check time. Stick to MAJOR.MINOR.PATCH —
# the comparator tolerates trailing pre-release tags like "1.0.0-rc1" but
# treats them as equal to the same MAJOR.MINOR.PATCH for ordering purposes.
QSFORGE_VERSION = "1.0.0"

# Version of DDC that is currently bundled inside this build's
# ``vendor\ddc\`` folder. Written into ``vendor\ddc\.qsforge-ddc-version``
# by build.ps1 at package time so the installed copy can be probed at
# runtime even if this constant is later bumped without rebundling DDC.
DDC_BUNDLED_VERSION = "18.1.0"

# Default update manifest URL — published to the same GitHub Release that
# hosts the installer EXE.
#
# Picking GitHub Releases here because:
#   * Free, reliable, no infra to maintain.
#   * HTTPS by default; combined with our SHA256 verification this is safe
#     to trust without code signing.
#   * Edge cache is good enough for SG/HK/MY users without a CDN.
# To self-host instead (intranet, OSS, etc.) just set the env var to your
# own URL — no code changes needed.
DEFAULT_MANIFEST_URL = (
    "https://github.com/liyq0610123-star/qsforge/"
    "releases/latest/download/manifest.json"
)


def manifest_url() -> str:
    """Return the active manifest URL, or empty string when checks are disabled."""
    env = os.environ.get("QSFORGE_UPDATE_MANIFEST_URL")
    if env is None:
        return DEFAULT_MANIFEST_URL
    # An *explicitly empty* env var means "disable update checks".
    return env.strip()


def update_checks_enabled() -> bool:
    """Convenience: True if we should attempt to fetch the manifest."""
    return bool(manifest_url())
