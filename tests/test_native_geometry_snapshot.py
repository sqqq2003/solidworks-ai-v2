"""Fake COM contract tests for owned part snapshot capture."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import MagicMock,patch

from native_geometry_snapshot import capture_owned_part,_sha


class NativeGeometrySnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'source.SLDPRT';self.copy=self.root/'copy.SLDPRT'
        self.source.write_bytes(b'baseline');self.copy.write_bytes(b'work copy')
        self.mass=NS(Volume=0.000001)
        self.model=NS(GetTitle='copy.SLDPRT',GetPathName=str(self.copy),GetType=1,
            ConfigurationManager=NS(ActiveConfiguration=NS(Name='Default')),
            EditRebuild3=True,Extension=NS(CreateMassProperty=lambda:self.mass))
        self.driver=NS(lease=NS(owned_docs={'copy.SLDPRT':NS(handle_id=id(self.model))}),
                       guard=MagicMock(),owned_path=lambda p:Path(p).resolve())
        self.options=dict(source_path=self.source,source_sha256=_sha(self.source),document_key='part-1',
                          configuration='Default',step_id='step-1',phase='before')
        self.patches=[patch('native_geometry_snapshot.sw.ensure_solidworks_typelib',return_value='lib'),
            patch('native_geometry_snapshot.sw._as_interface',return_value='part'),
            patch('native_geometry_snapshot.solid_inventory',return_value=([0,0,0,10,20,30],[[0,0,0,10,20,30]])),
            patch('native_geometry_snapshot.get_journal',return_value=MagicMock())]
        for p in self.patches:p.start();self.addCleanup(p.stop)

    def test_snapshot_is_identity_bound_and_never_claims_production(self):
        result=capture_owned_part(self.driver,self.model,**self.options)
        self.assertEqual(result['body_count'],1);self.assertAlmostEqual(result['volume_mm3'],1000)
        self.assertEqual(result['bounds_mm'],[0,0,0,10,20,30])
        self.assertEqual(result['identity']['source_sha256'],_sha(self.source))
        self.assertFalse(result['production_approved']);self.assertFalse(result['geometry_verified'])
        self.assertGreaterEqual(self.driver.guard.call_count,2)

    def test_foreign_handle_and_changed_source_refused(self):
        self.driver.lease.owned_docs['copy.SLDPRT'].handle_id=123
        with self.assertRaisesRegex(RuntimeError,'exact task-owned'):
            capture_owned_part(self.driver,self.model,**self.options)
        self.driver.lease.owned_docs['copy.SLDPRT'].handle_id=id(self.model)
        self.source.write_bytes(b'changed')
        with self.assertRaisesRegex(RuntimeError,'baseline hash'):
            capture_owned_part(self.driver,self.model,**self.options)

    def test_wrong_configuration_bad_volume_and_failed_rebuild_are_not_passes(self):
        self.model.ConfigurationManager.ActiveConfiguration.Name='Other'
        with self.assertRaisesRegex(RuntimeError,'configuration'):
            capture_owned_part(self.driver,self.model,**self.options)
        self.model.ConfigurationManager.ActiveConfiguration.Name='Default'
        self.model.EditRebuild3=False
        with self.assertRaisesRegex(RuntimeError,'rebuild'):
            capture_owned_part(self.driver,self.model,**self.options)
        self.model.EditRebuild3=True;self.mass.Volume=float('nan')
        with self.assertRaisesRegex(RuntimeError,'volume'):
            capture_owned_part(self.driver,self.model,**self.options)

    def test_original_cannot_be_used_as_the_work_copy(self):
        self.model.GetPathName=str(self.source)
        with self.assertRaisesRegex(RuntimeError,'distinct'):
            capture_owned_part(self.driver,self.model,**self.options)

    def test_callable_com_mass_property_is_not_called_as_default_member(self):
        class MassProperty:
            def __init__(self):self._oleobj_=object();self.Volume=.000001
            def __call__(self):raise AssertionError('COM mass object was invoked')
        self.model.Extension=NS(CreateMassProperty=MassProperty())
        result=capture_owned_part(self.driver,self.model,**self.options)
        self.assertAlmostEqual(result['volume_mm3'],1000)


if __name__=='__main__':unittest.main()
