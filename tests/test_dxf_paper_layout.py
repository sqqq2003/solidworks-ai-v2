import sys
from pathlib import Path
import unittest
import ezdxf
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from dxf_paper_layout import add_partitioned_layout


class PaperLayoutTests(unittest.TestCase):
    def test_a2_page_uses_declared_size(self):
        doc=ezdxf.new();circle=doc.modelspace().add_circle((0,0),5)
        paper,report=add_partitioned_layout(doc,{'view':[circle]},
            {'view':(10,10,580,400)},name='A2',page_size=(594,420))
        self.assertEqual(report['page_mm'],[594,420])
        self.assertEqual(paper.dxf.paper_width,594)
        self.assertEqual(paper.dxf.paper_height,420)

    def test_viewports_preserve_model_geometry_and_isolate_other_groups(self):
        doc=ezdxf.new();msp=doc.modelspace()
        a=msp.add_lwpolyline([(0,0),(100,0),(100,50),(0,50)],close=True)
        b=msp.add_circle((200,200),20)
        line=msp.add_line((-100,-100),(500,500))
        original_points=list(a.get_points());original_center=b.dxf.center
        paper,report=add_partitioned_layout(doc,{'a':[a],'b':[b],'hidden':[line]},
            {'a':(10,100,200,280),'b':(210,100,410,280)})
        self.assertEqual(list(a.get_points()),original_points)
        self.assertEqual(b.dxf.center,original_center)
        viewports=list(paper.query('VIEWPORT'))
        viewports=[v for v in viewports if v.dxf.id>1]
        self.assertEqual(len(viewports),2)
        self.assertIn(b.dxf.layer,viewports[0].frozen_layers)
        self.assertIn(line.dxf.layer,viewports[0].frozen_layers)
        self.assertNotIn(a.dxf.layer,viewports[0].frozen_layers)
        self.assertFalse(report['model_geometry_transformed'])

    def test_overlap_is_rejected_before_layers_or_entities_change(self):
        doc=ezdxf.new();a=doc.modelspace().add_circle((0,0),5)
        b=doc.modelspace().add_circle((20,0),5);count=len(doc.layers)
        with self.assertRaisesRegex(ValueError,'overlap'):
            add_partitioned_layout(doc,{'a':[a],'b':[b]},
                {'a':(0,0,100,100),'b':(50,50,150,150)})
        self.assertEqual(a.dxf.layer,'0');self.assertEqual(len(doc.layers),count)

    def test_missing_or_duplicate_model_entities_are_rejected(self):
        doc=ezdxf.new();a=doc.modelspace().add_circle((0,0),5)
        b=doc.modelspace().add_circle((20,0),5)
        for groups in [{'a':[a]},{'a':[a,b],'b':[b]}]:
            with self.assertRaisesRegex(ValueError,'exactly one'):
                add_partitioned_layout(doc,groups,{'a':(0,0,100,100)})

    def test_foreign_document_entity_cannot_replace_matching_handle(self):
        doc=ezdxf.new();a=doc.modelspace().add_circle((0,0),5)
        other=ezdxf.new();foreign=other.modelspace().add_circle((0,0),10)
        self.assertEqual(a.dxf.handle,foreign.dxf.handle)
        with self.assertRaisesRegex(ValueError,'another document'):
            add_partitioned_layout(doc,{'a':[foreign]},{'a':(0,0,100,100)})
        self.assertEqual(foreign.dxf.layer,'0')


if __name__=='__main__':unittest.main()
