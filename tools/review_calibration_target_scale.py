#!/usr/bin/env python3
"""Record print-scale evidence for a Bividi stereo calibration target."""
from __future__ import annotations
import argparse, hashlib, json, math, tempfile
from pathlib import Path
from typing import Any, Sequence
TARGET_SCHEMA='bividi.calibration.stereo_target.v1'; REPORT_SCHEMA='bividi.calibration.stereo_target_scale_review.v1'; TOOL_VERSION='1'
class TargetScaleError(ValueError): pass
def sha(p):
 h=hashlib.sha256();
 with p.open('rb') as f:
  for c in iter(lambda:f.read(1024*1024),b''):h.update(c)
 return h.hexdigest()
def load(p):
 try:v=json.loads(p.read_text(encoding='utf-8'))
 except (OSError,json.JSONDecodeError) as e:raise TargetScaleError(f'cannot read {p}: {e}') from e
 if not isinstance(v,dict) or v.get('schema')!=TARGET_SCHEMA:raise TargetScaleError(f'{p}: expected {TARGET_SCHEMA}')
 return v
def review(path,args):
 d=load(path); design=d.get('physical_size_mm',{}); dims={}; gates={}
 for key,measured in [('width',args.measured_width_mm),('height',args.measured_height_mm)]:
  if measured is None:continue
  expected=design.get(key)
  if not isinstance(expected,(int,float)) or float(expected)<=0:raise TargetScaleError(f'target has no valid design {key}')
  if measured<=0:raise TargetScaleError(f'measured {key} must be >0')
  delta=float(measured)-float(expected); pct=abs(delta)/float(expected)*100.0
  dims[key]={'designed_mm':float(expected),'measured_mm':float(measured),'signed_delta_mm':delta,'absolute_delta_percent':pct}
  if args.max_abs_delta_percent is not None:gates[f'{key}_max_abs_delta_percent']={'limit':args.max_abs_delta_percent,'observed':pct,'pass':pct<=args.max_abs_delta_percent}
 if not dims:raise TargetScaleError('measure at least one of --measured-width-mm/--measured-height-mm')
 status='EVIDENCE_ONLY_NO_THRESHOLDS'
 if gates:
  if not args.policy_source:raise TargetScaleError('explicit print-scale gates require --policy-source')
  status='PASS' if all(v['pass'] for v in gates.values()) else 'FAIL'
 return {'schema':REPORT_SCHEMA,'target':{'path':str(path.resolve()),'sha256':sha(path.resolve()),'target_id':d.get('target_id')},'measurements':dims,'measurement_source':args.measurement_source,'method':args.method,'gates':gates,'policy_source':args.policy_source,'status':status,'provenance':{'tool':Path(__file__).name,'tool_version':TOOL_VERSION},'guardrails':['Printer DPI/fit-to-page settings are not accepted as physical scale proof; a physical measurement is required.']}
def self_test():
 with tempfile.TemporaryDirectory() as td:
  p=Path(td)/'t.json';p.write_text(json.dumps({'schema':TARGET_SCHEMA,'target_id':'t','physical_size_mm':{'width':240.0,'height':180.0}}))
  a=argparse.Namespace(measured_width_mm=239.5,measured_height_mm=None,max_abs_delta_percent=None,policy_source=None,measurement_source='synthetic',method='caliper')
  r=review(p,a);assert 0.2<r['measurements']['width']['absolute_delta_percent']<0.21
 print('Calibration target print-scale review self-test: PASS')
def main(argv:Sequence[str]|None=None):
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--self-test',action='store_true');ap.add_argument('target',nargs='?',type=Path);ap.add_argument('--measured-width-mm',type=float);ap.add_argument('--measured-height-mm',type=float);ap.add_argument('--measurement-source');ap.add_argument('--method');ap.add_argument('--max-abs-delta-percent',type=float);ap.add_argument('--policy-source');ap.add_argument('--output',type=Path);a=ap.parse_args(argv)
 if a.self_test:self_test();return 0
 if not a.target or not a.measurement_source or not a.method:raise TargetScaleError('target, --measurement-source, and --method are required')
 r=review(a.target.resolve(),a);text=json.dumps(r,indent=2)+'\n';
 if a.output:a.output.write_text(text,encoding='utf-8')
 else:print(text,end='')
 return 0 if r['status']!='FAIL' else 3
if __name__=='__main__':
 try:raise SystemExit(main())
 except TargetScaleError as e:print(f'error: {e}',file=__import__('sys').stderr);raise SystemExit(2)
