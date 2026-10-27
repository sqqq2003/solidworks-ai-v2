import tempfile
from pathlib import Path
import unittest
from app import job_from_form
from project_workbench import build_command,execute_job


class DesktopFormTests(unittest.TestCase):
    def values(self,source,**overrides):
        result=dict(kind='sheet',machine='QL-5050PX',ql_action='plan',source=str(source),output='',sw_exe='',
                    thickness='',radius='',angle='',k_factor='',profile='1',variant='0')
        result.update(overrides);return result

    def test_analyze_allows_blank_manufacturing_parameters(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'plate.dxf';source.write_bytes(b'synthetic')
            job=job_from_form(self.values(source),'analyze')
            self.assertIn('--analyze-only',build_command(job))
            self.assertNotIn('thickness',job)

    def test_sheet_plan_still_requires_explicit_manufacturing_parameters(self):
        with self.assertRaises(ValueError):job_from_form(self.values('plate.dxf'),'plan')

    def test_roller_and_turned_do_not_parse_unused_sheet_values(self):
        for mode in ('roller','turned'):
            job=job_from_form(self.values('part.dxf',kind=mode),'plan')
            self.assertEqual(job['variant'],0);self.assertNotIn('k_factor',job)

    def test_real_dxf_analysis_through_form_and_cli(self):
        import ezdxf
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'plate with spaces.dxf'
            doc=ezdxf.new();doc.modelspace().add_lwpolyline([(0,0),(100,0),(100,50),(0,50)],close=True);doc.saveas(path)
            result=execute_job(job_from_form(self.values(path),'analyze'))
            self.assertEqual(result['status'],'analyzed',result)
            self.assertFalse(result['cad_verified'])
