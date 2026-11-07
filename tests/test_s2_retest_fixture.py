"""Fixture preparation and identity only; never launches SW."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'work'))
from prepare_s2_retest import prepare


class S2RetestFixtureTests(unittest.TestCase):
    def test_explicit_fixture_identity_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'review'
            kwargs=dict(thickness=2.5,radius=1,angle=90,k_factor=.4,sw_exe='C:/fake/SLDWORKS.exe')
            result=prepare(folder,**kwargs)
            self.assertFalse(result['cad_executed'])
            self.assertEqual(result['index_base'],0)
            self.assertEqual(len(result['source_sha256']),64)
            self.assertIn('--no-relief-retries',result['command_argv'])
            self.assertEqual(len(result['loaded_code_sha256']),6)
            self.assertTrue((folder/'retest-plan.json').is_file())
            with self.assertRaises(FileExistsError):prepare(folder,**kwargs)

    def test_invalid_parameters_create_no_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'never'
            with self.assertRaises(ValueError):
                prepare(folder,thickness=0,radius=1,angle=90,k_factor=.4,sw_exe='fake')
            self.assertFalse(folder.exists())
