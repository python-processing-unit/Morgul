"""Tiny SVG → QIcon helpers (no emoji, no bitmap assets on disk)."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# 16x16 strokes; ``currentColor`` is replaced by the colour arg below.
_CLOSE_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="none">
  <path d="M4.5 4.5l7 7M11.5 4.5l-7 7" stroke="currentColor"
        stroke-width="1.5" stroke-linecap="round"/>
</svg>
"""

_PLUS_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="none">
  <path d="M8 3.5v9M3.5 8h9" stroke="currentColor"
        stroke-width="1.5" stroke-linecap="round"/>
</svg>
"""

_EYE_OPEN_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="none">
  <path d="M1.5 8s2.5-4.5 6.5-4.5S14.5 8 14.5 8s-2.5 4.5-6.5 4.5S1.5 8 1.5 8z"
        stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/>
  <circle cx="8" cy="8" r="2" stroke="currentColor" stroke-width="1.4"/>
</svg>
"""

_EYE_OFF_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="none">
  <path d="M1.5 8s2.5-4.5 6.5-4.5S14.5 8 14.5 8s-2.5 4.5-6.5 4.5S1.5 8 1.5 8z"
        stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/>
  <circle cx="8" cy="8" r="2" stroke="currentColor" stroke-width="1.4"/>
  <path d="M3 13L13 3" stroke="currentColor" stroke-width="1.4"
        stroke-linecap="round"/>
</svg>
"""


def _paint_svg(svg: str, *, colour: str, size: int) -> QIcon:
    """Rasterize an SVG into a square icon with its current color replaced.

    Args:
        svg (str): SVG markup to render.
        colour (str): Replacement for ``currentColor`` in the SVG markup.
        size (int): Width and height of the rendered icon in pixels.

    Returns:
        QIcon: An icon backed by a transparent pixmap.
    """
    coloured = svg.replace("currentColor", colour)
    renderer = QSvgRenderer(QByteArray(coloured.encode("utf-8")))
    # QIcon wants a QPixmap; paint the SVG into one (not a bare QImage).
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return QIcon(pixmap)


def close_icon(*, size: int = 14) -> QIcon:
    """Create a gray tab-close icon.

    Args:
        size (int): Width and height of the icon in pixels.

    Returns:
        QIcon: The tab-close icon.
    """
    return _paint_svg(_CLOSE_SVG, colour="#c8c8c8", size=size)


def close_icon_hover(*, size: int = 14) -> QIcon:
    """Create a white close icon for hover states.

    Args:
        size (int): Size passed to the icon renderer.

    Returns:
        QIcon: The rendered close icon.
    """
    return _paint_svg(_CLOSE_SVG, colour="#ffffff", size=size)


def new_tab_icon(*, size: int = 16) -> QIcon:
    """Create a grey plus icon.

    Args:
        size (int): The icon size in pixels.

    Returns:
        QIcon: The grey plus icon.
    """
    return _paint_svg(_PLUS_SVG, colour="#c8c8c8", size=size)


def eye_open_icon(*, size: int = 16) -> QIcon:
    """Create a grey open-eye icon.

    Args:
        size (int): Size passed to the SVG renderer.

    Returns:
        QIcon: The rendered open-eye icon.
    """
    return _paint_svg(_EYE_OPEN_SVG, colour="#c8c8c8", size=size)


def eye_off_icon(*, size: int = 16) -> QIcon:
    """Create a grey slashed-eye icon.

    Args:
        size (int): Icon size in pixels.

    Returns:
        QIcon: The grey slashed-eye icon.
    """
    return _paint_svg(_EYE_OFF_SVG, colour="#c8c8c8", size=size)
