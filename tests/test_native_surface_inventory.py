import unittest
from types import SimpleNamespace as NS

from native_surface_inventory import cylindrical_surface_inventory


class NativeSurfaceInventoryTests(unittest.TestCase):
    def inventory(self, params):
        surface = NS(IsCylinder=True, CylinderParams=params)
        body = NS(GetFaces=lambda: [NS(GetSurface=surface)])
        part = NS(GetBodies2=lambda *_: [body])
        sw = NS(SW_BODY_TYPE_SOLID=0, _as_interface=lambda _, x, __: x,
                _com_read=lambda obj, key: getattr(obj, key))
        return cylindrical_surface_inventory(part, sw, None)

    def test_si_units_are_always_metres_even_for_large_radii(self):
        result = self.inventory([.053, 0, .005, 0, 0, -1, 1.5])
        self.assertEqual(result['faces'][0]['diameter_mm'], 3000)
        self.assertEqual(result['faces'][0]['axis_point_mm'], [53, 0, 5])
        self.assertFalse(result['geometry_verified'])

    def test_unknown_or_corrupt_geometry_fails_instead_of_claiming_no_holes(self):
        for params in ([0]*7, [0]*6, [0,0,0,0,0,1,float('nan')]):
            with self.subTest(params=params), self.assertRaises(RuntimeError):
                self.inventory(params)
