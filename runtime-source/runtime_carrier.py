#!/usr/bin/env python3
import json, os, socket, sys, time, hashlib, uuid
from copy import deepcopy
from pathlib import Path

ROOT=Path('/mnt/data/execution_runtime')
MANIFEST=ROOT/'runtime_manifest.json'
STATE=ROOT/'runtime_state.json'
OVERLAY=ROOT/'kb_overlay.json'
EVENTS=ROOT/'runtime_events.jsonl'
PUBLISHED_BASE=ROOT/'published_base.json'
SOCKET=Path('/tmp/execution-runtime.sock')
DEFAULT_BASE_IDENTITY={
  'repository':'BestNameYet/Execution-Contract-Controller',
  'runtime_commit':'871c0c808aa9f5ae5b2889be398bcb7bac8df10d',
  'kb_blob_sha':'97734aec10329f5a6788001383d7c8be8aa8459b',
  'kb_sha256':'fc82218417d59560b916ef910d59907f62e8e2d4d91d2a78bf6e72bfa9297636',
  'kb_schema':'execution-knowledge-base-v1','kb_version':1
}
BASE_IDENTITY=dict(DEFAULT_BASE_IDENTITY)
if PUBLISHED_BASE.exists():
    BASE_IDENTITY.update(json.loads(PUBLISHED_BASE.read_text()))

def atomic(path,obj):
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,sort_keys=True,indent=2))
    os.replace(tmp,path)

def emit_event(kind,data):
    with EVENTS.open('a') as f:
        f.write(json.dumps({'time':time.time(),'kind':kind,'data':data},separators=(',',':'))+'\n')

generation=uuid.uuid4().hex[:12]
started=time.time()
state={'version':0,'data':{},'events':[],'event_sequence':0,'sheet_recorded_through':0,'started_at':started}
overlay={'version':0,'records':[],'published_through':0}
if STATE.exists():
    try: state=json.loads(STATE.read_text())
    except Exception: pass
if not isinstance(state,dict): state={'version':0,'data':{},'started_at':started}
state.setdefault('version',0)
state.setdefault('data',{})
state.setdefault('events',[])
state.setdefault('event_sequence',len(state['events']))
state.setdefault('sheet_recorded_through',0)
state.setdefault('started_at',started)
if OVERLAY.exists():
    try: overlay=json.loads(OVERLAY.read_text())
    except Exception: pass

def write_all():
    atomic(STATE,state); atomic(OVERLAY,overlay)
    manifest={
      'schema':'execution-runtime-manifest-v1','carrier_id':'execution-runtime','generation':generation,
      'pid':os.getpid(),'transport':'unix','endpoint':str(SOCKET),'started_at':started,
      'state_version':state['version'],'kb_overlay_version':overlay['version'],
      'pending_unpublished_records':len(overlay['records'])-overlay.get('published_through',0),
      'published_base':BASE_IDENTITY,
    }
    atomic(MANIFEST,manifest)
    return manifest

def validate_record(r):
    if not isinstance(r,dict): raise ValueError('record must be object')
    if not isinstance(r.get('id'),str) or not r['id']: raise ValueError('id required')
    if r.get('type') not in {'invariant','action','procedure','heuristic','pattern','capability'}: raise ValueError('invalid type')
    if not isinstance(r.get('summary'),str) or not r['summary']: raise ValueError('summary required')

def validate_event(e):
    if not isinstance(e,dict): raise ValueError('event must be object')
    if not isinstance(e.get('event_id'),str) or not e['event_id']: raise ValueError('event_id required')
    if not isinstance(e.get('turn_id'),str) or not e['turn_id']: raise ValueError('turn_id required')
    if not isinstance(e.get('timestamp_started'),str) or not e['timestamp_started']: raise ValueError('timestamp_started required')
    if not isinstance(e.get('timestamp_completed'),str) or not e['timestamp_completed']: raise ValueError('timestamp_completed required')
    if not isinstance(e.get('invocation'),dict): raise ValueError('invocation required')

def append_controller_event(e):
    validate_event(e)
    existing=next((x for x in state['events'] if x.get('event_id')==e['event_id']),None)
    if existing is not None:
        return existing,False
    node=deepcopy(e)
    state['event_sequence']=int(state.get('event_sequence',0))+1
    node['sequence']=state['event_sequence']
    node['parent_event_id']=state['events'][-1].get('event_id') if state['events'] else None
    same_turn=[x for x in reversed(state['events']) if x.get('turn_id')==node.get('turn_id')]
    node['turn_parent_event_id']=same_turn[0].get('event_id') if same_turn else None
    state['events'].append(node)
    state['version']+=1
    write_all()
    emit_event('CONTROLLER_EVENT_APPEND',{'event_id':node['event_id'],'sequence':node['sequence'],'turn_id':node['turn_id'],'version':state['version']})
    return node,True

if SOCKET.exists():
    try: SOCKET.unlink()
    except FileNotFoundError: pass
srv=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
srv.bind(str(SOCKET)); os.chmod(SOCKET,0o600); srv.listen(16)
write_all(); emit_event('START',{'generation':generation,'pid':os.getpid()})

def respond(conn,obj):
    conn.sendall((json.dumps(obj,separators=(',',':'))+'\n').encode())

running=True
while running:
    conn,_=srv.accept()
    try:
        buf=b''
        while b'\n' not in buf:
            chunk=conn.recv(65536)
            if not chunk: break
            buf+=chunk
        req=json.loads(buf.split(b'\n',1)[0] or b'{}')
        op=req.get('op')
        if op=='PING':
            respond(conn,{'ok':True,'manifest':write_all()})
        elif op=='CONTEXT':
            respond(conn,{'ok':True,'manifest':write_all(),'state':state,'pending_records':overlay['records'][overlay.get('published_through',0):]})
        elif op=='STATE_SET':
            key=req['key']; state['data'][key]=req.get('value'); state['version']+=1; write_all(); emit_event('STATE_SET',{'key':key,'version':state['version']}); respond(conn,{'ok':True,'state_version':state['version']})
        elif op=='STATE_GET':
            respond(conn,{'ok':True,'value':state['data'].get(req['key']),'state_version':state['version']})
        elif op=='EVENT_APPEND':
            node,created=append_controller_event(req['event'])
            respond(conn,{'ok':True,'created':created,'event_id':node['event_id'],'sequence':node['sequence'],'parent_event_id':node.get('parent_event_id'),'state_version':state['version']})
        elif op=='EVENTS_GET':
            after=int(req.get('after_sequence',0))
            if after<0: raise ValueError('after_sequence must be nonnegative')
            respond(conn,{'ok':True,'event_sequence':state['event_sequence'],'sheet_recorded_through':state.get('sheet_recorded_through',0),'events':[deepcopy(x) for x in state['events'] if int(x.get('sequence',0))>after]})
        elif op=='EVENTS_MARK_RECORDED':
            through=int(req.get('through_sequence',0))
            if through<state.get('sheet_recorded_through',0) or through>state.get('event_sequence',0): raise ValueError('invalid through_sequence')
            state['sheet_recorded_through']=through; state['version']+=1; write_all(); emit_event('EVENTS_MARK_RECORDED',{'through_sequence':through,'version':state['version']}); respond(conn,{'ok':True,'sheet_recorded_through':through,'state_version':state['version']})
        elif op=='KB_APPEND':
            rec=req['record']; validate_record(rec)
            known={r['id'] for r in overlay['records']}
            if rec['id'] in known: raise ValueError('duplicate overlay id')
            overlay['records'].append(rec); overlay['version']+=1; write_all(); emit_event('KB_APPEND',{'id':rec['id'],'overlay_version':overlay['version']}); respond(conn,{'ok':True,'overlay_version':overlay['version'],'pending':len(overlay['records'])-overlay.get('published_through',0)})
        elif op=='KB_PENDING':
            respond(conn,{'ok':True,'overlay_version':overlay['version'],'records':overlay['records'][overlay.get('published_through',0):]})
        elif op=='BASE_SET':
            published=req.get('published_base')
            if not isinstance(published,dict): raise ValueError('published_base must be object')
            for key in ('repository','runtime_commit','kb_blob_sha','kb_sha256','kb_schema','kb_version'):
                if key not in published: raise ValueError(f'published_base.{key} required')
            BASE_IDENTITY.clear(); BASE_IDENTITY.update(published); atomic(PUBLISHED_BASE,BASE_IDENTITY); write_all(); emit_event('BASE_SET',{'published_base':dict(BASE_IDENTITY)}); respond(conn,{'ok':True,'published_base':dict(BASE_IDENTITY)})
        elif op=='MARK_PUBLISHED':
            published=req.get('published_base')
            if published is not None:
                if not isinstance(published,dict): raise ValueError('published_base must be object')
                for key in ('repository','runtime_commit','kb_blob_sha','kb_sha256','kb_schema','kb_version'):
                    if key not in published: raise ValueError(f'published_base.{key} required')
                BASE_IDENTITY.clear(); BASE_IDENTITY.update(published); atomic(PUBLISHED_BASE,BASE_IDENTITY)
            overlay['published_through']=len(overlay['records']); write_all(); emit_event('MARK_PUBLISHED',{'count':overlay['published_through'],'commit':req.get('commit'),'published_base':dict(BASE_IDENTITY)}); respond(conn,{'ok':True,'pending':0,'published_base':dict(BASE_IDENTITY)})
        elif op=='STOP':
            respond(conn,{'ok':True}); running=False
        else:
            respond(conn,{'ok':False,'error':'unknown op'})
    except Exception as e:
        respond(conn,{'ok':False,'error':str(e)})
    finally:
        conn.close()

srv.close()
try: SOCKET.unlink()
except FileNotFoundError: pass
emit_event('STOP',{})
