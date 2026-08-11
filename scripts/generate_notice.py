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
PYPROJECT = REPO_ROOT / "pyproject.toml"

_LICENSE_PATTERN = re.compile(
    r"^(LICENSE|COPYING|NOTICE|LICENSE\..+|LicenseRef.+)$",
    re.IGNORECASE,
)


def _parse_pyproject_deps(path: Path) -> tuple[set[str], set[str]]:
    """Return (direct_names, dev_names) from pyproject.toml."""
    with path.open("rb") as fh:
        data = tomllib.load(fh)

    def _normalize(specs: list[str]) -> set[str]:
        names: set[str] = set()
        for spec in specs:
            name = spec.strip()
            for sep in (">=", "<=", "==", "!=", "~=", ">", "<"):
                name = name.split(sep)[0]
            names.add(name.strip())
        return names

    direct = _normalize(data.get("project", {}).get("dependencies", []))
    dev = _normalize(data.get("dependency-groups", {}).get("dev", []))
    return direct, dev


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
    direct_deps, dev_deps = _parse_pyproject_deps(PYPROJECT)

    direct: dict[str, dict[str, Any]] = {}
    dev: dict[str, dict[str, Any]] = {}
    transitive: dict[str, dict[str, Any]] = {}

    for name, pkg in packages.items():
        if name == "morgul":
            continue
        if name in direct_deps:
            direct[name] = pkg
        elif name in dev_deps:
            dev[name] = pkg
        else:
            transitive[name] = pkg

    lines: list[str] = [
        "# Copyright and Attribution Notices",
        "",
        "This file lists copyright and attribution notices for the software and all",
        "of its dependencies (direct, dev, and transitive).",
        "",
        "Generated from `uv.lock` and installed package license files.",
        "",
    ]

    if PROJECT_LICENSE.exists():
        proj_text = read_text(PROJECT_LICENSE).strip()
        if proj_text:
            lines.extend((
                "## Morgul",
                "",
                "```",
                proj_text,
                "```",
                "",
            ))

    _render_section(lines, "## Direct Dependencies", direct)
    _render_section(lines, "## Development Dependencies", dev)
    _render_section(lines, "## Transitive Dependencies", transitive)

    return "\n".join(lines)


def _render_section(
    lines: list[str],
    title: str,
    pkgs: dict[str, dict[str, Any]],
) -> None:
    lines.extend((title, ""))
    if not pkgs:
        lines.extend(("_None._", ""))
        return
    for name, pkg in sorted(pkgs.items()):
        _render_package(lines, name, pkg)


def _render_package(lines: list[str], name: str, pkg: dict[str, Any]) -> None:
    version = pkg.get("version", "unknown")
    license_paths = find_license_files(name, version)
    lines.extend((f"### {name} {version}", ""))
    if not license_paths:
        lines.extend((f"_No license files found for {name}._", ""))
        return
    seen_texts: set[str] = set()
    for license_path in license_paths:
        text = read_text(license_path).strip()
        if not text or text in seen_texts:
            continue
        seen_texts.add(text)
        lines.extend(("```", text, "```", ""))


def main() -> None:
    """Generate NOTICE.md and write it to disk."""
    notice = generate()
    NOTICE_FILE.write_text(notice, encoding="utf-8")


if __name__ == "__main__":
    main()
