"""
app_profile — the application profile: one YAML file that says which
application AppMind serves and where its knowledge lives
(features/appmind-config/app-config-design.md).

    from app_profile import load_profile
    profile = load_profile("config/apps/orderflow.yaml")
"""

from app_profile.loader import (
    AppInfo,
    AppProfile,
    CodeSource,
    DocumentSource,
    ProfileError,
    Scope,
    Sources,
    load_profile,
    parse_profile,
)

__all__ = [
    "AppInfo", "AppProfile", "CodeSource", "DocumentSource", "ProfileError",
    "Scope", "Sources", "load_profile", "parse_profile",
]
