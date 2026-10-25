"""Regenerate synthetic engineering examples; no OEM data or CAD."""
import json
from pathlib import Path

def q(value,unit,source='synthetic engineering example'):
    return {'value':value,'unit':unit,'source':source}

def examples():
    dims=[]
    for name,value,role in [('left',50,'interface'),('right',60,'interface'),('barrel',500,'adjustable'),('diameter',20,'interface'),('shoulder',5,'interface'),('bearing',20,'interface')]:
        dims.append(dict(id=name,datum='roller_axis_origin',role=role,minimum_mm=1,**q(value,'mm')))
    dims.append(dict(id='overall',unit='mm',datum='roller_axis_origin',role='adjustable',source='explicit overall equation',
                     terms=[{'dimension':k,'direction':1} for k in ('left','barrel','right')],solve_for='barrel'))
    dimensions={'dimensions':dims,'targets':{'overall':q(800,'mm')}}
    tolerances={'datum':'bearing_fit_axis','dimensions':[dict(id='hole',datum='bearing_fit_axis',**q(20,'mm'),tolerance={'lower':.01,'upper':.03,'unit':'mm','source':'synthetic specified tolerance'}),
                  dict(id='shaft',datum='bearing_fit_axis',**q(20,'mm'),tolerance={'lower':-.02,'upper':-.01,'unit':'mm','source':'synthetic specified tolerance'})],
                  'terms':[{'dimension':'hole','direction':1},{'dimension':'shaft','direction':-1}], 'required_interval_mm':[.02,.05]}
    before=[{'id':'roller','kind':'part','source':'isolated/roller.sldprt','revision':'A','depends_on':[]},
            {'id':'machine','kind':'assembly','source':'isolated/machine.sldasm','revision':'A','depends_on':['roller']},
            {'id':'drawing','kind':'drawing','source':'isolated/machine.slddrw','revision':'A','depends_on':['machine']},
            {'id':'bom','kind':'bom','source':'bom.csv','revision':'A','depends_on':['machine']}]
    after=json.loads(json.dumps(before)); after[0]['revision']='B'
    changes={'before':before,'after':after}
    assembly={'components':[{'id':'frame','fixed':True},{'id':'roller','expected_dof':1}],
              'mates':[{'id':'concentric','a':'frame','b':'roller','type':'concentric','moving':'roller'},
                       {'id':'axial','a':'frame','b':'roller','type':'distance','moving':'roller'}],
              'joints':[{'id':'lift','component':'roller','minimum':0,'maximum':100,'position':20,'unit':'mm','source':'synthetic travel'}]}
    review={'scope':'roller_example','minimum_confidence':.9,'values':{'barrel':q(690,'mm'),'minimum':q(200,'mm')},
            'rules':[{'id':'barrel_min','left':'barrel','right':'minimum','op':'ge','unit':'mm','source':'synthetic design requirement',
                      'scope':'roller_example','confidence':1,'reviewed':True,'suggestion':'review barrel target'}]}
    transmission={'inputs':{k:q(v,u) for k,v,u in [('diameter',80,'mm'),('speed',.2,'m/s'),('force',100,'N'),('ratio',10,'ratio'),('efficiency',.8,'ratio'),('safety',1.5,'ratio')]}}
    weldments={'kerf':q(3,'mm'),'profiles':[{'id':'tube','source':'user synthetic profile table','revision':'A','material':'steel',
               'area':q(300,'mm^2'),'density':q(7850,'kg/m^3'),'stock_length':q(6000,'mm')}],
               'members':[{'id':'rail1','profile':'tube','start_mm':[0,0,0],'end_mm':[1000,0,0],'quantity':2,'end_allowance':q(1,'mm'),'cut_type':'square','source':'synthetic frame'},
                          {'id':'rail2','profile':'tube','start_mm':[0,0,0],'end_mm':[0,500,0],'quantity':2,'end_allowance':q(1,'mm'),'cut_type':'square','source':'synthetic frame'}],
               'connections':[{'id':'joint1','members':['rail1','rail2'],'weld_spec':'pending welding engineer review','source':'synthetic connection'}]}
    costs={'currency':'CNY','as_of':'2026-10-25','exclusions':['tax','shipping'],
           'items':[{'id':'steel','kind':'material','quantity':q(10,'kg'),'quantity_unit':'kg','loss':q(.1,'ratio'),
                     'quote':{'value':5,'currency':'CNY','per_unit':'kg','source':'synthetic quote, not vendor pricing','date':'2026-10-25'}}]}
    part={'unit':'mm','source':'synthetic snapshot','dimensions':{'length':100,'diameter':20},'material':'steel','features':['extrude'],'interfaces':['bearing20']}
    similarity={'dimension_tolerance_mm':.01,'parts':[dict(part,id='a'),dict(part,id='b')]}
    proposals={'metrics':[{'id':k,'unit':u,'weight':1,'preference':p,'source':'synthetic design comparison'} for k,u,p in [('load','kg','max'),('speed','m/s','max'),('cost','CNY','min'),('space','mm','min'),('maintenance','h/year','min')]],
               'alternatives':[{'id':kind,'kind':kind,'metrics':{k:q(v,u) for k,v,u in [('load',100,'kg'),('speed',speed,'m/s'),('cost',cost,'CNY'),('space',2000,'mm'),('maintenance',h,'h/year')]}}
                               for kind,speed,cost,h in [('gravity',.1,1000,2),('chain',.3,3000,10),('belt',.4,3500,5)]]}
    report=dict(changes,evidence=[],parameter_differences=[{'parameter':'overall','before':610,'after':800,'unit':'mm'}],validation_status='review_required')
    return locals()

if __name__=='__main__':
    values=examples(); root=Path(__file__).parent
    names=['dimensions','assembly','changes','tolerances','review','transmission','weldments','costs','similarity','change_report','proposals','instruction']
    values['change_report']=values['report'];values['instruction']={'text':'把这个滚筒总长度改成800 mm，轴径不变，两端安装结构不变。'}
    modules={k:values[k] for k in names}
    for key,value in modules.items(): (root/('issue50-'+key+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (root/'issue50-batch.json').write_text(json.dumps({'modules':modules},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
