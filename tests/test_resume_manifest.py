"""Synthetic artifacts exercise resume invalidation without starting CAD."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import tempfile
import unittest
from unittest.mock import patch
from resume_manifest import fingerprint, record_path, verified_output, write_record


class ResumeManifestTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.source = self.root / 'synthetic.input'
        self.source.write_bytes(b'input')
        self.code = self.root / 'generator.py'
        self.code.write_text('version = 1', encoding='utf-8')
        self.canonical = self.root / 'part.SLDPRT'
        self.canonical.write_bytes(b'synthetic, not real CAD')
        self.parameters = dict(thickness=2, radius=1)

    def key(self):
        return fingerprint(self.source, self.parameters, self.root)

    def test_matching_completed_artifact_can_resume(self):
        key = self.key()
        self.assertTrue(write_record(self.canonical, self.canonical, key, 'passed'))
        self.assertEqual(verified_output(self.canonical, key), self.canonical)
        self.assertFalse(json.loads(record_path(self.canonical).read_text())['engineering_accepted'])

    def test_nonempty_file_alone_is_not_evidence(self):
        self.assertIsNone(verified_output(self.canonical, self.key()))

    def test_output_corruption_prevents_resume(self):
        key = self.key()
        write_record(self.canonical, self.canonical, key, 'passed')
        self.canonical.write_bytes(b'corrupt')
        self.assertIsNone(verified_output(self.canonical, key))

    def test_source_parameter_and_code_changes_invalidate(self):
        key = self.key()
        write_record(self.canonical, self.canonical, key, 'passed')
        self.parameters['thickness'] = 3
        self.assertIsNone(verified_output(self.canonical, self.key()))
        self.parameters['thickness'] = 2
        self.source.write_bytes(b'new input')
        self.assertNotEqual(key, self.key())
        self.source.write_bytes(b'input')
        self.code.write_text('version = 2', encoding='utf-8')
        self.assertNotEqual(key, self.key())

    def test_degraded_output_cannot_resume_as_success(self):
        key = self.key()
        write_record(self.canonical, self.canonical, key, 'degraded')
        self.assertIsNone(verified_output(self.canonical, key))

    def test_malformed_and_traversal_records_are_refused(self):
        record_path(self.canonical).write_text('[]')
        self.assertIsNone(verified_output(self.canonical, self.key()))
        key = self.key()
        write_record(self.canonical, self.canonical, key, 'passed')
        row = json.loads(record_path(self.canonical).read_text())
        row['output_name'] = '../escape.SLDPRT'
        record_path(self.canonical).write_text(json.dumps(row))
        self.assertIsNone(verified_output(self.canonical, key))

    def test_missing_source_disables_resume(self):
        self.source.unlink()
        self.assertIsNone(self.key())
        self.assertFalse(write_record(self.canonical, self.canonical, None, 'passed'))

    def test_unique_output_path_is_preserved_without_overwrite(self):
        alternate = self.root / 'part_2.SLDPRT'
        alternate.write_bytes(b'new artifact')
        original = self.canonical.read_bytes()
        key = self.key()
        self.assertTrue(write_record(self.canonical, alternate, key, 'passed'))
        self.assertEqual(verified_output(self.canonical, key), alternate)
        self.assertEqual(self.canonical.read_bytes(), original)
        self.assertEqual(list(self.root.glob('.resume-*.tmp')), [])

    def test_batch_resumes_verified_artifact_and_rebuilds_changed_parameters(self):
        import batch_export as batch
        from cad_analyzer import DrawingAnalysis
        from solidworks_generator import GenerationResult
        analysis = DrawingAnalysis(self.source, 'mm', (), (), (), (0, 0, 1, 1), 'Model')
        job = batch.SheetPartJob(0, (), 1, 'synthetic')
        def generate(*args, **kwargs):
            output = Path(args[6])
            output.write_bytes(b'synthetic artifact, not CAD')
            return GenerationResult(output, 0, 0, 0, (0,)*6, (0,)*6)
        def export(radius=1):
            return batch._export_jobs(analysis, [(1, job)], self.root, 2, radius, 90,
                                      False, None, False, None, True)[0]
        with patch.object(batch, '_recycle_solidworks_if_heavy'), patch.object(batch, 'generate_sheet_metal_with_relief_retries', side_effect=generate) as create:
            first = export()
            self.assertFalse(first.skipped)
            second = export()
            self.assertTrue(second.skipped)
            self.assertTrue(second.resume_verified)
            self.assertEqual(second.status, 'passed')
            third = export(radius=3)
            self.assertFalse(third.skipped)
            self.assertNotEqual(first.path, third.path)
            self.assertEqual(create.call_count, 2)
