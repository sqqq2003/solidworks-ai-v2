"""Capability claims cannot promote missing, stale, or foreign evidence."""
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from capability_registry import build_capability_report, file_sha256, load_records


class CapabilityRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'src').mkdir()
        for name in ('dxf_overview.py','desktop_ui.py'):
            (self.root/'src'/name).write_text(name,encoding='utf-8')
        self.source=self.root/'input.dxf';self.source.write_text('source',encoding='utf-8')
        self.store=self.root/'runtime/capability-evidence';self.store.mkdir(parents=True)
        self.evidence=self.store/'test-log.txt';self.evidence.write_text('a claim',encoding='utf-8')
        self.hashes={'src/'+n:file_sha256(self.root/'src'/n) for n in ('dxf_overview.py','desktop_ui.py')}
        self.record={'capability_id':'dxf_overview','stage':'solidworks','result':'passed',
            'tested_at':datetime.now(timezone.utc).isoformat(),'solidworks_version':'33.1.2.0',
            'source_sha256':file_sha256(self.source),'code_sha256':self.hashes,
            'evidence_file':'test-log.txt','evidence_sha256':file_sha256(self.evidence)}

    def report(self, records, version='33.1.2.0'):
        return build_capability_report(root=self.root,source_path=str(self.source),records=records,
            evidence_dir=self.store,version_info={'version':version,'path':None})

    def claim(self, report):
        return report['capabilities'][0]['evidence']['solidworks']

    def test_missing_evidence_never_means_verified(self):
        report=self.report([])
        self.assertTrue(all(row['evidence']['solidworks']['state']=='unverified' for row in report['capabilities']))
        self.assertFalse(report['production_approved']);self.assertFalse(report['cad_executed'])

    def test_matching_claim_stays_pending_independent_review(self):
        self.assertEqual(self.claim(self.report([self.record]))['state'],'linked_review_required')
        self.assertFalse(self.report([self.record])['production_approved'])

    def test_changed_code_input_version_and_evidence_each_invalidate(self):
        self.assertEqual(self.claim(self.report([self.record],version='34.0.0.0'))['state'],'unverified')
        self.source.write_text('changed',encoding='utf-8')
        self.assertEqual(self.claim(self.report([self.record]))['state'],'unverified')
        self.source.write_text('source',encoding='utf-8')
        (self.root/'src/dxf_overview.py').write_text('different',encoding='utf-8')
        self.assertEqual(self.claim(self.report([self.record]))['state'],'unverified')
        (self.root/'src/dxf_overview.py').write_text('dxf_overview.py',encoding='utf-8')
        self.evidence.write_text('tampered',encoding='utf-8')
        self.assertEqual(self.claim(self.report([self.record]))['state'],'unverified')

    def test_path_traversal_and_duplicate_claims_rejected(self):
        outside=self.root/'private.txt';outside.write_text('private',encoding='utf-8')
        bad={**self.record,'evidence_file':'../../private.txt','evidence_sha256':file_sha256(outside)}
        self.assertEqual(self.claim(self.report([bad]))['state'],'unverified')
        self.assertEqual(self.claim(self.report([self.record,self.record]))['state'],'unverified')

    def test_missing_index_or_malformed_index_is_visible(self):
        self.assertEqual(load_records(self.root),([],None))
        (self.store/'index.json').write_text(json.dumps({'schema_version':1,'records':'bad'}),encoding='utf-8')
        records,error=load_records(self.root)
        self.assertEqual(records,[]);self.assertIsNotNone(error)


if __name__ == '__main__':
    unittest.main()
