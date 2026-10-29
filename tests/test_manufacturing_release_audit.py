import importlib.util
from pathlib import Path
import tempfile
import unittest

# Load the candidate module while reusing the existing ql5050px dependencies.
spec = importlib.util.spec_from_file_location('candidate_manufacturing', Path(__file__).resolve().parents[1]/'src/design_platform/manufacturing.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class ManufacturingAuditTests(unittest.TestCase):
    def setUp(self):
        common = dict(part_number='P1', configuration='main', material='steel', revision='B')
        self.rows = [dict(common, kind='part', source='copy/P1.sldprt'),
                     dict(common, kind='drawing', source='copy/P1.slddrw', model_source='copy/P1.sldprt', model_revision='B'),
                     dict(common, kind='bom', source='bom.csv', quantity=3)]
        self.components = [dict(common, quantity=1), dict(common, quantity=2)]

    def audit(self):
        return m.consistency(self.rows, 'B', bom=m.build_bom(self.components))

    def reasons(self):
        return {i['reason'] for i in self.audit()['issues']}

    def test_coherent(self):
        self.assertEqual(self.audit()['status'], 'declared_data_consistent')
        self.assertFalse(self.audit()['manufacturing_approved'])
        self.assertFalse(self.audit()['native_references_verified'])

    def test_actual_bom_quantity(self):
        self.rows[-1]['quantity'] = 1
        self.assertIn('bom_quantity_mismatch', self.reasons())

    def test_boolean_quantity(self):
        self.rows[-1]['quantity'] = True
        self.assertIn('bom_quantity_mismatch', self.reasons())

    def test_old_model_reference(self):
        self.rows[1]['model_source'] = 'mother/P1.sldprt'
        self.rows[1]['model_revision'] = 'A'
        self.assertIn('drawing_model_reference_mismatch', self.reasons())
        self.assertIn('drawing_model_revision_mismatch', self.reasons())

    def test_configuration_not_silently_merged(self):
        self.rows[1]['configuration'] = 'other'
        self.assertIn('drawing_requires_unique_registered_model', self.reasons())

    def test_missing_register_and_declaration(self):
        self.rows = []
        self.assertIn('bom_item_missing_from_register', self.reasons())
        self.rows = [dict(part_number='P1',configuration='main',kind='part',source='copy',material='steel',revision='B')]
        self.assertIn('missing_or_ambiguous_bom_declaration', self.reasons())

    def test_generated_bom_material(self):
        self.components[0]['material'] = 'aluminium'
        self.assertIn('ambiguous_bom_identity', self.reasons())

    def test_no_implicit_sheet_values(self):
        self.rows[0]['kind'] = 'sheet'
        self.assertIn('missing_per_job_k_factor', self.reasons())

    def test_invalid_sheet_values(self):
        self.rows[0].update(kind='sheet',thickness_mm=-1,radius_mm=float('nan'),angle_degrees=180,k_factor=True,direction='normal')
        for field in ('thickness_mm','radius_mm','angle_degrees','k_factor'):
            self.assertIn('invalid_'+field,self.reasons())

    def test_export_uses_same_generator_register(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=m.export_manufacturing(iter(self.components),iter(self.rows),'B',Path(tmp)/'new')
            self.assertEqual(result['consistency']['status'],'declared_data_consistent')
            self.assertEqual(result['bom'][0]['quantity'],3)
