import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

from cad_checkpoint import create_checkpoint
from modeling_domain.dimension_edit import edit_reviewed_length


class Dimension:
    SystemValue = .504
    ReadOnly = False
    DrivenState = 2
    kind = 0
    status = 0
    def __init__(self):self.calls=[]
    def GetType(self):return self.kind
    def SetSystemValue3(self, value, mode, configurations):
        self.calls.append((value,mode,configurations))
        self.SystemValue=value
        return self.status


class ReviewedLengthEditTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);scope=root/'models';scope.mkdir()
        self.path=scope/'work.SLDPRT';self.path.write_bytes(b'isolated fixture')
        self.cp=create_checkpoint([self.path],root/'cp',scope=scope,snapshot={'features':[],'bodies':[]})
        self.dim=Dimension();self.guards=[]
        self.model=NS(Parameter=lambda name:self.dim,EditRebuild3=lambda:True,
            ConfigurationManager=NS(ActiveConfiguration=NS(Name='Default')))
        self.port=NS(path=self.path,host=NS(model=self.model),guard=lambda:self.guards.append(True))
        self.args=dict(configuration='Default',dimension_name='D1@Thin',before_mm=504,
            after_mm=514,allowed_range=(500,520),source='reviewed synthetic mapping')
    def run_edit(self):return edit_reviewed_length(self.port,self.cp,**self.args)
    def test_one_write_specific_configuration_and_readback(self):
        self.assertEqual(self.run_edit()['after_mm'],514)
        self.assertEqual(self.dim.calls,[(.514,3,['Default'])]);self.assertEqual(len(self.guards),2)
    def test_angles_readonly_and_driven_rejected_before_write(self):
        for name,value in [('kind',1),('ReadOnly',True),('DrivenState',1)]:
            with self.subTest(name=name):
                original=getattr(self.dim,name);setattr(self.dim,name,value)
                with self.assertRaises(ValueError):self.run_edit()
                self.assertEqual(self.dim.calls,[]);setattr(self.dim,name,original)
    def test_wrong_configuration_and_stale_value_rejected(self):
        self.args['configuration']='Other'
        with self.assertRaises(ValueError):self.run_edit()
        self.args['configuration']='Default';self.args['before_mm']=505
        with self.assertRaises(ValueError):self.run_edit()
        self.assertEqual(self.dim.calls,[])
    def test_tampered_checkpoint_or_target_rejected(self):
        self.path.write_bytes(b'changed')
        with self.assertRaises(ValueError):self.run_edit()
        self.assertEqual(self.dim.calls,[])
    def test_invalid_or_out_of_range_value_rejected(self):
        for value in (True,float('nan'),0,600):
            self.args['after_mm']=value
            with self.assertRaises(ValueError):self.run_edit()
        self.assertEqual(self.dim.calls,[])
    def test_failure_does_not_retry_native_write(self):
        self.dim.status=1
        with self.assertRaises(RuntimeError):self.run_edit()
        self.assertEqual(len(self.dim.calls),1)
