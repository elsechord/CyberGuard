"""Bounded real model communication probe. Run only after arming a test budget."""
import argparse
import json
from pathlib import Path
import subprocess
import uuid


REMOTE = r'''
import importlib.util,json,os,pathlib,signal,sys,time
from qwenpaw_worker.api import QwenPawApiClient
from qwenpaw.agents.tools import agent_management as am
p=json.load(sys.stdin); c=QwenPawApiClient('http://127.0.0.1:8088',timeout=30)
parent=c._request('GET','/api/agents/default'); w=pathlib.Path(parent['workspace_dir'])
os.environ['QWENPAW_WORKING_DIR']=str(w.parent.parent)
os.environ['QWENPAW_DEFAULT_WORKSPACE_DIR']=str(w)
s=importlib.util.spec_from_file_location('cg','/opt/cyberguard-collaboration/native_collaboration.py')
h=importlib.util.module_from_spec(s);s.loader.exec_module(h)
n=h.load_native(h.DEFAULT_MODULE)
run=p['run_id']; d=w/'shared'/'cyberguard-communication-validation'/run;d.mkdir(parents=True)
material={'material_id':'MAT-synthetic','content':'Synthetic: 10:00 login denied. 10:05 account disabled. No successful login is recorded.'}
plan={'job_id':'COMMUNICATION-PROBE','task_id':run,'parent_worker':p['worker'],'run_id':run,
 'room_id':p['room_id'],'reason':'Bounded synthetic native communication integration test',
 'materials':[material], 'nodes':[{'id':x,'subagent':template,'role':x,
 'question':'Use only the synthetic login record; exchange a specific evidence question.',
 'material_ids':['MAT-synthetic']} for x,template in (('reader-a','source-reader'),('reader-b','hypothesis-checker'))]}
(d/'plan.json').write_text(json.dumps(plan),encoding='utf-8')
flow=h.Collaboration(n,plan,d,max_agents=2,max_iters=6)
events=[]; result={'scope':'synthetic_communication_probe','run_id':run,'events':events,'checks':{},'errors':[]}
def timeout(*args):raise TimeoutError('Five-minute communication probe deadline exceeded')
signal.signal(signal.SIGALRM,timeout);signal.alarm(300)
def call(target,text,label):
    session,payload,_=am.build_agent_chat_request(target,text,session_id=run+'-'+label,from_agent='default')
    def receive(line):
        event=am.parse_agent_sse_line(line)
        if event:events.append({'label':label,'target':target,'session':session,'event':event})
    am.stream_agent_chat(None,payload,target,timeout=240,line_handler=receive)
def objects(value):
    if isinstance(value,dict):
        yield value
        for v in value.values():yield from objects(v)
    elif isinstance(value,list):
        for v in value:yield from objects(v)
try:
    started=flow.start(); ids={row['id']:row['agentId'] for row in started['nodes']}
    a,b=ids['reader-a'],ids['reader-b'];result['agents']=ids
    for attempt in range(30):
        states={x['id']:x.get('startup_status') for x in c._request('GET','/api/agents')['agents']}
        if states.get(a)=='running' and states.get(b)=='running':break
        time.sleep(1)
    call(a, 'This is a bounded synthetic communication test. Do not create agents, use shell, browse, or start TeamHarness tasks. '
      'You must make exactly two real chat_with_agent tool calls, sequentially. First call to_agent='+b+
      ' with text: "Synthetic fixture: 10:00 login denied; 10:05 account disabled; no successful login recorded. '
      'What is the elapsed time? Answer in one sentence, no tools needed." Second call to_agent=default with text: '
      '"Bounded synthetic fixture check only; do not use tools, create tasks, delegate or change files. '
      'Evidence: 10:00 login denied; 10:05 account disabled; no successful login recorded. '
      'Does it support a successful intrusion? Answer in one sentence." '
      'Use timeout=90 for both. After both actual replies, return a short Chinese conclusion and identify remaining uncertainty. '
      'Do not claim a tool call occurred unless it actually returned.', 'child-a')
    calls=[];tool_results=[]
    for entry in events:
        if entry['label']!='child-a':continue
        for obj in objects(entry['event']):
            kind=obj.get('type','')
            if kind in ('tool_use','function_call','tool_call'):
                name=obj.get('name') or (obj.get('function') or {}).get('name')
                args=obj.get('input',obj.get('arguments',(obj.get('function') or {}).get('arguments',{})))
                if isinstance(args,str):
                    try:args=json.loads(args)
                    except ValueError:args={}
                if name=='chat_with_agent' and isinstance(args,dict):
                    calls.append({'name':name,'to_agent':args.get('to_agent'),'call_id':obj.get('id',obj.get('call_id'))})
            if kind in ('tool_result','function_call_output','tool_response'):
                tool_results.append(obj)
    result['observed_calls']=calls;result['observed_tool_results']=tool_results
    # Calls and replies must be checked from native structured traces, not final prose.
    result['checks']['child_to_peer_call']=any(x['to_agent']==b for x in calls)
    result['checks']['child_to_parent_call']=any(x['to_agent']=='default' for x in calls)
    result['checks']['replies_observed']='requires_trace_review' if tool_results else 'unknown'
    before={x['id'] for x in c._request('GET','/api/agents')['agents']}
    call('default','Synthetic direct-answer test only. Material: "login denied". Does this say the login succeeded? '
         'Answer in one sentence without tools or delegation. This is not a TeamHarness project.', 'simple-parent')
    after={x['id'] for x in c._request('GET','/api/agents')['agents']}
    result['checks']['simple_case_created_no_persistent_agent']=before==after
except Exception as exc:
    result['errors'].append(type(exc).__name__+': '+str(exc))
finally:
    signal.alarm(0)
    if flow.state_path.is_file():
        try:
            flow.advance('fail',{'summary':'Synthetic communication probe stopped; no investigation completion asserted.'})
            result['snapshot']=flow.export()
        except Exception as exc:result['errors'].append('cleanup: '+str(exc))
    result['remaining_test_agents']=[x['id'] for x in c._request('GET','/api/agents')['agents'] if run in x['id']]
    (d/'native-communication-evidence.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
'''


def analyze(evidence):
    """Join native completed plugin-call and plugin-output records by call ID."""
    calls, outputs = {}, {}
    simple_calls = []
    for entry in evidence.get('events', []):
        event = entry.get('event', {})
        if event.get('status') != 'completed':
            continue
        kind = event.get('type')
        if kind not in ('plugin_call', 'plugin_call_output'):
            continue
        for content in event.get('content', []):
            data = content.get('data') or {}
            call_id = data.get('call_id')
            if not call_id:
                continue
            if entry.get('label') == 'simple-parent' and kind == 'plugin_call':
                simple_calls.append(data.get('name'))
            if entry.get('label') != 'child-a' or data.get('name') != 'chat_with_agent':
                continue
            if kind == 'plugin_call':
                args = data.get('arguments', {})
                if isinstance(args, str):
                    try: args = json.loads(args)
                    except ValueError: continue
                calls[call_id] = dict(call_id=call_id, to_agent=args.get('to_agent'),
                                     question=args.get('text'), event_id=event.get('id'))
            elif data.get('state') == 'success' and data.get('output'):
                outputs[call_id] = dict(answer=data['output'], output_event_id=event.get('id'))
    messages = [{**call, **outputs[call_id], 'from': evidence.get('agents', {}).get('reader-a'),
                 'provenance': 'native_sse_tool_call_and_successful_output'}
                for call_id, call in calls.items() if call_id in outputs]
    peer = evidence.get('agents', {}).get('reader-b')
    evidence['observed_calls'] = list(calls.values())
    evidence['communication_evidence'] = messages
    evidence['checks'].update(
        child_to_peer_call=any(x.get('to_agent') == peer for x in calls.values()),
        child_to_parent_call=any(x.get('to_agent') == 'default' for x in calls.values()),
        child_peer_roundtrip=any(x['to_agent'] == peer for x in messages),
        child_parent_roundtrip=any(x['to_agent'] == 'default' for x in messages),
        replies_observed=bool(messages), simple_case_tool_calls=simple_calls)
    return evidence


def save(evidence, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    summary = {key:evidence.get(key) for key in
               ('scope','run_id','agents','checks','communication_evidence','errors','remaining_test_agents')}
    summary['cleanup'] = evidence.get('snapshot',{}).get('cleanup')
    path.with_name('native-communication-summary.json').write_text(
        json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def main():
    root=Path(__file__).resolve().parents[2]
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker',default='cg-native001-investigator')
    parser.add_argument('--room-id')
    parser.add_argument('--output',type=Path,default=root.parent/'output/adaptive-collaboration')
    parser.add_argument('--analyze-only',action='store_true',help='Recheck saved native SSE without model calls')
    args=parser.parse_args()
    path=args.output/'native-communication.json'
    if args.analyze_only:
        evidence=analyze(json.loads(path.read_text(encoding='utf-8')))
        save(evidence,path)
        print(json.dumps(evidence['checks']))
        return
    room=args.room_id
    if not room:
        data=json.loads(subprocess.check_output(['docker','exec','agentteams-controller','agt','get','teams','-o','json'],text=True))
        room=next(x for x in data['teams'] if x['name']=='cg-native001')['teamRoomID']
    result=subprocess.run(['docker','exec','-i','agentteams-worker-'+args.worker,
                           '/opt/venv/qwenpaw/bin/python','-c',REMOTE],
                          input=json.dumps({'worker':args.worker,'room_id':room,'run_id':'cg-comm-'+uuid.uuid4().hex[:10]}),
                          text=True,capture_output=True)
    if result.returncode:raise SystemExit('Communication probe process failed: '+result.stderr[-2000:])
    evidence=analyze(json.loads(result.stdout))
    args.output.mkdir(parents=True,exist_ok=True)
    save(evidence,path)
    print(json.dumps({'evidence':str(path),'checks':evidence['checks'],'errors':evidence['errors'],
                      'remaining_test_agents':evidence['remaining_test_agents']},ensure_ascii=False))


if __name__=='__main__':main()
