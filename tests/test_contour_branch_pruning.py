import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from cad_analyzer import Primitive, SketchSegment, _LoopSearchBudget, _walk_closed_loop


class ContourBranchPruningTests(unittest.TestCase):
    def test_bridge_into_many_detail_cycles_cannot_exhaust_search(self):
        # A leader connects the seed to a chain of detail-table squares.
        # No edge in those squares can close a contour through the seed.
        pairs = [((-1, 0), (0, 0))]
        for i in range(18):
            x = i * 2
            pairs.extend([((x, 0), (x+1, 1)), ((x+1, 1), (x+2, 0)),
                          ((x+2, 0), (x+1, -1)), ((x+1, -1), (x, 0))])
        segments = [Primitive((a, b), False, False, 'detail', 'LINE',
                              (SketchSegment(a, b),)) for a, b in pairs]
        adjacency = {}
        for i, (a, b) in enumerate(pairs):
            adjacency.setdefault(a, []).append(i)
            adjacency.setdefault(b, []).append(i)
        budget = _LoopSearchBudget(100)
        result = _walk_closed_loop(0, set(range(len(segments))), adjacency,
                                   segments, lambda p: p, budget)
        self.assertIsNone(result)
        self.assertFalse(budget.exhausted)
        # The attached detail loops must still be available as real contours.
        result = _walk_closed_loop(1, set(range(1, len(segments))), adjacency,
                                   segments, lambda p: p, _LoopSearchBudget(100))
        self.assertIsNotNone(result)
        self.assertEqual(result[2], {1, 2, 3, 4})


if __name__ == '__main__':
    unittest.main()
