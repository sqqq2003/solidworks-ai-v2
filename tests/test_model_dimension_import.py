import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
from ql5050px.model_dimensions import (dimension_value,display_dimension_value,dimension_values_match,
    validate_required_parameters,insert_model_dimensions,collect_model_dimensions,dimension_coverage,dimension_import_verified)


def dimension(value=.514,name='D1@Extrude@tube.Part',kind=0):
    return NS(FullName=name,SystemValue=value,GetType=lambda:kind)


def display(value=.514,name='D1@Extrude@tube.Part',override=False,doc_units=True):
    obj=NS(GetDimension2=lambda index:dimension(value,name),GetOverride=lambda:override,
        GetUseDocUnits=lambda:doc_units,GetNext5=None)
    ann=NS(GetName=lambda:'dimension1',GetType=lambda:4,GetPosition=lambda:[.1,.2,0],GetSpecificAnnotation=lambda:obj,Visible=1)
    obj.GetAnnotation=lambda:ann
    return obj


class ModelDimensionImportTests(unittest.TestCase):
    def source(self):return {'expected':[dimension_value(dimension())],'missing_source_parameters':[]}
    def imported(self,**kwargs):return [{'model_dimension':display_dimension_value(display(**kwargs))}]
    def test_real_dimension_coverage_and_units(self):
        report=dimension_coverage(self.source(),self.imported())
        self.assertEqual(report['status'],'verified');self.assertFalse(report['manufacturing_approved'])
        self.assertEqual(report['source_parameters'][0]['value_si'],.514)
    def test_overrides_and_unconfirmed_local_units_do_not_pass(self):
        for args in ({'override':True},{'doc_units':False},{'value':.504},{'name':'D1@Extrude@other.Part'}):
            with self.subTest(args=args):self.assertEqual(dimension_coverage(self.source(),self.imported(**args))['status'],'pending_dimensions')
    def test_missing_required_dimensions_are_explicit(self):
        report=dimension_coverage(self.source(),[])
        self.assertEqual(report['missing_parameters'],['D1@Extrude']);self.assertEqual(report['status'],'pending_dimensions')
    def test_bad_parameter_lists_rejected(self):
        for names in (None,[],['length'],['D1@E','D1@E'],['D1@E@other.Part']):
            with self.subTest(names=names),self.assertRaises(ValueError):validate_required_parameters(names)
    def test_nonfinite_or_unknown_dimension_type_rejected(self):
        for dim in (dimension(float('nan')),dimension(kind=2)):
            with self.assertRaises(RuntimeError):dimension_value(dim)
    def test_single_native_import_no_numeric_override(self):
        drawing=NS(ClearSelection2=Mock(),Extension=object(),InsertModelAnnotations3=Mock(),EditRebuild3=lambda:True)
        source=NS(Parameter=lambda name:dimension());views={'front':NS(GetName2='Front')}
        with patch('ql5050px.com_selection.select_by_id',return_value=True):
            result=insert_model_dimensions(NS(guard=lambda:None),drawing,source,views,['D1@Extrude'])
        self.assertTrue(result['attempted']);drawing.InsertModelAnnotations3.assert_called_once_with(0,557056,True,False,False,False)
    def test_missing_source_parameter_does_not_attempt_native_insert(self):
        drawing=NS(InsertModelAnnotations3=Mock())
        result=insert_model_dimensions(NS(guard=lambda:None),drawing,NS(Parameter=lambda name:None),{},['D1@Extrude'])
        self.assertFalse(result['attempted']);drawing.InsertModelAnnotations3.assert_not_called()
    def test_collects_native_dimensions_and_annotation_positions(self):
        rows=collect_model_dimensions({'front':NS(GetFirstDisplayDimension5=display())})
        self.assertEqual(rows[0]['kind'],'model_dimension');self.assertEqual(rows[0]['position_mm'],[100,200,0])
        self.assertEqual(rows[0]['model_dimension']['value_si'],.514)
    def test_cycle_is_refused(self):
        dim=display();dim.GetNext5=dim
        with self.assertRaisesRegex(RuntimeError,'cyclic'):collect_model_dimensions({'front':NS(GetFirstDisplayDimension5=dim)})
    def test_reopen_detects_numeric_override_or_changed_model_value(self):
        before=display_dimension_value(display())
        self.assertTrue(dimension_values_match(display_dimension_value(display()),before))
        self.assertFalse(dimension_values_match(display_dimension_value(display(override=True)),before))
        self.assertFalse(dimension_values_match(display_dimension_value(display(value=.504)),before))
    def test_stored_verified_flag_without_reopened_annotations_is_insufficient(self):
        self.assertFalse(dimension_import_verified({'model_dimension_import':{'status':'verified','reopened_verified':True}}))
        rows=collect_model_dimensions({'front':NS(GetFirstDisplayDimension5=display())})
        proof=dimension_coverage(self.source(),rows);proof['reopened_verified']=True
        data={'model_dimension_import':proof,'annotations':rows}
        self.assertFalse(dimension_import_verified(data))
        rows[0]['reopened']=True
        self.assertTrue(dimension_import_verified(data))
        rows[0]['model_dimension']['value_si']=.504
        self.assertFalse(dimension_import_verified(data))
