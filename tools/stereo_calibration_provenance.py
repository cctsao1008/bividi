#!/usr/bin/env python3
"""Hash-bind and gate the final stereo-calibration evidence bundle for issue #8.

Profiles:
  integrity  verify file hashes/schemas/cross-links
  review     integrity + no quality evidence may be FAIL
  promotion  review + all quality evidence must be explicit PASS with gates,
             measured provenance, verified camera mapping, and named policy source

The gate owns no calibration thresholds. Numeric limits remain with the evidence
producers and must be justified by a lab/product policy.
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, os, tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

TARGET_SCHEMA='bividi.calibration.stereo_target.v1'
TARGET_SCALE_SCHEMA='bividi.calibration.stereo_target_scale_review.v1'
SESSION_SCHEMA='bividi.calibration.stereo_session.v1'
QUALITY_SCHEMA='bividi.calibration.stereo_dataset_quality.v1'
CALIB_SCHEMA='bividi.calibration.stereo.v1'
GEOMETRY_SCHEMA='bividi.calibration.stereo_geometry_review.v1'
REPEAT_SCHEMA='bividi.calibration.stereo_repeatability.v1'
MANIFEST_SCHEMA='bividi.calibration.stereo_evidence_manifest.v1'
TOOL_VERSION='1'
ROLES={
 'target':TARGET_SCHEMA,'target_scale':TARGET_SCALE_SCHEMA,'session':SESSION_SCHEMA,
 'dataset_quality':QUALITY_SCHEMA,'calibration':CALIB_SCHEMA,'geometry_review':GEOMETRY_SCHEMA,
 'repeatability':REPEAT_SCHEMA,
}
QUALITY_ROLES=('target_scale','dataset_quality','calibration','geometry_review','repeatability')
PLACEHOLDERS={'','unknown','n/a','na','tbd','unset','none','?'}
class GateError(ValueError):pass

def utc_now():return dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00','Z')
def sha(p:Path)->str:
 h=hashlib.sha256();
 with p.open('rb') as f:
  for c in iter(lambda:f.read(1024*1024),b''):h.update(c)
 return h.hexdigest()
def load(p:Path)->dict[str,Any]:
 try:v=json.loads(p.read_text(encoding='utf-8'))
 except (OSError,json.JSONDecodeError) as e:raise GateError(f'cannot read {p}: {e}') from e
 if not isinstance(v,dict):raise GateError(f'{p}: expected object')
 return v
def placeholder(v:Any)->bool:return not isinstance(v,str) or v.strip().lower() in PLACEHOLDERS
def rel(p:Path,owner:Path)->str:
 try:return os.path.relpath(p.resolve(),owner.parent.resolve()).replace(os.sep,'/')
 except ValueError:return str(p.resolve()).replace(os.sep,'/')
def resolve(owner:Path,text:str)->Path:
 p=Path(text);return p if p.is_absolute() else (owner.parent/p).resolve()
def record(role:str,p:Path,owner:Path)->dict[str,Any]:
 d=load(p); expected=ROLES[role]
 if d.get('schema')!=expected:raise GateError(f'{role}: expected {expected}; got {d.get("schema")!r}')
 return {'role':role,'path':rel(p,owner),'sha256':sha(p),'bytes':p.stat().st_size,'schema':expected}
def verified(entry:Mapping[str,Any],owner:Path)->tuple[Path,dict[str,Any]]:
 role=entry.get('role');
 if role not in ROLES:raise GateError(f'unknown evidence role {role!r}')
 p=resolve(owner,str(entry.get('path','')))
 if not p.is_file():raise GateError(f'{role}: missing {p}')
 if sha(p)!=entry.get('sha256'):raise GateError(f'{role}: SHA-256 mismatch')
 d=load(p)
 if d.get('schema')!=ROLES[role]:raise GateError(f'{role}: schema mismatch')
 return p,d

def status_of(role:str,d:Mapping[str,Any])->str|None:
 if role=='calibration': return d.get('quality',{}).get('status') if isinstance(d.get('quality'),Mapping) else None
 return d.get('status') if isinstance(d.get('status'),str) else None
def gates_of(role:str,d:Mapping[str,Any])->Mapping[str,Any]:
 if role=='calibration':
  q=d.get('quality'); return q.get('gates',{}) if isinstance(q,Mapping) and isinstance(q.get('gates'),Mapping) else {}
 g=d.get('gates'); return g if isinstance(g,Mapping) else {}
def policy_of(role:str,d:Mapping[str,Any])->Any:
 if role=='calibration':
  q=d.get('quality'); return q.get('policy_source') if isinstance(q,Mapping) else None
 return d.get('policy_source')

def cross_check(data:Mapping[str,dict[str,Any]], paths:Mapping[str,Path])->list[str]:
 findings=[]
 target,scale,session,quality,calib,geometry,repeat=[data[k] for k in ('target','target_scale','session','dataset_quality','calibration','geometry_review','repeatability')]
 target_hash=sha(paths['target']);session_hash=sha(paths['session']);calib_hash=sha(paths['calibration'])
 if scale.get('target',{}).get('sha256')!=target_hash:findings.append('target_scale does not bind selected target')
 if session.get('target',{}).get('sha256')!=target_hash:findings.append('session does not bind selected target')
 if quality.get('session',{}).get('sha256')!=session_hash:findings.append('dataset_quality does not bind selected session')
 if quality.get('target',{}).get('sha256')!=target_hash:findings.append('dataset_quality does not bind selected target')
 prov=calib.get('provenance',{})
 if prov.get('source_session_sha256')!=session_hash:findings.append('calibration does not bind selected session')
 if calib.get('target',{}).get('sha256')!=target_hash:findings.append('calibration does not bind selected target')
 if geometry.get('calibration',{}).get('sha256')!=calib_hash:findings.append('geometry_review does not bind selected calibration')
 artifacts=repeat.get('artifacts',[])
 hashes={x.get('sha256') for x in artifacts if isinstance(x,Mapping)}
 if calib_hash not in hashes:findings.append('repeatability campaign does not include selected calibration')
 for role,d in [('calibration',calib)]:
  if d.get('device')!=session.get('device'):findings.append(f'{role} device identity differs from session')
  c1=d.get('capture',{});c2=session.get('capture',{})
  for key in ('mode_index','pixel_format','width','height'):
   if c1.get(key)!=c2.get(key):findings.append(f'{role} capture.{key} differs from session')
 return findings

def build(args)->dict[str,Any]:
 out=args.output.resolve(); selected={k:getattr(args,k).resolve() for k in ROLES}
 docs={k:load(p) for k,p in selected.items()}
 for k,d in docs.items():
  if d.get('schema')!=ROLES[k]:raise GateError(f'{k}: expected {ROLES[k]}')
 records=[record(k,selected[k],out) for k in ROLES]
 manifest={'schema':MANIFEST_SCHEMA,'created_utc':utc_now(),'profile':args.profile,'policy_source':args.policy_source,
 'evidence':records,'provenance':{'tool':Path(__file__).name,'tool_version':TOOL_VERSION}}
 return evaluate(manifest,out,docs_override=docs,paths_override=selected)

def evidence_map(m:Mapping[str,Any])->dict[str,Mapping[str,Any]]:
 entries=m.get('evidence');
 if not isinstance(entries,list):raise GateError('evidence array required')
 result={}
 for e in entries:
  if not isinstance(e,Mapping):raise GateError('invalid evidence entry')
  r=e.get('role')
  if r in result:raise GateError(f'duplicate role {r}')
  result[r]=e
 missing=set(ROLES)-set(result)
 if missing:raise GateError('missing evidence roles: '+', '.join(sorted(missing)))
 return result

def evaluate(m:dict[str,Any],owner:Path,docs_override=None,paths_override=None)->dict[str,Any]:
 if m.get('schema')!=MANIFEST_SCHEMA:raise GateError(f'expected {MANIFEST_SCHEMA}')
 entries=evidence_map(m); docs={}; paths={}
 if docs_override is None:
  for role,e in entries.items(): paths[role],docs[role]=verified(e,owner)
 else: docs=dict(docs_override);paths=dict(paths_override)
 findings=cross_check(docs,paths)
 profile=m.get('profile')
 if profile not in {'integrity','review','promotion'}:raise GateError('profile must be integrity/review/promotion')
 quality_status={r:status_of(r,docs[r]) for r in QUALITY_ROLES}
 if profile in {'review','promotion'}:
  for r,s in quality_status.items():
   if s=='FAIL':findings.append(f'{r} status is FAIL')
 if profile=='promotion':
  if placeholder(m.get('policy_source')):findings.append('promotion requires non-placeholder manifest policy_source')
  if docs['session'].get('provenance',{}).get('kind')!='measured':findings.append('promotion requires measured session provenance')
  if docs['calibration'].get('provenance',{}).get('kind')!='measured':findings.append('promotion requires measured calibration provenance')
  mapping=docs['session'].get('capture',{}).get('camera_mapping_evidence')
  if placeholder(mapping):findings.append('promotion requires #35 camera mapping evidence in session.capture.camera_mapping_evidence')
  for r in QUALITY_ROLES:
   s=quality_status[r]
   if s!='PASS':findings.append(f'promotion requires {r} status PASS; got {s!r}')
   if not gates_of(r,docs[r]):findings.append(f'promotion requires explicit gates in {r}')
   if placeholder(policy_of(r,docs[r])):findings.append(f'promotion requires {r} policy_source')
 disposition='PROMOTION_READY' if profile=='promotion' and not findings else ('REVIEWABLE' if profile=='review' and not findings else ('INTEGRITY_OK' if profile=='integrity' and not findings else 'FAIL'))
 m=dict(m);m['quality_status']=quality_status;m['findings']=findings;m['disposition']=disposition
 return m

def verify(path:Path)->dict[str,Any]:return evaluate(load(path),path)
def self_test():
 with tempfile.TemporaryDirectory() as td:
  root=Path(td);out=root/'manifest.json'
  target={'schema':TARGET_SCHEMA,'target_id':'t'};tp=root/'target.json';tp.write_text(json.dumps(target))
  t_hash=sha(tp)
  session={'schema':SESSION_SCHEMA,'session_id':'s','provenance':{'kind':'measured'},'device':{'model':'M','serial':'S'},'capture':{'mode_index':0,'pixel_format':'GRAY8','width':640,'height':480,'camera_mapping_evidence':'#35 physical mapping note'},'target':{'sha256':t_hash}}
  sp=root/'session.json';sp.write_text(json.dumps(session));s_hash=sha(sp)
  scale={'schema':TARGET_SCALE_SCHEMA,'target':{'sha256':t_hash},'status':'PASS','gates':{'g':{'pass':True}},'policy_source':'lab-v1'}
  qual={'schema':QUALITY_SCHEMA,'session':{'sha256':s_hash},'target':{'sha256':t_hash},'status':'PASS','gates':{'g':{'pass':True}},'policy_source':'lab-v1'}
  calib={'schema':CALIB_SCHEMA,'calibration_id':'c','provenance':{'kind':'measured','source_session_sha256':s_hash},'device':session['device'],'capture':session['capture'],'target':{'sha256':t_hash},'quality':{'status':'PASS','gates':{'g':{'pass':True}},'policy_source':'lab-v1'}}
  cp=root/'calib.json';cp.write_text(json.dumps(calib));c_hash=sha(cp)
  geo={'schema':GEOMETRY_SCHEMA,'calibration':{'sha256':c_hash},'status':'PASS','gates':{'g':{'pass':True}},'policy_source':'lab-v1'}
  rep={'schema':REPEAT_SCHEMA,'artifacts':[{'sha256':c_hash}], 'status':'PASS','gates':{'g':{'pass':True}},'policy_source':'lab-v1'}
  files={'target':tp,'session':sp,'calibration':cp}
  for name,data in [('target_scale',scale),('dataset_quality',qual),('geometry_review',geo),('repeatability',rep)]:p=root/(name+'.json');p.write_text(json.dumps(data));files[name]=p
  ns=argparse.Namespace(output=out,profile='promotion',policy_source='lab-v1',**files)
  m=build(ns);assert m['disposition']=='PROMOTION_READY',m['findings'];out.write_text(json.dumps(m));assert verify(out)['disposition']=='PROMOTION_READY'
 print('Stereo calibration evidence promotion gate self-test: PASS')
def parse(argv:Sequence[str]|None=None):
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--self-test',action='store_true');sub=ap.add_subparsers(dest='cmd')
 b=sub.add_parser('build');
 for r in ROLES:b.add_argument('--'+r.replace('_','-'),dest=r,type=Path,required=True)
 b.add_argument('--profile',choices=('integrity','review','promotion'),required=True);b.add_argument('--policy-source');b.add_argument('--output',type=Path,required=True)
 v=sub.add_parser('verify');v.add_argument('manifest',type=Path)
 return ap.parse_args(argv)
def main(argv=None):
 a=parse(argv)
 if a.self_test:self_test();return 0
 if a.cmd=='build':m=build(a);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(m,indent=2)+'\n');print(m['disposition']);return 0 if m['disposition']!='FAIL' else 3
 if a.cmd=='verify':m=verify(a.manifest.resolve());print(json.dumps(m,indent=2));return 0 if m['disposition']!='FAIL' else 3
 raise GateError('choose build/verify or --self-test')
if __name__=='__main__':
 try:raise SystemExit(main())
 except GateError as e:print(f'error: {e}',file=__import__('sys').stderr);raise SystemExit(2)
