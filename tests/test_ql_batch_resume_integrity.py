"""Resume must bind in-memory dependency values to the hashed result artifact."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from ql5050px.batch import BatchRunner


class BatchResumeIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'jobs'
        self.calls=[]
        def handler(payload,folder):
            self.calls.append(payload)
            return {'length_mm':100}
        self.runner=BatchRunner({'measure':handler})
        self.jobs=[{'id':'measure','kind':'measure','payload':{}}]
        self.runner.run(self.jobs,self.root)

    def edit(self,change):
        journal=self.root/'journal.jsonl'
        row=json.loads(journal.read_text(encoding='utf-8'))
        change(row)
        journal.write_text(json.dumps(row)+'\n',encoding='utf-8')

    def test_journal_value_cannot_override_hashed_result(self):
        self.edit(lambda row:row['value'].update(length_mm=999))
        with self.assertRaisesRegex(ValueError,'result value'):
            self.runner.run(self.jobs,self.root,resume=True)
        self.assertEqual(len(self.calls),1)

    def test_completed_without_artifacts_is_not_reused(self):
        self.edit(lambda row:row.update(artifacts={}))
        with self.assertRaisesRegex(ValueError,'result artifact'):
            self.runner.run(self.jobs,self.root,resume=True)

    def test_result_from_different_job_is_not_reused(self):
        self.edit(lambda row:row.update(kind='different'))
        with self.assertRaisesRegex(ValueError,'job kind'):
            self.runner.run(self.jobs,self.root,resume=True)

    def test_unchanged_result_reused_without_rerun(self):
        result=self.runner.run(self.jobs,self.root,resume=True)
        self.assertEqual(result['counts']['completed'],1)
        self.assertEqual(result['jobs']['measure']['value']['length_mm'],100)
        self.assertEqual(len(self.calls),1)

    def test_dependent_handler_cannot_mutate_previous_result(self):
        def mutate(payload,folder):
            payload['source']['length_mm']=999
            return {'derived_mm':999}
        self.runner.handlers['mutate']=mutate
        jobs=self.jobs+[{'id':'derived','kind':'mutate','depends_on':['measure'],
                         'payload':{'source':{'$ref':'measure'}}}]
        result=self.runner.run(jobs,Path(self.tmp.name)/'independent')
        self.assertEqual(result['jobs']['measure']['value']['length_mm'],100)
        self.assertEqual(result['jobs']['derived']['value']['derived_mm'],999)
