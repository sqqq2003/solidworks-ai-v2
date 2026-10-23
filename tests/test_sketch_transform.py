"""Model-to-sketch uses SOLIDWORKS row-vector affine transform layout."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import unittest
from solidworks_generator import _transform_to_sketch


class SketchTransformTests(unittest.TestCase):
    def test_quarter_turn_does_not_use_inverse_rotation(self):
        transform = (0,1,0, -1,0,0, 0,0,1, .01,.02,0, 1,0,0,0)
        x, y = _transform_to_sketch(transform, (.03,.04,0))
        self.assertAlmostEqual(x, -.03)
        self.assertAlmostEqual(y, .05)

    def test_non_xy_model_point_maps_to_sketch_origin(self):
        # Sketch basis x=(1,0,0), y=(0,0,1); origin=(1,2,3).
        transform = (1,0,0, 0,0,-1, 0,1,0, -1,-3,2, 1,0,0,0)
        self.assertEqual(_transform_to_sketch(transform, (1,2,3)), (0,0))
        self.assertEqual(_transform_to_sketch(transform, (2,2,5)), (1,2))

    def test_scale_precedes_translation(self):
        transform = (1,0,0, 0,1,0, 0,0,1, 10,20,30, 2,0,0,0)
        self.assertEqual(_transform_to_sketch(transform, (1,2,3)), (12,24))

    def test_identity_and_translation_stay_compatible(self):
        transform = (1,0,0, 0,1,0, 0,0,1, -.03,.01,0, 1,0,0,0)
        x,y = _transform_to_sketch(transform, (.03,.04,0))
        self.assertAlmostEqual(x, 0)
        self.assertAlmostEqual(y, .05)

    def test_invalid_transform_is_refused_before_sketch_write(self):
        for transform in ((1,)*12, (1,)*12+(0,), (1,)*12+(float('nan'),)):
            with self.subTest(transform=transform):
                with self.assertRaises(ValueError):
                    _transform_to_sketch(transform, (0,0,0))
