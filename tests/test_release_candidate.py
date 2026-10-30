"""Actual isolated Git/source ZIP checks; no Windows packaging or CAD."""
from pathlib import Path
import os,stat
import json,subprocess,sys,tempfile,unittest,zipfile
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from release_candidate import build_candidate,verify_candidate


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.repo=self.root/'repo';self.repo.mkdir()
        self.git('init','-q');self.git('config','user.name','Fixture');self.git('config','user.email','fixture@example.invalid')
        for name,content in {'app.py':'pass\n','geometry_ir/__init__.py':'','src/mod.py':'pass\n','customer.dwg':'private fixture','.env':'secret fixture'}.items():
            p=self.repo/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(content)
        self.git('add','.');self.git('commit','-qm','fixture')
    def git(self,*args):return subprocess.check_output(['git','-C',str(self.repo),*args]).decode().strip()
    def test_pin_and_source_integrity_and_package_dependency_roots(self):
        result=build_candidate(self.repo,self.root/'candidate',expected_revision=self.git('rev-parse','HEAD'))
        self.assertFalse(result['runtime_bundled']);self.assertEqual(result['native_acceptance'],'not_run')
        with zipfile.ZipFile(self.root/'candidate/source.zip') as z:
            self.assertIn('geometry_ir/__init__.py',z.namelist());self.assertNotIn('.env',z.namelist());self.assertNotIn('customer.dwg',z.namelist())
        self.assertEqual(verify_candidate(self.root/'candidate')['status'],'passed')
    def test_dirty_or_wrong_pin_does_not_create_output(self):
        with self.assertRaises(ValueError):build_candidate(self.repo,self.root/'wrong',expected_revision='a'*40)
        (self.repo/'app.py').write_text('changed')
        with self.assertRaises(ValueError):build_candidate(self.repo,self.root/'dirty')
        self.assertFalse((self.root/'dirty').exists())
    def test_existing_or_in_repository_destination_rejected(self):
        with self.assertRaises(ValueError):build_candidate(self.repo,self.repo/'output')
        self.assertFalse((self.repo/'output').exists())
        (self.root/'exists').mkdir()
        with self.assertRaises(FileExistsError):build_candidate(self.repo,self.root/'exists')
    def test_archive_and_matrix_changes_are_detected(self):
        build_candidate(self.repo,self.root/'candidate');(self.root/'candidate/source.zip').write_bytes(b'changed')
        result=verify_candidate(self.root/'candidate');self.assertEqual(result['status'],'failed')
        self.assertIn('source_archive_changed',result['issues'])
    def test_pinned_git_snapshot_without_local_repository(self):
        import hashlib,shutil
        files={}
        for name in self.git('ls-files').splitlines():
            b=(self.repo/name).read_bytes();files[name]=hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
        revision=self.git('rev-parse','HEAD')
        def make_writable_and_retry(function,path,error):
            os.chmod(path,stat.S_IWRITE | stat.S_IREAD)
            function(path)
        shutil.rmtree(self.repo/'.git',onerror=make_writable_and_retry)
        result=build_candidate(self.repo,self.root/'snapshot',source_index={'schema_version':1,'source_revision':revision,'files':files})
        self.assertEqual(result['source_revision'],revision)
        self.assertEqual(verify_candidate(self.root/'snapshot')['status'],'passed')
    def test_changed_source_cannot_use_pinned_snapshot(self):
        import hashlib
        b=(self.repo/'app.py').read_bytes()
        index={'schema_version':1,'source_revision':'a'*40,'files':{'app.py':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}}
        (self.repo/'app.py').write_text('changed')
        with self.assertRaisesRegex(ValueError,'pinned Git blob'):build_candidate(self.repo,self.root/'changed',source_index=index)
    def test_duplicate_json_keys_are_rejected(self):
        from project_delivery import read_json
        path=self.root/'duplicate.json';path.write_text('{"key":1,"key":2}')
        with self.assertRaises(ValueError):read_json(path)


if __name__=='__main__':unittest.main()
