"""Numeric DAG, source-bound review and materialized-feature contracts."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cad_checkpoint import digest_file
from drawing_review import atomic_json
from parametric_workspace import preview_parameters, _digest
from parametric_functions import solve_functions
from parametric_functions.generate import materialize_part_plan
from parametric_functions.workflow import (inspect_digest, build_edit_plan, prepare_edit_workspace,
    approve_edit_workspace, inspect_edit_workspace, verify_edit_workspace)
from project_delivery import read_json

ROOT=Path(__file__).resolve().parents[1]


def preview():return preview_parameters(80,30,10,spec_path=ROOT/'examples/function-block.json')


def fixture(root, *, simulated=True):
    source=root/'Original.SLDPRT';source.write_bytes(b'original synthetic part; never native evidence')
    data=preview()
    inventory={'features':[{'name':'Sketch1','native_type':'ProfileFeature'},{'name':'Boss1','native_type':'Extrude'}],
               'bodies':[{'name':'Body','faces':6,'volume_mm3':12000.,'bounds_mm':[0,0,0,40,30,10]}],
               'bounds_precision':'approximate'}
    inspection={'schema_version':1,'scope':'native_dimension_snapshot','source_document':str(source),
       'source_sha256':digest_file(source),'configuration':'Default','inventory':inventory,
       'dimensions':[{'name':'D1@Sketch1','feature':'Sketch1','value_mm':40.,'unit':'mm','editable':True},
                     {'name':'D2@Sketch1','feature':'Sketch1','value_mm':30.,'unit':'mm','editable':True}],
       'simulated_only':simulated,'read_only':True,'manufacturing_approved':False}
    inspection['inspection_sha256']=inspect_digest(inspection)
    mappings={'schema_version':1,'parameters':[
        {'parameter':name,'document':str(source),'configuration':'Default','feature':'Sketch1',
         'dimension':dimension,'unit':'mm','depends_on':[],'source':'reviewed test mapping; not OEM',
         'allowed_range':bounds,'component_kind':kind,'status':'confirmed'}
        for name,dimension,bounds,kind in [('length','D1@Sketch1',[1,1000],'editable'),('width','D2@Sketch1',[30,30],'fixed')]]}
    return data,mappings,inspection


class FormulaTests(unittest.TestCase):
    def test_roller_dependencies_hole_integer_and_preserved_interfaces(self):
        result=solve_functions(read_json(ROOT/'examples/function-roller.json'))
        self.assertEqual(result['values_mm']['barrel_length'],745)
        self.assertEqual(result['values_mm']['hole_count'],9)
        self.assertAlmostEqual(result['values_mm']['actual_margin'],44.4)
        self.assertTrue(result['parameter_register']['left_end']['preserve_interface'])
        self.assertFalse(result['cad_executed'])

    def test_units_convert_millimetres_metres_angles_and_areas(self):
        spec={'kind':'parametric_functions','schema_version':1,'source':'explicit test rules',
              'inputs':{'length':{'unit':'m','value':.8},'shaft':{'unit':'mm','value':20},'angle':{'unit':'deg','value':30}},
              'parameters':{'body':{'expression':'length - 2*shaft','unit':'mm'},
                 'sine':{'expression':'sin(angle)','unit':'ratio'},
                 'root':{'expression':'sqrt(shaft * shaft)','unit':'mm'},
                 'area':{'expression':'shaft ** 2 * pi','unit':'mm2'}}}
        result=solve_functions(spec)['values_mm']
        self.assertEqual(result['body'],760);self.assertAlmostEqual(result['sine'],.5)
        self.assertEqual(result['root'],20);self.assertAlmostEqual(result['area'],1256.6370614359173)
        spec['parameters']['body']['unit']='deg'
        with self.assertRaisesRegex(ValueError,'units'):solve_functions(spec)

    def test_cycle_unknown_dependency_incompatible_addition_and_noninteger_count_refused(self):
        base={'kind':'parametric_functions','schema_version':1,'source':'test','inputs':{'x':{'unit':'mm','value':10}},
              'parameters':{'a':{'unit':'mm','expression':'x * 2'}}}
        for change in ('cycle','unknown','units','count','range','dependencies'):
            p=deepcopy(base)
            if change=='cycle':p['parameters'].update(a={'unit':'mm','expression':'b'},b={'unit':'mm','expression':'a'})
            elif change=='unknown':p['parameters']['a']['expression']='missing'
            elif change=='units':p['parameters']['a']['expression']='x + 1'
            elif change=='count':p['parameters']['a'].update(unit='count',expression='x / x / 2')
            elif change=='range':p['inputs']['x']['range']=[20,30]
            else:p['parameters']['a']['depends_on']=[]
            with self.subTest(change=change),self.assertRaises((ValueError,ArithmeticError)):solve_functions(p)

    def test_code_and_unbounded_operations_are_not_executable(self):
        base={'kind':'parametric_functions','schema_version':1,'source':'test','inputs':{'x':{'unit':'ratio','value':1}},'parameters':{}}
        for expression in ["__import__('os').system('echo unsafe')",'x.real','x[0]','lambda: 1',
                           '[i for i in range(3)]','(x := 2)','2 ** 1000','True','sum(x)',
                           'round(x, digits=2)','x if x else 1','+' .join(['x']*100)]:
            p=deepcopy(base);p['parameters']['y']={'expression':expression,'unit':'ratio'}
            with self.subTest(expression=expression),self.assertRaises((ValueError,TypeError)):solve_functions(p)

    def test_unknowns_stay_unknown_and_constraint_failure_blocks(self):
        spec=read_json(ROOT/'examples/function-roller.json');spec['inputs']['left_end'].pop('value')
        result=solve_functions(spec)
        self.assertIsNone(result['values_mm']['barrel_length']);self.assertTrue(result['unresolved'])
        spec['inputs']['left_end']['value']=199;spec['inputs']['length']['value']=100
        spec['parameters']['barrel_length'].pop('range')
        self.assertEqual(solve_functions(spec)['status'],'blocked')

    def test_materialization_changes_real_sketch_depth_and_body_gates(self):
        result=materialize_part_plan(preview())
        boss=result['plan']['features'][1]
        self.assertEqual(boss['parameters']['depth_mm'],10)
        self.assertEqual(boss['expected']['bounds_mm'],[0,0,0,80,30,10])
        self.assertEqual(boss['expected']['min_volume_mm3'],23997.6)
        self.assertEqual(result['draft']['status'],'draft_ready')
        self.assertFalse(result['native_executed'])

    def test_rehashed_manual_preview_changes_cannot_bypass_rule_recalculation(self):
        data=preview();data['plan']['values_mm']['length']=999
        data['review_sha256']=_digest({k:v for k,v in data.items() if k!='review_sha256'})
        with self.assertRaisesRegex(ValueError,'source rules'):materialize_part_plan(data)

    def test_volume_cannot_be_substituted_into_a_length_field(self):
        with tempfile.TemporaryDirectory() as folder:
            spec=read_json(ROOT/'examples/function-block.json')
            spec['feature_template']['features'][1]['parameters']['depth_mm']='${volume}'
            path=Path(folder)/'spec.json';atomic_json(path,spec,exclusive=True)
            with self.assertRaisesRegex(ValueError,'unit differs'):
                materialize_part_plan(preview_parameters(40,30,10,spec_path=path))


class ReviewWorkflowTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.preview,self.mappings,self.inspection=fixture(self.root)

    def test_change_protected_scope_immutable_review_and_binding(self):
        status=prepare_edit_workspace(self.preview,self.mappings,self.inspection,self.root/'review')
        self.assertEqual(status['phase'],'ready_for_review')
        self.assertEqual([(r['before'],r['after']) for r in status['changes']],[(40,80)])
        self.assertEqual(status['protected'][0]['parameter'],'width')
        self.assertIn('volume',status['computed_only'])
        approved=approve_edit_workspace(self.root/'review',reviewer='Engineer',expected_review_sha256=status['review_sha256'])
        self.assertEqual(approved['phase'],'review_recorded')
        self.assertFalse(approved['native_write_allowed'])
        with self.assertRaises(FileExistsError):approve_edit_workspace(self.root/'review',reviewer='Other',expected_review_sha256=status['review_sha256'])
        with self.assertRaises(FileExistsError):prepare_edit_workspace(self.preview,self.mappings,self.inspection,self.root/'review')

    def test_protected_target_change_blocks_named_approval(self):
        p=preview_parameters(80,35,10,spec_path=ROOT/'examples/function-block.json')
        self.mappings['parameters'][1]['allowed_range']=[1,100]
        status=prepare_edit_workspace(p,self.mappings,self.inspection,self.root/'review')
        self.assertEqual(status['phase'],'blocked')
        with self.assertRaises(ValueError):approve_edit_workspace(self.root/'review',reviewer='Engineer',expected_review_sha256=status['review_sha256'])

    def test_wrong_physical_owner_duplicate_or_unconfirmed_mapping_is_refused(self):
        for mode in ('wrong_feature','duplicate','unconfirmed','configuration','range'):
            mapping=deepcopy(self.mappings)
            if mode=='wrong_feature':mapping['parameters'][0]['feature']='Boss1'
            elif mode=='duplicate':mapping['parameters'][1]['dimension']='D1@Sketch1'
            elif mode=='unconfirmed':mapping['parameters'][0]['status']='pending_mapping'
            elif mode=='configuration':mapping['parameters'][0]['configuration']='Other'
            else:mapping['parameters'][0]['allowed_range']=[1,50]
            with self.subTest(mode=mode),self.assertRaises(ValueError):build_edit_plan(self.preview,mapping,self.inspection)

    def test_source_mapping_implementation_or_approval_changes_invalidate_execution(self):
        status=prepare_edit_workspace(self.preview,self.mappings,self.inspection,self.root/'review')
        with patch('parametric_functions.workflow.code_hashes',return_value={}):
            with self.assertRaisesRegex(ValueError,'implementation'):verify_edit_workspace(self.root/'review')
        path=self.root/'review/mappings.json';path.write_text('{}')
        with self.assertRaisesRegex(ValueError,'artifact changed'):verify_edit_workspace(self.root/'review')
        Path(self.inspection['source_document']).write_bytes(b'manual saved edit')
        with self.assertRaisesRegex(ValueError,'source model changed'):build_edit_plan(self.preview,self.mappings,self.inspection)

    def test_meter_mapping_normalizes_before_after_and_allowed_range_once(self):
        self.mappings['parameters'][0].update(unit='m',allowed_range=[.001,1.])
        edit,impact=build_edit_plan(self.preview,self.mappings,self.inspection)
        self.assertEqual(edit['changes'][0]['after_mm'],80)
        self.assertEqual(edit['changes'][0]['allowed_range'],[1,1000])
        self.assertTrue(impact['review_ready'])


class CliContractTests(unittest.TestCase):
    def test_cli_materializes_actual_files_and_native_generation_refuses_linux(self):
        from contextlib import redirect_stdout
        import io
        from work.parametric import main
        with tempfile.TemporaryDirectory() as folder,redirect_stdout(io.StringIO()):
            root=Path(folder);preview_path=root/'preview.json';feature_path=root/'features.json'
            self.assertEqual(main(['preview',str(ROOT/'examples/function-block.json'),'--length','80','--width','30','--height','10','--out',str(preview_path)]),0)
            self.assertEqual(main(['materialize',str(preview_path),'--out',str(feature_path)]),0)
            features=read_json(feature_path);self.assertEqual(features['plan']['features'][1]['expected']['bounds_mm'],[0,0,0,80,30,10])
            template=root/'empty.prtdot';template.write_bytes(b'synthetic template')
            with patch('modeling_domain.api.sys.platform','linux'):
                code=main(['generate',str(preview_path),'--sw-exe','SLDWORKS.exe','--template',str(template),
                           '--template-sha256',digest_file(template),'--reviewer','Engineer',
                           '--reviewed-plan-sha256',features['plan_sha256'],'--request-key','new-model',
                           '--out',str(root/'native')])
            self.assertEqual(code,1);self.assertFalse((root/'native').exists())

    def test_saved_batch_fault_tool_requires_windows_without_touching_output(self):
        from contextlib import redirect_stdout
        import io
        from work.verify_parameter_edit_rollback import main
        with tempfile.TemporaryDirectory() as folder,redirect_stdout(io.StringIO()),patch('work.verify_parameter_edit_rollback.sys.platform','linux'):
            root=Path(folder)
            self.assertEqual(main(['workspace','--sw-exe','SLDWORKS.exe','--out',str(root/'native'),
                '--approval-sha256','0'*64,'--request-key','fault','--enable-fault-injection']),1)
            self.assertFalse((root/'native').exists())


if __name__=='__main__':unittest.main()
