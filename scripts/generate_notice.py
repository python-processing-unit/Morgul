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

_LICENSE_PATTERN = re.compile(
    r"^(LICENSE|COPYING|NOTICE|LICENSE\..+|LicenseRef.+)$",
    re.IGNORECASE,
)


def parse_uv_lock(path: Path) -> dict[str, dict[str, Any]]:
    """Return package-name -> package-table from uv.lock."""
    with path.open("rb") as fh:
        data = tomllib.load(fh)

    packages: dict[str, dict[str, Any]] = {}
    for package in data.get("package", []):
        name = package.get("name", "")
        if name:
            packages[name] = package
    return packages


def find_license_files(package_name: str, version: str) -> list[Path]:
    """Locate license/copyright files inside the installed package.

    Returns:
        Sorted list of license file paths found for the package.
    """
    base = VENV_SITE_PACKAGES
    package_stem = package_name.replace("-", "_")
    candidates = [
        *base.glob(f"{package_stem}-{version}*.dist-info"),
        *base.glob(f"{package_stem}-{version}*.whl-info"),
    ]

    # bare package directory (sometimes used for namespace / single-file pkgs)
    package_dir = base / package_stem
    if package_dir.is_dir():
        candidates.append(package_dir)

    license_paths: list[Path] = []
    for candidate in candidates:
        if candidate.is_dir():
            # look in a licenses/ sub-directory first
            licenses_dir = candidate / "licenses"
            search_root = licenses_dir if licenses_dir.is_dir() else candidate
            license_paths.extend(
                f
                for f in search_root.rglob("*")
                if f.is_file() and _LICENSE_PATTERN.match(f.name)
            )
    return sorted(set(license_paths))


def read_text(path: Path) -> str:
    """Return file contents, replacing undecodable bytes."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def generate() -> str:
    """Build the full NOTICE.md content from lock file and license files.

    Returns:
        The complete NOTICE.md file content as a string.
    """
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
            lines.extend((
                "## morgul",
                "",
                "```",
                proj_text,
                "```",
                "",
            ))

    for name, pkg in sorted(packages.items()):
        if name == "morgul":
            continue
        version = pkg.get("version", "unknown")
        license_paths = find_license_files(name, version)

        lines.extend((f"## {name} {version}", ""))

        if not license_paths:
            lines.extend((f"_No license files found for {name}._", ""))
            continue

        seen_texts: set[str] = set()
        for license_path in license_paths:
            text = read_text(license_path).strip()
            if not text or text in seen_texts:
                continue
            seen_texts.add(text)

            lines.extend(("```", text, "```", ""))

    return "\n".join(lines)


def main() -> None:
    """Generate NOTICE.md and write it to disk."""
    notice = generate()
    NOTICE_FILE.write_text(notice, encoding="utf-8")


if __name__ == "__main__":
    main()
