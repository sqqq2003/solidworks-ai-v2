import unittest
from ql5050px.auto_layout import first_angle_layout

class AutoLayoutTests(unittest.TestCase):
    def test_six_cells_at_fixed_scale(self):
        measured={'front':[110.5,143.0],'top':[110.5,180.32],'right':[180.32,143.0]}
        for sheet,w,h in [('A2',594,420),('A3',420,297)]:
            for denominator in [5,10,20]:
                sizes={k:[n*10/denominator for n in v] for k,v in measured.items()}
                with self.subTest(sheet=sheet,scale=denominator):
                    if denominator==5 or (sheet=='A3' and denominator==10):
                        with self.assertRaisesRegex(ValueError,'does_not_fit'):first_angle_layout(w,h,sizes)
                    else:
                        positions=first_angle_layout(w,h,sizes)
                        self.assertLess(positions['right'][0],positions['front'][0])
                        self.assertLess(positions['top'][1],positions['front'][1])
                        self.assertEqual(positions['top'][0],positions['front'][0])
    def test_invalid_dimensions_rejected(self):
        with self.assertRaises(ValueError):first_angle_layout(594,420,{'front':[0,2],'top':[2,2],'right':[2,2]})

if __name__=='__main__':unittest.main()
