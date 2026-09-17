#!/usr/bin/env python3
"""Plan and audit a physical stereo-calibration campaign for Bividi issue #8.

The planner wires together target scale, session capture, dataset inspection,
native solve, physical baseline review, rectification evidence, independent-session
repeatability, optional Kalibr cross-check, and final promotion. It never invents
numeric calibration thresholds.
"""
from __future__ import annotations
import argparse, datetime as dt, json, os, tempfile
from pathlib import Path
from typing import Any, Sequence
SCHEMA='bividi.calibration.stereo_physical_campaign.v1';TOOL_VERSION='1'
class CampaignError(ValueError):pass
def utc():return dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00','Z')
def artifact(path,schema=None,required=True):
 d={'path':path,'required':required}
 if schema:d['schema']=schema
 return d
def stage(i,title,outputs,depends=(),runtime='bividi',kind='evidence',notes=()):return {'id':i,'title':title,'depends_on':list(depends),'runtime':runtime,'evidence_class':kind,'outputs':outputs,'notes':list(notes)}
def build_stages(count:int):
 if count<2:raise CampaignError('--session-count must be >= 2 because repeatability requires independent solves')
 s=[
  stage('target_definition','Create versioned physical calibration target',[artifact('target/target.json','bividi.calibration.stereo_target.v1')],kind='definition',notes=['Native path uses ChArUco; AprilGrid metadata remains available for optional Kalibr interoperability.']),
  stage('target_scale','Physically verify printed target scale',[artifact('target/target-scale.json','bividi.calibration.stereo_target_scale_review.v1')],depends=('target_definition',),kind='quality',notes=['Measure the printed board physically; printer settings are not scale proof.']),
 ]
 repeats=[]
 for n in range(1,count+1):
  sid=f'session_{n:02d}';root=f'sessions/session-{n:02d}'
  s += [
   stage(f'{sid}_capture',f'Capture diverse synchronized stereo target session #{n}',[artifact(f'{root}/session.json','bividi.calibration.stereo_session.v1')],depends=('target_scale',),kind='measured_raw',notes=['Use #35 normalized/stable capture and preserve camera_a/camera_b identities.','Deliberately vary position, scale, tilt, roll, image-plane location, and edge coverage.']),
   stage(f'{sid}_inspect',f'Inspect target detection / coverage / image quality #{n}',[artifact(f'{root}/dataset-quality.json','bividi.calibration.stereo_dataset_quality.v1')],depends=(f'{sid}_capture',),kind='quality'),
   stage(f'{sid}_solve',f'Solve mono intrinsics + fixed-intrinsic stereo geometry #{n}',[artifact(f'{root}/stereo-calibration.json','bividi.calibration.stereo.v1')],depends=(f'{sid}_inspect',),kind='candidate',notes=['Do not use vendor nominal FOV/baseline as solver inputs.']),
   stage(f'{sid}_geometry',f'Compare recovered baseline with physical measurement #{n}',[artifact(f'{root}/geometry-review.json','bividi.calibration.stereo_geometry_review.v1')],depends=(f'{sid}_solve',),kind='quality'),
   stage(f'{sid}_rectify',f'Rectification inspection evidence #{n}',[artifact(f'{root}/rectified-sample.png')],depends=(f'{sid}_solve',),kind='inspection'),
   stage(f'{sid}_kalibr_reference',f'Optional AprilGrid/Kalibr cross-check #{n}',[artifact(f'{root}/kalibr-reference.json',required=False)],depends=(f'{sid}_solve',),runtime='external_kalibr',kind='optional_reference',notes=['Optional reference only; ROS/Kalibr is not a Bividi runtime dependency.']),
  ]
  repeats.append(f'{sid}_geometry')
 s += [
  stage('repeatability','Compare independent stereo solves',[artifact('final/repeatability.json','bividi.calibration.stereo_repeatability.v1')],depends=tuple(repeats),kind='quality'),
  stage('promotion','Hash-bind target/session/quality/geometry/repeatability evidence',[artifact('final/stereo-evidence.json','bividi.calibration.stereo_evidence_manifest.v1')],depends=('repeatability',),kind='promotion',notes=['Use promotion profile only after explicit target/dataset/solve/geometry/repeatability gates PASS under a named policy.','PROMOTION_READY is a controlled evidence disposition, not independent proof of physical accuracy.']),
 ]
 return s
def manifest(a):return {'schema':SCHEMA,'campaign_id':a.campaign_id,'created_utc':utc(),'specimen':{'model':a.model,'serial':a.serial},'capture':{'device_index':a.device,'mode_index':a.mode,'pixel_format':a.pixel_format,'width':a.width,'height':a.height,'camera_mapping_evidence':a.camera_mapping_evidence},'session_count':a.session_count,'policy_source':a.policy_source,'dependencies':{'host_acquisition_issue':35,'stereo_calibration_issue':8,'depth_issue':9,'camera_imu_issue':47,'vio_issue':46},'stages':build_stages(a.session_count),'guardrails':['No numeric acceptance threshold is invented by this planner.','camera_a/camera_b are not renamed left/right without #35 physical mapping evidence.','Vendor nominal FOV/baseline are reference-only, not measured calibration.','#9 metric-depth and #46 live-VIO accuracy claims remain blocked until measured calibration is frozen.'],'provenance':{'tool':Path(__file__).name,'tool_version':TOOL_VERSION}}
def runbook(m):
 lines=[f"# Stereo Physical Calibration Campaign — {m['campaign_id']}",'',f"Specimen: `{m['specimen']['model']}` / `{m['specimen']['serial']}`  ",f"Device/mode: `{m['capture']['device_index']}` / `{m['capture']['mode_index']}`  ",f"Image: `{m['capture']['width']}x{m['capture']['height']} {m['capture']['pixel_format']}`",'', '## Execution rule','', 'Target scale first; diverse captures second; solve only after dataset inspection; promotion only after independent repeatability.','']
 for i,s in enumerate(m['stages'],1):
  deps=', '.join(s['depends_on']) if s['depends_on'] else 'none';outs=', '.join(x['path'] for x in s['outputs'])
  lines += [f"### {i}. `{s['id']}` — {s['title']}",'',f"Runtime: `{s['runtime']}`  ",f"Evidence: `{s['evidence_class']}`  ",f"Depends on: `{deps}`  ",f"Expected output(s): `{outs}`",'']
  for n in s['notes']:lines.append(f'- {n}')
  if s['notes']:lines.append('')
 lines += ['## Capture coverage procedure','', '- Fill center and all image quadrants/edges; do not only collect centered frontal boards.','- Vary board distance/apparent scale and out-of-plane tilt around both axes.','- Include roll variation.','- Keep motion blur and clipping visible to the dataset inspector rather than deleting weak frames silently.','- Preserve rejected/weak-pair evidence in the quality report; re-capture instead of accepting poor coverage.','', '## Final rule','', 'The selected artifact must be included in the repeatability campaign and be hash-bound by the final evidence manifest. Explicit thresholds must come from the recorded lab/product policy.','']
 return '\n'.join(lines)
def write(p,d):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d,indent=2)+'\n',encoding='utf-8')
def load(p):
 try:d=json.loads(p.read_text(encoding='utf-8'))
 except (OSError,json.JSONDecodeError) as e:raise CampaignError(f'cannot read {p}: {e}') from e
 if not isinstance(d,dict) or d.get('schema')!=SCHEMA:raise CampaignError(f'{p}: expected {SCHEMA}')
 return d
def audit(path:Path):
 m=load(path);root=path.parent;states={};details=[]
 for s in m['stages']:
  deps=all(states.get(x)=='complete' for x in s['depends_on']);outs=[];required_ok=True;any_present=False
  for item in s['outputs']:
   p=root/item['path'];present=p.is_file();any_present|=present;schema_ok=None
   if present and item.get('schema'):
    try:v=json.loads(p.read_text(encoding='utf-8'));schema_ok=isinstance(v,dict) and v.get('schema')==item['schema']
    except (OSError,json.JSONDecodeError):schema_ok=False
   if item.get('required',True) and (not present or schema_ok is False):required_ok=False
   outs.append({'path':item['path'],'required':item.get('required',True),'present':present,'schema_ok':schema_ok})
  has_required=any(item.get('required',True) for item in s['outputs'])
  if required_ok and (has_required or any_present):state='complete'
  elif deps:state='ready'
  else:state='blocked'
  states[s['id']]=state;details.append({'id':s['id'],'state':state,'outputs':outs})
 return {'schema':'bividi.calibration.stereo_physical_campaign_audit.v1','campaign_id':m['campaign_id'],'summary':{'stages':len(states),'complete':sum(v=='complete' for v in states.values()),'ready':sum(v=='ready' for v in states.values()),'blocked':sum(v=='blocked' for v in states.values())},'stages':details,'promotion_artifact_present':states.get('promotion')=='complete','note':'Presence/schema audit only; quality/hash/policy verification remains owned by the evidence tools.'}
def self_test():
 with tempfile.TemporaryDirectory() as td:
  root=Path(td);a=argparse.Namespace(campaign_id='synthetic',model='S',serial='1',device=0,mode=0,pixel_format='GRAY8',width=1280,height=720,camera_mapping_evidence='synthetic',session_count=2,policy_source=None)
  m=manifest(a);write(root/'campaign.json',m);(root/'RUNBOOK.md').write_text(runbook(m));r=audit(root/'campaign.json');assert r['summary']['complete']==0
  p=root/m['stages'][0]['outputs'][0]['path'];p.parent.mkdir(parents=True);p.write_text(json.dumps({'schema':'bividi.calibration.stereo_target.v1'}));r=audit(root/'campaign.json');assert r['stages'][0]['state']=='complete'
  try:build_stages(1);raise AssertionError()
  except CampaignError:pass
 print('Stereo physical campaign planner self-test: PASS')
def parse(argv:Sequence[str]|None=None):
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--self-test',action='store_true');sub=ap.add_subparsers(dest='cmd')
 i=sub.add_parser('init');i.add_argument('root',type=Path);i.add_argument('--campaign-id',required=True);i.add_argument('--model',required=True);i.add_argument('--serial',required=True);i.add_argument('--device',type=int,required=True);i.add_argument('--mode',type=int,required=True);i.add_argument('--pixel-format',required=True);i.add_argument('--width',type=int,required=True);i.add_argument('--height',type=int,required=True);i.add_argument('--camera-mapping-evidence');i.add_argument('--session-count',type=int,required=True);i.add_argument('--policy-source')
 a=sub.add_parser('audit');a.add_argument('manifest',type=Path);a.add_argument('--output',type=Path)
 return ap.parse_args(argv)
def main(argv=None):
 a=parse(argv)
 if a.self_test:self_test();return 0
 if a.cmd=='init':
  root=a.root.resolve()
  if root.exists() and any(root.iterdir()):raise CampaignError(f'campaign root is not empty: {root}')
  root.mkdir(parents=True,exist_ok=True);m=manifest(a);write(root/'campaign.json',m);(root/'RUNBOOK.md').write_text(runbook(m),encoding='utf-8');print(root/'campaign.json');print(root/'RUNBOOK.md');return 0
 if a.cmd=='audit':
  r=audit(a.manifest.resolve());text=json.dumps(r,indent=2)+'\n';
  if a.output:a.output.write_text(text,encoding='utf-8')
  else:print(text,end='')
  return 0
 raise CampaignError('choose init/audit or --self-test')
if __name__=='__main__':
 try:raise SystemExit(main())
 except CampaignError as e:print(f'error: {e}',file=__import__('sys').stderr);raise SystemExit(2)
