import copy
import math
import unittest

from ql5050px.repair_planning import plan_slot_relief, require_trial


class SlotReliefTests(unittest.TestCase):
    def inputs(self,**overrides):
        args=dict(source_sha256='a'*64, axis_point_mm=[10,0,-10],
                  axis_direction=[0,0,2], cylinder_radius_mm=25,
                  slot_center_mm=[0,0], existing_radius_mm=35,
                  slab_z_mm=[-1,1], trial_clearance_mm=.2,
                  radius_grid_mm=1, max_trial_increase_mm=2,
                  trial_authorized=True)
        args.update(overrides)
        return args

    def test_perpendicular_cylinder_requires_offset_plus_radius_and_clearance(self):
        plan=plan_slot_relief(**self.inputs())
        self.assertEqual(plan['target_radius_mm'],36)
        self.assertTrue(require_trial(plan,'a'*64))
        self.assertFalse(plan['production_approved'])

    def test_tilted_ellipse_is_enclosed_on_both_surfaces(self):
        args=self.inputs(axis_point_mm=[2,3,0],axis_direction=[.3,.4,.8660254037844386],existing_radius_mm=1,max_trial_increase_mm=100)
        plan=plan_slot_relief(**args)
        # Sample the analytic ellipse: major axis follows projected cylinder axis.
        a=plan['axis_direction'];normal=abs(a[2]);major=[.6,.8];minor=[-.8,.6]
        for center in plan['axis_intersections_mm']:
            for i in range(360):
                angle=math.radians(i)
                point=[center[j]+25/normal*math.cos(angle)*major[j]+25*math.sin(angle)*minor[j] for j in range(2)]
                self.assertLessEqual(math.hypot(*point),plan['conservative_required_radius_mm']+1e-10)

    def test_oversize_requires_review(self):
        plan=plan_slot_relief(**self.inputs(axis_point_mm=[20,0,0]))
        self.assertEqual(plan['status'],'review_required')
        with self.assertRaises(ValueError):require_trial(plan,'a'*64)

    def test_missing_authorization_blocks_trial(self):
        plan=plan_slot_relief(**self.inputs(trial_authorized=False))
        with self.assertRaises(ValueError):require_trial(plan,'a'*64)

    def test_changed_source_blocks_trial(self):
        with self.assertRaises(ValueError):require_trial(plan_slot_relief(**self.inputs()),'b'*64)

    def test_tampered_derived_evidence_cannot_bypass_gate(self):
        original=plan_slot_relief(**self.inputs())
        for key,value in [('target_radius_mm',100),('radius_increase_mm',100),('max_trial_increase_mm',.1),('production_approved',True),('cad_executed',True),('schema_version',2)]:
            with self.subTest(key=key):
                plan=copy.deepcopy(original);plan[key]=value
                with self.assertRaises(ValueError):require_trial(plan,'a'*64)

    def test_parallel_or_zero_axis_is_refused(self):
        for axis in ([0,0,0],[1,0,0],[1,0,1e-8]):
            with self.subTest(axis=axis),self.assertRaises(ValueError):plan_slot_relief(**self.inputs(axis_direction=axis))

    def test_invalid_numbers_are_refused(self):
        for value in (True,float('nan'),float('inf'),-1,0):
            with self.subTest(value=value),self.assertRaises(ValueError):plan_slot_relief(**self.inputs(cylinder_radius_mm=value))

    def test_invalid_units_inputs_and_authorization(self):
        for overrides in ({'slab_z_mm':[1,1]},{'axis_point_mm':None},{'trial_authorized':1},{'trial_clearance_mm':-.1},{'source_sha256':'not-hash'}):
            with self.subTest(overrides=overrides),self.assertRaises(ValueError):plan_slot_relief(**self.inputs(**overrides))

    def test_no_change_is_not_a_cad_write_authorization(self):
        plan=plan_slot_relief(**self.inputs(existing_radius_mm=40))
        self.assertEqual(plan['status'],'no_change')
        with self.assertRaises(ValueError):require_trial(plan,'a'*64)
