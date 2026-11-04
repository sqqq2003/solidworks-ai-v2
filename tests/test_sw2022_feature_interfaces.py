"""Focused interface fakes; no COM or ownership bypass."""
import sys,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from ql5050px.editable_features import EditableFeaturesMixin

class Host(EditableFeaturesMixin):
    def guard(self):pass

class Interfaces(unittest.TestCase):
    def setUp(self):
        fake_com=patch.dict(sys.modules,{'pythoncom':SimpleNamespace(Nothing=object()),'win32com':SimpleNamespace(),'win32com.client':SimpleNamespace()})
        fake_com.start();self.addCleanup(fake_com.stop)
        self.feature=SimpleNamespace(Name='old',GetTypeName2=lambda:'ProfileFeature')
        self.part=SimpleNamespace(FeatureByName=lambda name:self.feature if name=='outline' else None)
        def as_interface(module,obj,kind):
            if kind=='IPartDoc':return self.part
            return obj
        self.sw=SimpleNamespace(ensure_solidworks_typelib=lambda:object(),_as_interface=as_interface)
        self.host=Host()
        self.manager=SimpleNamespace(InsertSketch=lambda *_:None,ActiveSketch=object(),CreateLine=lambda *_:object())
        self.host.model=SimpleNamespace(ClearSelection2=lambda *_:None,
            Extension=SimpleNamespace(SelectByID2=lambda *_:True),SketchManager=self.manager,
            FeatureByPositionReverse=lambda _:self.feature)
    def test_sketch_without_GetFeature_uses_typed_latest_feature(self):
        self.feature.GetTypeName2='ProfileFeature'
        feature={'id':'outline','kind':'sketch','confirmed':True,'evidence':['fixture'],
            'parameters':{'plane':'fixture_plane','entities':[{'type':'line','start':[0,0],'end':[10,0]}]}}
        with patch.dict(sys.modules,{'solidworks_generator':self.sw}):self.host.create_editable_feature(feature)
        self.assertEqual(self.feature.Name,'outline')
    def test_part_interface_not_model_interface_for_lookup(self):
        with patch.dict(sys.modules,{'solidworks_generator':self.sw}):r=self.host.verify_feature_tree(['outline'])
        self.assertEqual(r['features'][0]['native_type'],'ProfileFeature')
    def test_missing_feature_fails_closed(self):
        with patch.dict(sys.modules,{'solidworks_generator':self.sw}):
            with self.assertRaises(RuntimeError):self.host.verify_feature_tree(['missing'])
    def test_non_sketch_latest_feature_not_renamed(self):
        self.feature.GetTypeName2=lambda:'Extrusion'
        feature={'id':'bad','kind':'sketch','confirmed':True,'evidence':['fixture'],'parameters':{'plane':'fixture_plane','entities':[]}}
        with patch.dict(sys.modules,{'solidworks_generator':self.sw}):
            with self.assertRaises(RuntimeError):self.host.create_editable_feature(feature)
        self.assertEqual(self.feature.Name,'old')
if __name__=='__main__':unittest.main()

