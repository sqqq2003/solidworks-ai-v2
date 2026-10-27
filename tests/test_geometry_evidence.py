"""Offline geometry evidence checks; fake observations, no SolidWorks."""
import copy
import math
import unittest
from geometry_evidence import compare_snapshots


class GeometryEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.before={'schema_version':1,'identity':{'source_sha256':'a'*64,
            'document_key':'roller','configuration':'Default','document_confirmed':True,
            'configuration_confirmed':True},'rebuilt':True,
            'body_count':1,'bounds_mm':[0,0,0,100,20,20],'volume_mm3':1000,
            'dimensions_mm':{'length':100,'shaft_diameter':10}}
        self.after=copy.deepcopy(self.before)
        self.after['bounds_mm']=[0,0,0,110,20,20]
        self.after['dimensions_mm']['length']=110
        self.checks=[{'field':'dimension:length','mode':'target','value':110,'unit':'mm','tolerance':.01},
                     {'field':'dimension:shaft_diameter','mode':'unchanged','unit':'mm','tolerance':.01}]

    def compare(self,checks=None):
        return compare_snapshots(self.before,self.after,self.checks if checks is None else checks,step_id='trial-1')

    def test_expected_change_and_protected_interface_still_pending_engineering(self):
        report=self.compare()
        self.assertEqual(report['status'],'observations_consistent_pending_engineering')
        self.assertEqual(report['checks'][0]['delta'],10)
        self.assertFalse(report['production_approved']);self.assertFalse(report['geometry_verified'])

    def test_unchanged_or_bad_interface_is_failure(self):
        self.after['dimensions_mm']['length']=100
        self.assertEqual(self.compare()['status'],'failed')
        self.after['dimensions_mm']['length']=110;self.after['dimensions_mm']['shaft_diameter']=11
        self.assertEqual(self.compare()['status'],'failed')

    def test_missing_tolerance_or_measurement_never_passes(self):
        self.assertEqual(self.compare([{'field':'dimension:length','mode':'target','unit':'mm'}])['status'],'review_required')
        self.after['dimensions_mm']['length']=None
        self.assertEqual(self.compare()['status'],'review_required')
        self.assertEqual(self.compare([])['status'],'review_required')

    def test_unknown_or_failed_rebuild_not_success(self):
        self.after['rebuilt']=None;self.assertEqual(self.compare()['status'],'review_required')
        self.after['rebuilt']=False;self.assertEqual(self.compare()['status'],'failed')

    def test_nan_units_and_identity_mismatch_refused(self):
        self.after['volume_mm3']=math.nan
        with self.assertRaises(ValueError):self.compare()
        self.after['volume_mm3']=1000
        with self.assertRaises(ValueError):self.compare([{'field':'volume_mm3','mode':'target','unit':'mm','value':1000,'tolerance':1}])
        self.after['identity']['configuration']='Other'
        with self.assertRaises(ValueError):self.compare()

    def test_unconfirmed_configuration_is_not_an_identity(self):
        self.before['identity']['configuration_confirmed']=False
        self.after['identity']['configuration_confirmed']=False
        with self.assertRaisesRegex(ValueError,'unconfirmed'):
            self.compare()

    def test_approximate_extent_change_remains_unverified_as_geometry(self):
        report=self.compare([{'field':'extent_x_mm','mode':'delta','unit':'mm','value':10,'tolerance':.1}])
        self.assertEqual(report['checks'][0]['status'],'observed_consistent')
        self.assertFalse(report['geometry_verified'])


if __name__=='__main__':unittest.main()
