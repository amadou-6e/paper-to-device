"""Regression tests for layout detector cluster filtering."""

import unittest

from src.layout_detector import compute_margin_from_layout_clusters


class _FakeOrigin:
    def __init__(self, name: str):
        self.name = name


class _FakeBBox:
    def __init__(self, l: float, t: float, r: float, b: float, origin: str = "TOPLEFT"):
        self.l = l
        self.t = t
        self.r = r
        self.b = b
        self.coord_origin = _FakeOrigin(origin)

    def to_top_left_origin(self, page_height: float):
        # Convert from bottom-left to top-left origin.
        return _FakeBBox(
            l=self.l,
            t=page_height - self.b,
            r=self.r,
            b=page_height - self.t,
            origin="TOPLEFT",
        )


class _FakeLabel:
    def __init__(self, name: str):
        self.name = name


class _FakeCluster:
    def __init__(self, label_name: str, bbox: _FakeBBox):
        self.label = _FakeLabel(label_name)
        self.bbox = bbox


class LayoutDetectorRegressionTests(unittest.TestCase):
    def test_excludes_page_header_and_footer_labels(self):
        # Header/footer should be ignored when building the union crop box.
        clusters = [
            _FakeCluster("PAGE_HEADER", _FakeBBox(18.0, 165.0, 36.0, 555.0)),
            _FakeCluster("TEXT", _FakeBBox(108.0, 74.0, 504.0, 687.0)),
            _FakeCluster("PAGE_FOOTER", _FakeBBox(100.0, 734.0, 460.0, 742.0)),
        ]

        margin = compute_margin_from_layout_clusters(clusters, page_height_pts=792.0, dpi=100)

        self.assertIsNotNone(margin)
        self.assertEqual(margin["left"], 142)
        self.assertEqual(margin["top"], 94)
        self.assertEqual(margin["right"], 708)
        self.assertEqual(margin["bottom"], 962)

    def test_returns_none_when_only_excluded_labels_exist(self):
        clusters = [
            _FakeCluster("PAGE_HEADER", _FakeBBox(18.0, 165.0, 36.0, 555.0)),
            _FakeCluster("PAGE_FOOTER", _FakeBBox(100.0, 734.0, 460.0, 742.0)),
        ]

        margin = compute_margin_from_layout_clusters(clusters, page_height_pts=792.0, dpi=100)

        self.assertIsNone(margin)

    def test_converts_bottom_left_coordinates_to_top_left(self):
        clusters = [
            _FakeCluster("TEXT", _FakeBBox(100.0, 100.0, 500.0, 200.0, origin="BOTTOMLEFT")),
        ]

        margin = compute_margin_from_layout_clusters(clusters, page_height_pts=800.0, dpi=100)

        self.assertIsNotNone(margin)
        # Top-left converted bbox is (100,600,500,700) before pixel conversion + padding.
        self.assertEqual(margin["left"], 130)
        self.assertEqual(margin["top"], 825)
        self.assertEqual(margin["right"], 702)
        self.assertEqual(margin["bottom"], 980)

    def test_excludes_tall_narrow_left_edge_annotation_when_separated_from_body(self):
        clusters = [
            _FakeCluster("TEXT", _FakeBBox(18.0, 120.0, 34.0, 620.0)),
            _FakeCluster("TEXT", _FakeBBox(108.0, 74.0, 504.0, 687.0)),
        ]

        margin = compute_margin_from_layout_clusters(
            clusters,
            page_height_pts=792.0,
            dpi=100,
            page_width_pts=612.0,
        )

        self.assertIsNotNone(margin)
        self.assertEqual(margin["left"], 142)
        self.assertEqual(margin["top"], 94)
        self.assertEqual(margin["right"], 708)
        self.assertEqual(margin["bottom"], 962)

    def test_keeps_left_edge_body_content_when_not_narrow_annotation(self):
        clusters = [
            _FakeCluster("TEXT", _FakeBBox(24.0, 90.0, 220.0, 700.0)),
            _FakeCluster("TEXT", _FakeBBox(240.0, 90.0, 520.0, 700.0)),
        ]

        margin = compute_margin_from_layout_clusters(
            clusters,
            page_height_pts=792.0,
            dpi=100,
            page_width_pts=612.0,
        )

        self.assertIsNotNone(margin)
        self.assertEqual(margin["left"], 25)
        self.assertEqual(margin["top"], 117)
        self.assertEqual(margin["right"], 730)
        self.assertEqual(margin["bottom"], 980)


if __name__ == "__main__":
    unittest.main()
