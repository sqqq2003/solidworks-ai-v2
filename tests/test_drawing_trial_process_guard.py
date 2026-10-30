import unittest
from src.ql5050px.drawing_trial import require_no_running_solidworks


class DrawingProcessGuardTests(unittest.TestCase):
    def test_existing_process_blocks_spawn_route(self):
        with self.assertRaisesRegex(RuntimeError,'未启动第二个实例'):
            require_no_running_solidworks(lambda:[123])

    def test_empty_verified_inventory_allows_spawn_route(self):
        self.assertTrue(require_no_running_solidworks(lambda:[])['checked'])

    def test_unavailable_or_invalid_inventory_does_not_mean_empty(self):
        def unavailable():raise OSError('inventory unavailable')
        for inventory in (unavailable,lambda:[None],lambda:[True]):
            with self.subTest(inventory=inventory),self.assertRaisesRegex(RuntimeError,'未启动新实例'):
                require_no_running_solidworks(inventory)
