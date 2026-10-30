import unittest
from ql5050px.auto_layout import first_angle_layout, position_for_outline_center
from ql5050px.drawing_verification import default_frame_mm, default_title_block_mm, view_exceeds_frame


def _box(center, size):
    return [center[0]-size[0]/2, center[1]-size[1]/2, center[0]+size[0]/2, center[1]+size[1]/2]


def _overlaps(a, b):
    return min(a[2],b[2])-max(a[0],b[0])>0.1 and min(a[3],b[3])-max(a[1],b[1])>0.1


def _outline(center, size, anchor, compensated):
    position=position_for_outline_center(center, anchor) if compensated else list(center)
    landed=[position[0]-anchor[0], position[1]-anchor[1]]
    return _box(landed, size)


class AutoLayoutTests(unittest.TestCase):
    def test_six_cells_at_fixed_scale(self):
        # Paper mm at 1:10. 1:5 doubles them; 1:20 halves them. These envelopes
        # do not fit A3 at 1:10 or either sheet at 1:5, so the scale stays put.
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
                        frame=default_frame_mm(w,h)
                        boxes={name:_box(positions[name], sizes[name]) for name in positions}
                        for name,box in boxes.items():
                            self.assertFalse(view_exceeds_frame(box, frame), name)
                        self.assertFalse(any(_overlaps(a,b) for i,a in enumerate(boxes.values()) for b in list(boxes.values())[i+1:]))
                        self.assertFalse(any(_overlaps(box, default_title_block_mm(w)) for box in boxes.values()))
    def test_outline_anchor_keeps_a3_top_and_a2_front_inside_the_frame(self):
        # Same failure names as D4: A3 top hangs below Position; A2 at 1:5 front
        # sits above it. The requested scale is not changed to make them fit.
        a3_sizes={'front':[90,70],'top':[90,80],'right':[70,70]}
        a3=first_angle_layout(420,297,a3_sizes)
        a3_anchor={'front':[0,0],'top':[0,40],'right':[0,0]}
        frame=default_frame_mm(420,297)
        self.assertTrue(view_exceeds_frame(_outline(a3['top'], a3_sizes['top'], a3_anchor['top'], False), frame))
        for name,size in a3_sizes.items():
            self.assertFalse(view_exceeds_frame(_outline(a3[name], size, a3_anchor[name], True), frame))
        a2_sizes={'front':[100,180],'top':[100,180],'right':[120,180]}
        a2=first_angle_layout(594,420,a2_sizes)
        a2_frame=default_frame_mm(594,420)
        front_anchor=[0,-40]
        self.assertTrue(view_exceeds_frame(_outline(a2['front'], a2_sizes['front'], front_anchor, False), a2_frame))
        self.assertFalse(view_exceeds_frame(_outline(a2['front'], a2_sizes['front'], front_anchor, True), a2_frame))
    def test_anchor_is_added_to_the_outline_center(self):
        self.assertEqual(position_for_outline_center([10,20],[3,-4]),[13,16])
        with self.assertRaises(ValueError):position_for_outline_center([1,2],[float('nan'),0])
    def test_invalid_dimensions_rejected(self):
        with self.assertRaises(ValueError):first_angle_layout(594,420,{'front':[0,2],'top':[2,2],'right':[2,2]})

if __name__=='__main__':unittest.main()
