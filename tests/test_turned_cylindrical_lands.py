import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from turned_generate import _fit_chain
from turned_outline import _upper_envelope


class CylindricalLandTests(unittest.TestCase):
    def test_dense_fillet_events_do_not_hide_the_following_shaft_land(self):
        envelope = _upper_envelope([(0, 5, 10, 5), (10, 5, 10.01, 4.8),
                                   (10.01, 4.8, 10.02, 4.6),
                                   (10.02, 4.6, 10.03, 4), (10.03, 4, 13, 4)])
        self.assertIn((10.03, 4), envelope)
        self.assertIn((13, 4), envelope)

    def test_long_cylinder_does_not_absorb_small_fillet(self):
        self.assertIsNone(_fit_chain([(0, 5), (40, 5), (40.04, 4.997)]))

    def test_straight_land_still_simplifies(self):
        fitted = _fit_chain([(0, 5), (20, 5), (40, 5)])
        self.assertEqual(fitted.kind, 'line')
        self.assertEqual(fitted.end, (40, 5))

    def test_shoulder_does_not_absorb_adjacent_curve(self):
        self.assertIsNone(_fit_chain([(40, 5), (40, 2), (40.003, 1.96)]))
