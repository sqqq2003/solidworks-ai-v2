import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from work.relocate_model_package import relocate


class PortableModelGuardTests(unittest.TestCase):
    def test_changed_model_cannot_reach_native_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);(folder/'part.sldprt').write_bytes(b'changed')
            (folder/'portable-models.json').write_text(json.dumps({'files':[{'path':'part.sldprt','sha256':hashlib.sha256(b'original').hexdigest()}],'dependencies':[]}))
            with patch('sw_session.run_on_task_sta') as native,self.assertRaises(ValueError):relocate(folder,'SLDWORKS.exe')
            native.assert_not_called()

    def test_manifest_cannot_write_outside_model_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'models';folder.mkdir();outside=Path(tmp)/'outside.sldprt';outside.write_bytes(b'original')
            (folder/'portable-models.json').write_text(json.dumps({'files':[{'path':'../outside.sldprt','sha256':hashlib.sha256(b'original').hexdigest()}],'dependencies':[]}))
            with patch('sw_session.run_on_task_sta') as native,self.assertRaises(ValueError):relocate(folder,'SLDWORKS.exe')
            native.assert_not_called();self.assertEqual(outside.read_bytes(),b'original')

    def test_dependency_keys_checked_before_native_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);(folder/'part.sldprt').write_bytes(b'original')
            (folder/'portable-models.json').write_text(json.dumps({'files':[{'path':'part.sldprt','sha256':hashlib.sha256(b'original').hexdigest()}],'dependencies':[{'owner':'missing.sldasm','target':'part.sldprt','old_path':'old'}]}))
            with patch('sw_session.run_on_task_sta') as native,self.assertRaises(ValueError):relocate(folder,'SLDWORKS.exe')
            native.assert_not_called()
