"""Selection geometry for the capture overlay.

Everything here works on plain rectangles in logical desktop coordinates and
needs no widgets, so it can be tested without a display. Rectangles are treated
as half-open: a rectangle at x with width w covers x up to, but not including,
x + w.
"""

from enum import Enum, auto

from PySide6.QtCore import QPoint, QRect


class Handle(Enum):
    TOP_LEFT = auto()
    TOP = auto()
    TOP_RIGHT = auto()
    RIGHT = auto()
    BOTTOM_RIGHT = auto()
    BOTTOM = auto()
    BOTTOM_LEFT = auto()
    LEFT = auto()
    MOVE = auto()


_MOVES_LEFT = {Handle.TOP_LEFT, Handle.LEFT, Handle.BOTTOM_LEFT}
_MOVES_RIGHT = {Handle.TOP_RIGHT, Handle.RIGHT, Handle.BOTTOM_RIGHT}
_MOVES_TOP = {Handle.TOP_LEFT, Handle.TOP, Handle.TOP_RIGHT}
_MOVES_BOTTOM = {Handle.BOTTOM_LEFT, Handle.BOTTOM, Handle.BOTTOM_RIGHT}

_BY_EDGES: dict[tuple[int, int], Handle] = {
    (-1, -1): Handle.TOP_LEFT,
    (0, -1): Handle.TOP,
    (1, -1): Handle.TOP_RIGHT,
    (1, 0): Handle.RIGHT,
    (1, 1): Handle.BOTTOM_RIGHT,
    (0, 1): Handle.BOTTOM,
    (-1, 1): Handle.BOTTOM_LEFT,
    (-1, 0): Handle.LEFT,
}


def rect_from_points(first: QPoint, second: QPoint) -> QRect:
    """The rectangle between two points, whichever corner each one is."""
    left, right = sorted((first.x(), second.x()))
    top, bottom = sorted((first.y(), second.y()))
    return QRect(left, top, right - left, bottom - top)


def clamp_point(point: QPoint, bounds: QRect) -> QPoint:
    """The nearest point inside `bounds`, edges included."""
    return QPoint(
        min(max(point.x(), bounds.left()), bounds.left() + bounds.width()),
        min(max(point.y(), bounds.top()), bounds.top() + bounds.height()),
    )


def hit_test(rect: QRect, point: QPoint, tolerance: int) -> Handle | None:
    """The handle under `point`, or None if the point is outside the selection.

    Edges and corners respond within `tolerance` of the border, on both sides.
    The tolerance shrinks for small selections so that their middle can still be
    grabbed to move them.
    """
    tolerance_x = min(tolerance, rect.width() // 3)
    tolerance_y = min(tolerance, rect.height() // 3)
    left, top = rect.left(), rect.top()
    right, bottom = left + rect.width(), top + rect.height()

    grabbable = rect.adjusted(-tolerance_x, -tolerance_y, tolerance_x, tolerance_y)
    if not grabbable.contains(point):
        return None

    horizontal = 0
    if abs(point.x() - left) <= tolerance_x:
        horizontal = -1
    elif abs(point.x() - right) <= tolerance_x:
        horizontal = 1
    vertical = 0
    if abs(point.y() - top) <= tolerance_y:
        vertical = -1
    elif abs(point.y() - bottom) <= tolerance_y:
        vertical = 1

    if (horizontal, vertical) in _BY_EDGES:
        return _BY_EDGES[horizontal, vertical]
    return Handle.MOVE if rect.contains(point) else None


def resized(rect: QRect, handle: Handle, point: QPoint, bounds: QRect) -> QRect:
    """`rect` with the edges of `handle` dragged to `point`.

    Dragging an edge past the opposite one flips the rectangle, as it does when
    drawing a new selection.
    """
    point = clamp_point(point, bounds)
    left, top = rect.left(), rect.top()
    right, bottom = left + rect.width(), top + rect.height()

    if handle in _MOVES_LEFT:
        left = point.x()
    elif handle in _MOVES_RIGHT:
        right = point.x()
    if handle in _MOVES_TOP:
        top = point.y()
    elif handle in _MOVES_BOTTOM:
        bottom = point.y()
    return rect_from_points(QPoint(left, top), QPoint(right, bottom))


def moved(rect: QRect, delta: QPoint, bounds: QRect) -> QRect:
    """`rect` shifted by `delta`, stopping at the edges of `bounds`."""
    x = min(
        max(rect.x() + delta.x(), bounds.left()),
        bounds.left() + bounds.width() - rect.width(),
    )
    y = min(
        max(rect.y() + delta.y(), bounds.top()),
        bounds.top() + bounds.height() - rect.height(),
    )
    return QRect(x, y, rect.width(), rect.height())
