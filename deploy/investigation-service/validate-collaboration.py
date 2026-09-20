"""Exercise native temporary-agent lifecycle only; never submit model work."""
import argparse
import json
from pathlib import Path
import subprocess
import uuid


REMOTE = r'''
import importlib.util, inspect, json, os, pathlib, sys, time
from qwenpaw_worker.api import QwenPawApiClient
p=json.load(sys.stdin)
c=QwenPawApiClient('http://127.0.0.1:8088', timeout=30)
parent=c._request('GET','/api/agents/default')
workspace=pathlib.Path(parent['workspace_dir'])
os.environ['QWENPAW_WORKING_DIR']=str(workspace.parent.parent)
os.environ['QWENPAW_DEFAULT_WORKSPACE_DIR']=str(workspace)
spec=importlib.util.spec_from_file_location('cg_helper','/opt/cyberguard-collaboration/native_collaboration.py')
helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
native=helper.load_native(helper.DEFAULT_MODULE)
results=[]
for count in (1,2):
    run_id=p['prefix']+'-'+str(count)
    task_dir=workspace/'shared'/'cyberguard-lifecycle-validation'/run_id
    task_dir.mkdir(parents=True,exist_ok=False)
    plan={'job_id':'LIFECYCLE-ONLY','task_id':run_id,'parent_worker':p['worker'],
          'run_id':run_id,'reason':'Lifecycle integration test; no inference task is submitted',
          'room_id':p['room_id'],'materials':[{'material_id':'MAT-test','content':'Synthetic lifecycle fixture.'}],
          'nodes':[{'id':'node-'+str(i),'subagent':'source-reader','role':'Lifecycle fixture',
                    'question':'Do not run: lifecycle-only test.','material_ids':['MAT-test']}
                   for i in range(count)]}
    (task_dir/'plan.json').write_text(json.dumps(plan),encoding='utf-8')
    flow=helper.Collaboration(native,plan,task_dir,max_agents=3,max_iters=7)
    started=None
    try:
        started=flow.start()
        children=[]
        for node in started['nodes']:
            child=c._request('GET','/api/agents/'+node['agentId'])
            row={'id':child['id'],'active_model':child['active_model'],
                 'max_iters':child['running']['max_iters'],
                 'auto_title_enabled':child['running']['auto_title_config']['enabled']}
            assert row['active_model']==parent['active_model']
            assert row['max_iters']==7 and row['auto_title_enabled'] is False
            children.append(row)
        assert len(children)==count
        for attempt in range(30):
            inventory=c._request('GET','/api/agents')['agents']
            states={item['id']:item.get('startup_status') for item in inventory}
            if all(states.get(child['id']) != 'starting' for child in children):
                break
            time.sleep(1)
        assert all(states.get(child['id']) != 'starting' for child in children), 'Agent startup did not settle'
    finally:
        if flow.state_path.is_file():
            flow.advance('fail',{'summary':'Lifecycle test canceled before inference; this is not a completed investigation.'})
    snapshot=flow.export()
    for child in children:
        try:
            c._request('GET','/api/agents/'+child['id'])
        except Exception as exc:
            assert '404' in str(exc), str(exc)
            child['removed']=True
        else:
            raise AssertionError('Temporary agent remains: '+child['id'])
    assert flow.state_path.is_file()
    results.append({'count':count,'run_id':run_id,'native_event_id':started.get('eventId'),
                    'children':children,'state_path':str(flow.state_path),'shared_retained':True,
                    'snapshot':snapshot,'model_calls':0,'scope':'lifecycle_only'})
from qwenpaw.agents.tools import agent_management as communication
schemas={name:{'signature':str(inspect.signature(getattr(communication,name))),
               'doc':inspect.getdoc(getattr(communication,name))}
         for name in ('chat_with_agent','submit_to_agent','check_agent_task')}
print(json.dumps({'worker':p['worker'],'runs':results,'communication_tools':schemas,
                  'model_calls':0,'scope':'lifecycle_only'},ensure_ascii=False))
'''


def main():
    root=Path(__file__).resolve().parents[2]
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker',default='cg-native001-investigator')
    parser.add_argument('--room-id')
    parser.add_argument('--output',type=Path,default=root.parent/'output/adaptive-collaboration')
    args=parser.parse_args()
    room=args.room_id
    if not room:
        data=json.loads(subprocess.check_output(['docker','exec','agentteams-controller','agt','get','teams','-o','json'],text=True))
        team=next(item for item in data['teams'] if item['name']=='cg-native001')
        room=team['teamRoomID']
    prefix='cg-lifecycle-'+uuid.uuid4().hex[:10]
    result=subprocess.run(['docker','exec','-i','agentteams-worker-'+args.worker,
                           '/opt/venv/qwenpaw/bin/python','-c',REMOTE],
                          input=json.dumps({'worker':args.worker,'room_id':room,'prefix':prefix}),
                          text=True,capture_output=True)
    if result.returncode:
        raise SystemExit('Lifecycle test failed: '+result.stderr[-3000:])
    evidence=json.loads(result.stdout)
    args.output.mkdir(parents=True,exist_ok=True)
    path=args.output/'native-lifecycle.json'
    path.write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'evidence':str(path),'counts':[r['count'] for r in evidence['runs']],
                      'all_removed':all(c['removed'] for r in evidence['runs'] for c in r['children']),
                      'shared_retained':all(r['shared_retained'] for r in evidence['runs']),
                      'scope':'lifecycle_only','model_calls':0}))


if __name__=='__main__':main()
