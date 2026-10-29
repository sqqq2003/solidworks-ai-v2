"""Recovery and immutable-input contracts with synthetic DXFs only."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import ezdxf
from PIL import Image
from pypdf import PdfWriter
from five_sheet_preview import NAMES,STATE,file_hash,generate,PreviewRunFailed,_lock


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.manifest=self.root/'five-sheet-preview.json'
        doc=ezdxf.new();e=doc.modelspace().add_lwpolyline([(0,0),(100,0),(100,50),(0,50)],close=True)
        self.source=self.root/'synthetic.dxf';doc.saveas(self.source)
        rows=[{'name':name,'source':self.source.name,'source_sha256':file_hash(self.source),
               'groups':{'views':[e.dxf.handle]},'cells':{'views':[10,30,580,380]},
               'page_mm':[594,420]} for name in NAMES]
        self.plan={'schema_version':1,'machine_name':'synthetic only','sheets':rows}
        self.write_plan();self.output=self.root/'output'
    def write_plan(self):self.manifest.write_text(json.dumps(self.plan),encoding='utf-8')
    @staticmethod
    def export(item,folder):
        row=item['row'];base=folder/row['name'];item['doc'].saveas(base.with_suffix('.dxf'))
        pdf=PdfWriter();pdf.add_blank_page(width=row['page_mm'][0]*72/25.4,height=row['page_mm'][1]*72/25.4)
        with base.with_suffix('.pdf').open('wb') as stream:pdf.write(stream)
        Image.new('RGB',(10,10),'white').save(base.with_suffix('.png'))
    def test_failure_resumes_without_rewriting_completed_outputs(self):
        seen=[]
        def interrupted(item,folder):
            seen.append(item['row']['name'])
            if len(seen)==3:raise RuntimeError('synthetic interruption')
            self.export(item,folder)
        before=self.source.read_bytes()
        with self.assertRaises(PreviewRunFailed):generate(self.manifest,self.output,exporter=interrupted)
        self.assertEqual(json.loads((self.output/STATE).read_text())['status'],'failed')
        first=self.output/NAMES[0]/(NAMES[0]+'.pdf');timestamp=first.stat().st_mtime_ns
        resumed=[]
        def exporting(item,folder):resumed.append(item['row']['name']);self.export(item,folder)
        result=generate(self.manifest,self.output,resume=True,exporter=exporting)
        self.assertEqual(resumed,list(NAMES[2:]))
        self.assertEqual(first.stat().st_mtime_ns,timestamp)
        self.assertEqual(result['status'],'completed_preview')
        self.assertFalse(result['production_approved']);self.assertEqual(before,self.source.read_bytes())
        self.assertEqual(len(result['pdf_text_reviews']),5)
        self.assertTrue(all(r['status']=='blocked' for r in result['pdf_text_reviews'].values()))
    def test_modified_completed_output_is_not_overwritten_on_resume(self):
        generate(self.manifest,self.output,exporter=self.export)
        image=self.output/NAMES[0]/(NAMES[0]+'.png')
        Image.new('RGB',(11,11),'black').save(image);changed=image.read_bytes()
        with self.assertRaisesRegex(PreviewRunFailed,'修改'):
            generate(self.manifest,self.output,resume=True,exporter=self.export)
        self.assertEqual(image.read_bytes(),changed)
    def test_source_hash_change_rejected_before_output_creation(self):
        self.source.write_text('changed',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'源图'):
            generate(self.manifest,self.output,exporter=self.export)
        self.assertFalse(self.output.exists())
    def test_incomplete_group_rejected_before_any_sheet_export(self):
        self.plan['sheets'][-1]['groups']={'views':['DEAD']};self.write_plan();seen=[]
        with self.assertRaises(PreviewRunFailed):
            generate(self.manifest,self.output,exporter=lambda *args:seen.append(args))
        self.assertEqual(seen,[])
    def test_changed_manifest_cannot_resume_existing_job(self):
        generate(self.manifest,self.output,exporter=self.export)
        self.plan['machine_name']='modified';self.write_plan()
        with self.assertRaisesRegex(ValueError,'清单'):
            generate(self.manifest,self.output,resume=True,exporter=self.export)

    def test_published_receipts_recover_after_state_checkpoint_loss(self):
        generate(self.manifest,self.output,exporter=self.export)
        path=self.output/STATE;state=json.loads(path.read_text())
        state.update(status='failed',sheets={})
        path.write_text(json.dumps(state),encoding='utf-8')
        def refuse_export(*_):raise AssertionError('published files should be adopted')
        result=generate(self.manifest,self.output,resume=True,exporter=refuse_export)
        self.assertTrue(all(row['reused'] for row in result['sheets'].values()))

    def test_an_active_output_lock_rejects_another_writer(self):
        self.output.mkdir()
        with _lock(self.output):
            with self.assertRaisesRegex(ValueError,'正在执行'):
                generate(self.manifest,self.output,resume=True,exporter=self.export)


if __name__=='__main__':unittest.main()
