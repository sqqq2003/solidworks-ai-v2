"""Source kit verification and extraction: no installed app, shell, COM or API."""
import hashlib,json,stat,sys,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from release_candidate import build_candidate,bundle_manifest
from release_install import inspect_kit,install_kit,members

class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.source=self.root/'source';self.source.mkdir();(self.source/'app.py').write_text('raise RuntimeError("never execute installer payload")\n')
        (self.source/'README.md').write_text('fixture')
        files={}
        for p in self.source.iterdir():
            b=p.read_bytes();files[p.name]=hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
        self.candidate=self.root/'candidate'
        build_candidate(self.source,self.candidate,source_index={'schema_version':1,'source_revision':'a'*40,'files':files})
        self.kit=self.root/'kit.zip';self.pack()
    def pack(self,extra=None):
        with zipfile.ZipFile(self.kit,'w',zipfile.ZIP_DEFLATED) as archive:
            for p in self.candidate.iterdir():archive.write(p,p.name)
            if extra:archive.writestr(*extra)
        self.sha=hashlib.sha256(self.kit.read_bytes()).hexdigest()
    def test_verified_source_install_does_not_execute_code_or_change_old_installation(self):
        old=self.root/'old';old.mkdir();(old/'app.py').write_text('old source')
        with patch('subprocess.Popen') as run:
            result=install_kit(self.kit,self.root/'new',expected_sha256=self.sha)
        run.assert_not_called();self.assertFalse(result['code_executed']);self.assertFalse(result['runtime_bundled'])
        self.assertEqual((old/'app.py').read_text(),'old source')
        self.assertEqual((self.root/'new/app/app.py').read_bytes(),(self.source/'app.py').read_bytes())
        self.assertTrue((self.root/'new/installation.json').exists())
    def test_preview_without_external_checksum_is_not_trusted_installation(self):
        self.assertEqual(inspect_kit(self.kit)['status'],'review_required')
        self.assertFalse(inspect_kit(self.kit)['external_checksum_verified'])
        with self.assertRaises(ValueError):install_kit(self.kit,self.root/'new',expected_sha256='')
    def test_wrong_checksum_and_existing_destination_are_refused(self):
        with self.assertRaises(ValueError):install_kit(self.kit,self.root/'new',expected_sha256='0'*64)
        self.assertFalse((self.root/'new').exists());(self.root/'existing').mkdir()
        with self.assertRaises(FileExistsError):install_kit(self.kit,self.root/'existing',expected_sha256=self.sha)
    def test_zip_traversal_symlink_and_windows_reserved_paths_are_refused(self):
        special=zipfile.ZipInfo('link');special.external_attr=(stat.S_IFLNK|0o777)<<16
        for name in ('../escape','CON.txt','folder\\escape','folder/name. ',special):
            self.pack((name,'payload'))
            with self.assertRaises(ValueError):install_kit(self.kit,self.root/'new',expected_sha256=self.sha)
            self.assertFalse((self.root/'new').exists())
    def test_unlisted_inner_file_is_rejected_even_with_consistent_outer_hashes(self):
        source=self.candidate/'source.zip'
        with zipfile.ZipFile(source,'a') as archive:archive.writestr('src/unlisted.py','must not run')
        candidate=json.loads((self.candidate/'candidate.json').read_text());candidate['package_sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
        candidate.pop('candidate_id');candidate['candidate_id']=hashlib.sha256(bundle_manifest(candidate)).hexdigest()
        (self.candidate/'candidate.json').write_text(json.dumps(candidate));self.pack()
        with self.assertRaisesRegex(ValueError,'unlisted'):inspect_kit(self.kit,expected_sha256=self.sha)
    def test_pinned_source_index_mismatch_is_rejected(self):
        index=json.loads((self.candidate/'source-index.json').read_text());index['files']['app.py']='0'*40
        (self.candidate/'source-index.json').write_text(json.dumps(index));self.pack()
        with self.assertRaisesRegex(ValueError,'Git blob'):inspect_kit(self.kit,expected_sha256=self.sha)
    def test_case_collisions_and_file_directory_conflicts_are_refused(self):
        for paths in (('app.py','APP.py'),('src','src/file.py')):
            path=self.root/'bad.zip'
            with zipfile.ZipFile(path,'w') as z:
                for name in paths:z.writestr(name,'fixture')
            with zipfile.ZipFile(path) as z:
                with self.assertRaises(ValueError):members(z)
    def test_broken_archive_is_a_clear_value_error(self):
        self.kit.write_bytes(b'not zip')
        with self.assertRaisesRegex(ValueError,'invalid'):inspect_kit(self.kit)

if __name__=='__main__':unittest.main()
