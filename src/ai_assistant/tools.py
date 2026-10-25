"""Whitelisted pure queries/calculations. No file reader, shell or native writer."""
import json
from design_platform.calculations import compute
from engineering_intelligence.proposals import instruction_request
from project_workbench import capabilities

CALCULATIONS=('conveyor','ratio','motor','shaft','bearing','belt','chain','shaft_load','shaft_deflection','cylinder','guide')


def _function(name,description,properties):
    return {'type':'function','name':name,'description':description,'strict':True,
            'parameters':{'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}}


def tool_definitions():
    return [
        _function('get_project_capabilities','Return implemented project capabilities, not native acceptance.',{}),
        _function('calculate_mechanics','Preliminary calculation from user-provided values/units/sources. Never invent missing loads or ratings.',
                  {'kind':{'type':'string','enum':list(CALCULATIONS)},'inputs_json':{'type':'string','description':'JSON object; each input has value, unit, source'}}),
        _function('review_roller_instruction','Prepare a read-only review request from an explicit roller overall-length instruction; never executes CAD.',
                  {'text':{'type':'string'}})]


def call_readonly_tool(name,args):
    if not isinstance(args,dict):raise ValueError('tool arguments must be an object')
    if name=='get_project_capabilities' and not args:
        return {'status':'review_required','capabilities':capabilities(),'native_verified':False}
    if name=='calculate_mechanics' and set(args)=={'kind','inputs_json'}:
        if args['kind'] not in CALCULATIONS:raise ValueError('unsupported calculation')
        if not isinstance(args['inputs_json'],str) or len(args['inputs_json'])>12000:raise ValueError('bounded JSON inputs required')
        values=json.loads(args['inputs_json'])
        if not isinstance(values,dict):raise ValueError('calculation inputs must be an object')
        result=compute(args['kind'],values)
        return {'status':'review_required','calculation':result,'engineering_approved':False,
                'provenance':'model-requested calculation; inputs and applicability require human verification'}
    if name=='review_roller_instruction' and set(args)=={'text'}:
        if not isinstance(args['text'],str) or len(args['text'])>8000:raise ValueError('bounded instruction required')
        return instruction_request({'text':args['text']})
    raise ValueError('tool_not_allowed_or_invalid_arguments')
