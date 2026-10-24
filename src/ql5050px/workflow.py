"""Machine-specific orchestration shared by the existing desktop and project CLI."""
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol
import json

from .parameters import build_plan
from .assembly import inspect_assembly
from .drawing_bom import build_bom, drawing_model, export_bom_csv, export_drawing_json

ACTIONS = {'plan','assembly','bom','drawing','pipeline','auto_assembly','drive','manufacturing','machine_package','intelligence'}


@dataclass(frozen=True)
class AssemblyInterface:
    id: str
    component_a: str
    component_b: str
    kind: str
    parameter_names: tuple[str,...] = ()
    status: str = 'pending_mapping'
    source: str | None = None


class NativeMechanicalPort(Protocol):
    """Implemented by an owned Windows worker; results must include evidence."""
    def check_mates(self, document: str) -> dict: ...
    def check_motion(self, document: str, request: dict) -> dict: ...
    def check_interference(self, document: str) -> dict: ...


def machine_plan(config):
    if config.get('machine','QL-5050PX') != 'QL-5050PX':
        raise ValueError('QL workflow rejects other machine identities')
    if config.get('units','mm') != 'mm':
        raise ValueError('QL configuration must use mm')
    plan = build_plan(envelope=config.get('envelope'),measurements=config.get('measurements'))
    components = config.get('components',[])
    seen = set()
    for row in components:
        if row['id'] in seen:
            raise ValueError('duplicate QL component id')
        seen.add(row['id'])
        if row.get('component_kind','editable') not in {'editable','fixed','purchased'}:
            raise ValueError('invalid component_kind')
        if row.get('module') not in plan['modules']:
            raise ValueError('component must identify a QL module')
    interfaces = []
    for row in config.get('interfaces',[]):
        item = AssemblyInterface(**row)
        if item.component_a not in seen or item.component_b not in seen or item.component_a==item.component_b:
            raise ValueError('assembly interface references unknown/equal components')
        if any(name not in plan['values_mm'] for name in item.parameter_names):
            raise ValueError('assembly interface references unknown parameter')
        if item.status not in {'pending_mapping','confirmed'} or (item.status=='confirmed' and not item.source):
            raise ValueError('confirmed interface requires source')
        interfaces.append(asdict(item))
    # Value confirmation and physical SW target mapping are separate contracts.
    mappings = {name:{'parameter':name,'unit':metadata['unit'],
                      'value_status':metadata['status'],'status':'pending_mapping',
                      'document':None,'configuration':None,'feature':None,'dimension':None}
                for name,metadata in plan['parameter_register'].items()}
    plan.update(components=components,assembly_interfaces=interfaces,physical_mapping_register=mappings,
                status='pending_mapping',cad_executed=False,cad_release_approved=False)
    return plan


def assembly_report(config):
    plan = machine_plan(config)
    components = [dict(c,fixed=c.get('fixed',c.get('component_kind')=='fixed')) for c in plan['components']]
    report = inspect_assembly(components,config.get('mates',[]),config.get('transmissions',[]))
    if not components:
        report['issues'].append({'kind':'missing_assembly','detail':'no real or fixture components supplied'})
    report['missing_interfaces'] = [r['id'] for r in plan['assembly_interfaces'] if r['status']!='confirmed']
    report['source_kind'] = config.get('source_kind','unconfirmed_input')
    return report


def native_mechanical_checks(document, request, port: NativeMechanicalPort):
    """Port owns Windows/session/ref isolation checks; never called by offline UI."""
    import sys
    if sys.platform != 'win32':
        raise RuntimeError('native mechanical evidence requires Windows')
    results = {'mates':port.check_mates(document),
               'motion':port.check_motion(document,request),
               'interference':port.check_interference(document)}
    for name,result in results.items():
        if not result.get('evidence') or result.get('simulated_only') is not False:
            raise ValueError(f'{name}: native evidence and explicit simulated_only=false required')
    return results


def run_workflow(action, config, *, output_dir=None, resume=False):
    if action=='intelligence':
        from .intelligence import run_intelligence
        return run_intelligence(config,output_dir)
    if action not in ACTIONS:
        raise ValueError('unknown QL action')
    if action in {'auto_assembly','drive','manufacturing','machine_package'}:
        from .machine_package import plan_machine, write_machine_package
        if resume: raise ValueError('machine planning packages require a new output directory')
        if action=='machine_package':
            if output_dir is None: raise ValueError('machine_package requires output_dir')
            package = write_machine_package(config,output_dir)
            return {**package,'plan':package['plan']['parameters'],'machine_plan':package['plan'],
                    'machine':'QL-5050PX','action':action,'cad_executed':False,
                    'mechanical_acceptance':'unverified'}
        machine = plan_machine(config)
        key = {'auto_assembly':'assembly_plan','drive':'drive_plan','manufacturing':'drawing_plan'}[action]
        return {'schema_version':1,'machine':'QL-5050PX','action':action,'status':machine[key]['status'],
                'plan':machine['parameters'],'result':machine[key],'cad_executed':False,
                'mechanical_acceptance':'unverified','test_status':'not_run'}
    plan = machine_plan(config)
    result = {'schema_version':1,'machine':'QL-5050PX','action':action,'plan':plan,
              'status':'pending_mapping','cad_executed':False,'mechanical_acceptance':'unverified',
              'test_status':'not_run'}
    if action=='pipeline':
        if output_dir is None:
            raise ValueError('pipeline requires a new output directory or explicit resume')
        from .manufacturing import offline_runner
        jobs = config.get('jobs')
        if not isinstance(jobs,list) or not jobs:
            raise ValueError('pipeline requires jobs array')
        batch = offline_runner().run(jobs,output_dir,resume=resume)
        result['batch'] = batch
        result['status'] = 'failed' if batch['counts']['failed'] or batch['counts']['blocked'] else 'pending_mapping'
        return result
    if resume:
        raise ValueError('resume is supported only for pipeline')
    if action in {'assembly','bom','drawing'}:
        result['assembly'] = assembly_report(config)
    if action in {'bom','drawing'}:
        result['bom'] = build_bom(plan['components'])
    if action=='drawing':
        spec = config.get('drawing',{})
        result['drawing'] = drawing_model(spec.get('part_number','QL-5050PX-PENDING'),
            material=spec.get('material'),dimensions_mm=spec.get('dimensions_mm'),
            views=spec.get('views',[]),notes=spec.get('notes',[]),bom=result['bom'])
        result['native_exports'] = {kind:{'status':'pending_windows','cad_executed':False}
                                    for kind in ('SLDDRW','native_flat_DXF')}
    if output_dir is not None:
        folder = Path(output_dir).resolve()
        folder.mkdir(parents=True,exist_ok=False)
        if 'bom' in result:
            export_bom_csv(result['bom'],folder/'bom.csv')
        if 'drawing' in result:
            export_drawing_json(result['drawing'],folder/'drawing.json')
        if action=='drawing' and config.get('sheet'):
            from .drawing_layout import render_sheet_svg
            render_sheet_svg({**config['sheet'],'bom':result['bom']},folder/'sheet.svg')
        with (folder/'workflow.json').open('x',encoding='utf-8') as stream:
            json.dump(result,stream,ensure_ascii=False,indent=2,allow_nan=False)
        result['output_dir'] = str(folder)
    return result
