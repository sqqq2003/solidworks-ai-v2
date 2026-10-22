"""Tests of input metadata gates only, not mechanical or CAD acceptance."""
import copy
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engineering_controls import production_parameter_issues, stable_reference_issues


class EngineeringControlTests(unittest.TestCase):
    def setUp(self):
        self.parameter = dict(value=100, unit='mm', confirmation_status='engineering_confirmed',
            production_approved=True, source=dict(locator='synthetic fixture', artifact_sha256='a'*64),
            confirmed_range=[50,150], confirmed_by='test fixture', confirmed_at='test-only')
        self.reference = dict(semantic_role='shaft-axis', component_instance_key='assembly/shaft-1',
            document_sha256='a'*64, configuration='test-config', reference_kind='solidworks_persistent_reference',
            persistent_reference_base64='dGVzdA==', resolved_and_checked=True,
            validation_evidence='synthetic test only; not a real CAD reference')

    def test_complete_synthetic_parameter_metadata(self):
        self.assertEqual(production_parameter_issues(self.parameter), [])

    def test_user_requested_target_is_not_engineering_approval(self):
        self.parameter.update(confirmation_status='user_requested', production_approved=False)
        self.assertIn('engineering_confirmation_required', production_parameter_issues(self.parameter))
        self.assertIn('production_approval_required', production_parameter_issues(self.parameter))

    def test_unmeasured_or_nonfinite_value_is_refused(self):
        for value in (None, float('nan'), float('inf'), True):
            self.parameter['value'] = value
            self.assertIn('missing_or_invalid_value', production_parameter_issues(self.parameter))

    def test_missing_range_and_out_of_range_are_refused(self):
        self.parameter['confirmed_range'] = None
        self.assertIn('confirmed_range_required', production_parameter_issues(self.parameter))
        self.parameter.update(confirmed_range=[1,2])
        self.assertIn('outside_confirmed_range', production_parameter_issues(self.parameter))

    def test_source_without_hash_is_not_traceable(self):
        self.parameter['source']['artifact_sha256'] = None
        self.assertIn('traceable_source_required', production_parameter_issues(self.parameter))

    def test_revision_or_configuration_change_invalidates_reference(self):
        errors = stable_reference_issues(self.reference, document_sha256='b'*64, configuration='new')
        self.assertIn('document_revision_mismatch', errors)
        self.assertIn('configuration_mismatch', errors)

    def test_face_name_and_coordinates_are_not_a_persistent_reference(self):
        self.reference.update(reference_kind='Face1', persistent_reference_base64=None)
        errors = stable_reference_issues(self.reference, document_sha256='a'*64, configuration='test-config')
        self.assertIn('persistent_reference_required', errors)
        self.assertIn('persistent_reference_bytes_required', errors)

    def test_encoded_token_without_resolution_evidence_is_refused(self):
        self.reference.update(resolved_and_checked=False, validation_evidence=None)
        self.assertIn('cad_resolution_evidence_required', stable_reference_issues(
            self.reference, document_sha256='a'*64, configuration='test-config'))


if __name__ == '__main__':
    unittest.main()
