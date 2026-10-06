"""
app_profile/registry.py — find and select the application profile.

Profiles live in config/apps/<id>.yaml. APPMIND_APP names the one to serve;
with a single profile present it is picked automatically (the same rule as
code_context.snapshots.target_repo()).
"""

from __future__ import annotations

import os
import pathlib

from app_profile.loader import AppProfile, ProfileError, load_profile
from app_profile.semantic import check_unique_ids

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
PROFILES_DIR = PROJECT_ROOT / "config" / "apps"


def load_all(profiles_dir: str | pathlib.Path = PROFILES_DIR) -> dict[str, AppProfile]:
    """Load every profile in the folder, keyed by file name. Raises ProfileError
    on the first invalid file, or if ids are duplicated or do not match names."""
    folder = pathlib.Path(profiles_dir)
    files = sorted(folder.glob("*.yaml"))
    if not files:
        raise ProfileError(f"{folder}: no application profiles found (expected <app.id>.yaml files)")
    profiles = {f.name: load_profile(f) for f in files}
    problems = check_unique_ids(profiles.items())
    if problems:
        raise ProfileError("invalid profile set\n" + "\n".join(f"  - {p}" for p in problems))
    return profiles


def select_profile(
    profiles_dir: str | pathlib.Path = PROFILES_DIR,
    app_id: str | None = None,
) -> AppProfile:
    """The profile AppMind serves: `app_id`, else APPMIND_APP, else the only one."""
    app_id = app_id or os.environ.get("APPMIND_APP")
    profiles = load_all(profiles_dir)
    if app_id:
        for profile in profiles.values():
            if profile.app.id == app_id:
                return profile
        known = ", ".join(sorted(p.app.id for p in profiles.values()))
        raise ProfileError(f"no profile with app.id '{app_id}' (available: {known})")
    if len(profiles) > 1:
        known = ", ".join(sorted(p.app.id for p in profiles.values()))
        raise ProfileError(f"several profiles exist ({known}); set APPMIND_APP")
    return next(iter(profiles.values()))
