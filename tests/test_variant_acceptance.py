"""Offline fixtures only; these tests do not establish native CAD acceptance."""
import copy
import hashlib
import math
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'src'),str(Path(__file__).resolve().parent)]
from test_decision_bridge import fixture
from ql5050px.intelligent_scan import identity
from ql5050px.native_machine import NativeMachineDriver,verify_dimension_value
from ql5050px.variant_acceptance import prepare_case,evidence_template,audit_case,STEPS


class VariantAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        request,key=fixture()
        part=self.root/'frame.SLDPRT'
        assembly=self.root/'machine.SLDASM'
        part.write_bytes(b'synthetic part bytes, not native CAD')
        assembly.write_bytes(b'synthetic assembly bytes, not native CAD')
        doc=request['snapshot']['documents'][0]
        doc['path']=str(part)
        new_key=identity(str(part),'SIM')
        request['rules'][new_key]=request['rules'].pop(key)
        request['approvals'][0]['document_id']=new_key
        request['manufacturing']['drive']['source_assembly']=str(assembly)
        request['acceptance']={'source_kind':'oem','mapping_review_source':'test-only assertion',
            'mate_inventory_review_source':'test-only assertion','source_inventory_review_source':'test-only assertion',
            'source_files':[str(part),str(assembly)]}
        self.request=request
        self.case=prepare_case(request)

    def records(self):
        # Synthetic records exercise the consistency checker, not native authenticity.
        evidence=evidence_template(self.case)
        evidence.update(simulated_only=False,operator='unit-test',observed_at_utc='2026-10-26T00:00:00Z',source_revision='test-revision')
        evidence['session']={'ownership':'spawned_pid_and_live_handle','attached_existing':False}
        data=self.root/'fixture-evidence.txt'
        data.write_bytes(b'synthetic test evidence')
        for row in evidence['checks']:
            row.update(status='passed',artifacts=[{'path':data.name,'sha256':hashlib.sha256(data.read_bytes()).hexdigest()}])
            if row['step'].startswith('dimension_'):
                row.update(configuration='SIM',dimension='Length@Sketch1',
                    value_mm=self.case['expected']['before_mm' if row['step']=='dimension_before' else 'after_mm'])
        return evidence

    def test_preflight_ready_does_not_enable_production(self):
        self.assertEqual(self.case['status'],'preflight_ready')
        self.assertFalse(self.case['native_write_allowed'])
        self.assertGreater(self.case['unresolved_whole_machine_items'],0)

    def test_fixture_and_missing_sources_are_blocked(self):
        request,key=fixture()
        case=prepare_case(request)
        self.assertEqual(case['status'],'blocked')
        self.assertTrue(any('OEM' in reason for reason in case['blockers']))

    def test_more_than_one_edit_blocked(self):
        request=copy.deepcopy(self.request)
        doc=request['snapshot']['documents'][0]
        key=request['approvals'][0]['document_id']
        doc['dimensions'].append({'name':'Width@Sketch1','value':500,'unit':'mm'})
        request['pending_parameters'].append('width')
        request['approvals'].append({'parameter':'width','document_id':key,'dimension':'Width@Sketch1','reviewed':True,'source':'test'})
        request['rules'][key]['targets']['width']=600
        self.assertIn('exactly one native dimension edit required',prepare_case(request)['blockers'])

    def test_blank_evidence_never_passes(self):
        result=audit_case(self.case,evidence_template(self.case),self.root)
        self.assertEqual(result['status'],'review_required')
        self.assertEqual(result['counts']['not_run'],len(STEPS))

    def test_consistent_records_still_not_engineering_release(self):
        result=audit_case(self.case,self.records(),self.root)
        self.assertEqual(result['status'],'evidence_consistent')
        self.assertFalse(result['production_release'])
        self.assertEqual(result['mechanical_acceptance'],'unverified')

    def test_simulated_duplicate_or_nan_readback_rejected(self):
        for variant in ('simulation','duplicate','nan','wrong_config','wrong_value'):
            with self.subTest(variant=variant):
                evidence=self.records()
                if variant=='simulation': evidence['simulated_only']=True
                if variant=='duplicate': evidence['checks'].append(copy.deepcopy(evidence['checks'][0]))
                row=evidence['checks'][2]
                if variant=='nan': row['value_mm']=float('nan')
                if variant=='wrong_config': row['configuration']='wrong'
                if variant=='wrong_value': row['value_mm']=900
                self.assertEqual(audit_case(self.case,evidence,self.root)['status'],'review_required')

    def test_tampered_plan_sources_and_artifacts_rejected(self):
        evidence=self.records()
        changed=copy.deepcopy(self.case)
        changed['expected']['after_mm']=2000
        self.assertIn('case identity mismatch',audit_case(changed,evidence,self.root)['issues'])
        (self.root/'frame.SLDPRT').write_bytes(b'changed original')
        self.assertTrue(any('original changed' in x for x in audit_case(self.case,evidence,self.root)['issues']))
        (self.root/'fixture-evidence.txt').write_bytes(b'changed evidence')
        self.assertTrue(any('evidence file' in x for x in audit_case(self.case,evidence,self.root)['issues']))

    def test_artifact_escape_rejected(self):
        evidence=self.records()
        evidence['checks'][0]['artifacts'][0]['path']='../outside.txt'
        self.assertTrue(any('outside evidence' in x for x in audit_case(self.case,evidence,self.root)['issues']))

    def test_dimension_readback_requires_finite_and_current_value(self):
        self.assertEqual(verify_dimension_value(1,1000,'mm'),1)
        self.assertAlmostEqual(verify_dimension_value(math.pi,180,'deg'),math.pi)
        for actual in (float('nan'),float('inf'),True,0.9):
            with self.subTest(actual=actual),self.assertRaises((ValueError,RuntimeError)):
                verify_dimension_value(actual,1000,'mm')

    def test_native_stale_snapshot_stops_before_dimension_write(self):
        driver=NativeMachineDriver(None,self.root)
        driver.guard=lambda:None
        def pack(source,destination,configuration):
            driver.receipt['events'].append({'copies':{str((self.root/'frame.SLDPRT').resolve()):str(self.root/'copy.SLDPRT')}})
            return self.root/'copy.SLDASM'
        driver.pack_and_go=pack
        writes=[]
        dimension=SimpleNamespace(SystemValue=0.9,SetSystemValue3=lambda *args:writes.append(args))
        model=SimpleNamespace(ShowConfiguration2=lambda cfg:True,Parameter=lambda name:dimension)
        driver.open_document=lambda *args:model
        driver.activate=lambda model:None
        with self.assertRaises(RuntimeError):
            driver.apply_drive(self.case['drive_plan'],self.root/'new-output')
        self.assertEqual(writes,[])


if __name__=='__main__': unittest.main()
