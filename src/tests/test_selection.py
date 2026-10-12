import unittest

from PySide6.QtCore import QPoint, QRect

from glance.ui.selection import (
    Handle,
    clamp_point,
    hit_test,
    moved,
    rect_from_points,
    resized,
)

DESKTOP = QRect(0, 0, 1000, 500)


class RectFromPointsTest(unittest.TestCase):
    def test_any_corner_order_gives_the_same_rectangle(self) -> None:
        expected = QRect(10, 20, 30, 40)
        for first, second in (
            (QPoint(10, 20), QPoint(40, 60)),
            (QPoint(40, 60), QPoint(10, 20)),
            (QPoint(40, 20), QPoint(10, 60)),
            (QPoint(10, 60), QPoint(40, 20)),
        ):
            self.assertEqual(rect_from_points(first, second), expected)


class ClampPointTest(unittest.TestCase):
    def test_points_outside_are_pulled_to_the_edge(self) -> None:
        self.assertEqual(clamp_point(QPoint(-5, 900), DESKTOP), QPoint(0, 500))

    def test_points_inside_are_unchanged(self) -> None:
        self.assertEqual(clamp_point(QPoint(5, 6), DESKTOP), QPoint(5, 6))


class HitTestTest(unittest.TestCase):
    rect = QRect(100, 100, 200, 100)

    def hit(self, x: int, y: int) -> Handle | None:
        return hit_test(self.rect, QPoint(x, y), 10)

    def test_corners_and_edges(self) -> None:
        self.assertIs(self.hit(100, 100), Handle.TOP_LEFT)
        self.assertIs(self.hit(300, 100), Handle.TOP_RIGHT)
        self.assertIs(self.hit(300, 200), Handle.BOTTOM_RIGHT)
        self.assertIs(self.hit(100, 200), Handle.BOTTOM_LEFT)
        self.assertIs(self.hit(200, 100), Handle.TOP)
        self.assertIs(self.hit(200, 200), Handle.BOTTOM)
        self.assertIs(self.hit(100, 150), Handle.LEFT)
        self.assertIs(self.hit(300, 150), Handle.RIGHT)

    def test_edges_can_be_grabbed_from_just_outside(self) -> None:
        self.assertIs(self.hit(95, 150), Handle.LEFT)

    def test_inside_moves_and_far_outside_misses(self) -> None:
        self.assertIs(self.hit(200, 150), Handle.MOVE)
        self.assertIsNone(self.hit(50, 150))
        self.assertIsNone(self.hit(200, 300))

    def test_small_selections_can_still_be_moved(self) -> None:
        small = QRect(100, 100, 12, 12)
        self.assertIs(hit_test(small, QPoint(106, 106), 10), Handle.MOVE)


class ResizedTest(unittest.TestCase):
    rect = QRect(100, 100, 200, 100)

    def test_right_edge_follows_the_pointer(self) -> None:
        result = resized(self.rect, Handle.RIGHT, QPoint(400, 999), DESKTOP)
        self.assertEqual(result, QRect(100, 100, 300, 100))

    def test_corner_moves_both_edges(self) -> None:
        result = resized(self.rect, Handle.TOP_LEFT, QPoint(50, 60), DESKTOP)
        self.assertEqual(result, QRect(50, 60, 250, 140))

    def test_dragging_past_the_opposite_edge_flips_the_rectangle(self) -> None:
        result = resized(self.rect, Handle.LEFT, QPoint(350, 0), DESKTOP)
        self.assertEqual(result, QRect(300, 100, 50, 100))

    def test_stays_inside_the_desktop(self) -> None:
        result = resized(self.rect, Handle.BOTTOM_RIGHT, QPoint(5000, 5000), DESKTOP)
        self.assertEqual(result, QRect(100, 100, 900, 400))


class MovedTest(unittest.TestCase):
    rect = QRect(100, 100, 200, 100)

    def test_shifts_by_the_delta(self) -> None:
        self.assertEqual(
            moved(self.rect, QPoint(10, -20), DESKTOP), QRect(110, 80, 200, 100)
        )

    def test_stops_at_the_desktop_edges(self) -> None:
        self.assertEqual(
            moved(self.rect, QPoint(-500, 900), DESKTOP), QRect(0, 400, 200, 100)
        )
        self.assertEqual(
            moved(self.rect, QPoint(5000, -500), DESKTOP), QRect(800, 0, 200, 100)
        )
