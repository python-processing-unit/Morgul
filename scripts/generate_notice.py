#!/usr/bin/env python3
"""Generate NOTICE.md from uv.lock and installed package license files."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import tomllib

REPO_ROOT = Path(__file__).resolve().parent.parent
UV_LOCK = REPO_ROOT / "uv.lock"
VENV_SITE_PACKAGES = REPO_ROOT / ".venv" / "Lib" / "site-packages"
NOTICE_FILE = REPO_ROOT / "NOTICE.md"
PROJECT_LICENSE = REPO_ROOT / "UNLICENSE"


def parse_uv_lock(path: Path) -> dict[str, dict[str, Any]]:
    """Return package-name -> package-table from uv.lock."""
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    packages: dict[str, dict[str, Any]] = {}
    for pkg in data.get("package", []):
        name = pkg.get("name", "")
        if name:
            packages[name] = pkg
    return packages


def find_license_files(package_name: str, version: str) -> list[Path]:
    """Locate license/copyright files inside the installed package."""
    base = VENV_SITE_PACKAGES
    candidates: list[Path] = []

    # dist-info / wheel-info directories
    for pattern in [
        f"{package_name.replace('-', '_')}-{version}*.dist-info",
        f"{package_name.replace('-', '_')}-{version}*.whl-info",
    ]:
        candidates.extend(base.glob(pattern))

    # bare package directory (sometimes used for namespace / single-file pkgs)
    pkg_dir = base / package_name.replace("-", "_")
    if pkg_dir.is_dir():
        candidates.append(pkg_dir)

    license_paths: list[Path] = []
    for candidate in candidates:
        if candidate.is_dir():
            # look in a licenses/ sub-directory first
            licenses_dir = candidate / "licenses"
            search_root = licenses_dir if licenses_dir.is_dir() else candidate
            for f in search_root.rglob("*"):
                if f.is_file() and re.match(
                    r"^(LICENSE|COPYING|NOTICE|LICENSE\..+|LicenseRef.+)$", f.name, re.IGNORECASE
                ):
                    license_paths.append(f)
    return sorted(set(license_paths))


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def classify_license(text: str) -> str:
    lower = text.lower()
    if "mit license" in lower or "mit" == lower.strip():
        return "MIT"
    if "apache license" in lower and "version 2.0" in lower:
        return "Apache-2.0"
    if "bsd" in lower and "redistribution" in lower:
        return "BSD"
    if "gnu general public license" in lower or "gpl" in lower:
        return "GPL"
    if "lgpl" in lower:
        return "LGPL"
    if "unlicense" in lower:
        return "Unlicense"
    if "psf license" in lower or "python software foundation" in lower:
        return "PSF-2.0"
    return "UNKNOWN"


def generate() -> str:
    packages = parse_uv_lock(UV_LOCK)

    lines: list[str] = [
        "# NOTICE",
        "",
        "This file lists copyright and attribution notices for the software and all",
        "of its dependencies (direct, dev, and transitive).",
        "",
        "Generated from `uv.lock` and installed package license files.",
        "",
    ]

    # Project's own license
    if PROJECT_LICENSE.exists():
        proj_text = read_text(PROJECT_LICENSE).strip()
        if proj_text:
            lines.append("## morgul (this software)")
            lines.append("")
            lines.append("**License:** Unlicense")
            lines.append("")
            lines.append("```")
            lines.append(proj_text)
            lines.append("```")
            lines.append("")

    for name, pkg in sorted(packages.items()):
        version = pkg.get("version", "unknown")
        license_paths = find_license_files(name, version)

        lines.append(f"## {name} {version}")
        lines.append("")

        if not license_paths:
            lines.append(f"_No license files found for {name}._")
            lines.append("")
            continue

        seen_texts: set[str] = set()
        for lpath in license_paths:
            text = read_text(lpath).strip()
            if not text or text in seen_texts:
                continue
            seen_texts.add(text)

            license_type = classify_license(text)
            lines.append(f"**License:** {license_type}")
            lines.append("")
            lines.append("```")
            lines.append(text)
            lines.append("```")
            lines.append("")

    return "\n".join(lines)


def main() -> None:
    notice = generate()
    NOTICE_FILE.write_text(notice, encoding="utf-8")
    print(f"Wrote {NOTICE_FILE}")


if __name__ == "__main__":
    main()
