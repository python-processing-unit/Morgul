"""Inspect installed package metadata for license information."""

from importlib import metadata

packages = [
    "argon2-cffi",
    "argon2-cffi-bindings",
    "cffi",
    "pycparser",
    "markdown-it-py",
    "mdurl",
    "mdit-py-plugins",
    "pynacl",
    "pyside6-essentials",
    "shiboken6",
    "typing-extensions",
    "zstandard",
    "zxcvbn",
    "pytest",
    "colorama",
    "iniconfig",
    "packaging",
    "pluggy",
    "pygments",
    "ruff",
    "ty",
]


def _inspect_package(pkg: str) -> None:
    """Print metadata fields for a single installed package."""
    dist = metadata.distribution(pkg)
    meta = dist.metadata
    _version = meta["Version"] or "UNKNOWN"
    _lic = meta["License"] or "UNKNOWN"
    _author = meta["Author"] or "UNKNOWN"
    _home_page = meta["Home-page"] or "UNKNOWN"
    _summary = meta["Summary"] or "UNKNOWN"
    classifiers = meta.get_all("Classifier", []) or []
    _license_classifiers = [c for c in classifiers if "License" in c]


def _is_installed(pkg: str) -> bool:
    """Return True if the package is installed."""
    try:
        metadata.distribution(pkg)
    except metadata.PackageNotFoundError:
        return False
    return True


def _main() -> None:
    """Inspect all packages, skipping missing ones."""
    for pkg in filter(_is_installed, packages):
        _inspect_package(pkg)


_main()
