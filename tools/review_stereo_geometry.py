#!/usr/bin/env python3
"""Review calibrated stereo baseline against an explicit physical measurement."""
from __future__ import annotations
import argparse, hashlib, json, math, tempfile
from pathlib import Path
from typing import Any, Sequence
SCHEMA='bividi.calibration.stereo.v1'; REPORT_SCHEMA='bividi.calibration.stereo_geometry_review.v1'; TOOL_VERSION='1'
class ReviewError(ValueError): pass
def sha256_file(p:Path)->str:
 h=hashlib.sha256();
 with p.open('rb') as f:
  for c in iter(lambda:f.read(1024*1024),b''): h.update(c)
 return h.hexdigest()
def load(p:Path)->dict[str,Any]:
 try:v=json.loads(p.read_text(encoding='utf-8'))
 except (OSError,json.JSONDecodeError) as e: raise ReviewError(f'cannot read {p}: {e}') from e
 if not isinstance(v,dict) or v.get('schema')!=SCHEMA: raise ReviewError(f'{p}: expected {SCHEMA}')
 return v
def review(path:Path,args)->dict[str,Any]:
 d=load(path); t=d.get('stereo',{}).get('T_camera_b_from_camera_a_m')
 if not isinstance(t,list) or len(t)!=3: raise ReviewError('calibration translation missing')
 baseline=math.sqrt(sum(float(x)**2 for x in t))*1000.0
 measured=float(args.physical_baseline_mm)
 if measured<=0: raise ReviewError('--physical-baseline-mm must be > 0')
 delta=baseline-measured; abs_delta=abs(delta); pct=abs_delta/measured*100.0
 gates={}
 if args.max_abs_delta_mm is not None: gates['max_abs_delta_mm']={'limit':args.max_abs_delta_mm,'observed':abs_delta,'pass':abs_delta<=args.max_abs_delta_mm}
 if args.max_abs_delta_percent is not None: gates['max_abs_delta_percent']={'limit':args.max_abs_delta_percent,'observed':pct,'pass':pct<=args.max_abs_delta_percent}
 status='EVIDENCE_ONLY_NO_THRESHOLDS'
 if gates:
  if not args.policy_source: raise ReviewError('explicit geometry gates require --policy-source')
  status='PASS' if all(v['pass'] for v in gates.values()) else 'FAIL'
 return {'schema':REPORT_SCHEMA,'calibration':{'path':str(path.resolve()),'sha256':sha256_file(path.resolve()),'calibration_id':d.get('calibration_id')},
 'physical_measurement':{'baseline_mm':measured,'measurement_source':args.measurement_source,'method':args.method},
 'calibrated':{'baseline_mm':baseline,'translation_m':t},'comparison':{'signed_delta_mm':delta,'absolute_delta_mm':abs_delta,'absolute_delta_percent':pct},
 'gates':gates,'policy_source':args.policy_source,'status':status,'provenance':{'tool':Path(__file__).name,'tool_version':TOOL_VERSION},
 'guardrails':['A mechanical baseline check is a sanity check, not an independent full extrinsic calibration.','Measurement method/fixture uncertainty should be retained outside this scalar comparison when it is material.']}
def self_test():
 with tempfile.TemporaryDirectory() as td:
  p=Path(td)/'c.json'; p.write_text(json.dumps({'schema':SCHEMA,'calibration_id':'x','stereo':{'T_camera_b_from_camera_a_m':[-0.08,0,0]}}))
  a=argparse.Namespace(physical_baseline_mm=80.5,measurement_source='synthetic',method='synthetic',max_abs_delta_mm=None,max_abs_delta_percent=None,policy_source=None)
  r=review(p,a); assert abs(r['comparison']['absolute_delta_mm']-0.5)<1e-9
 print('Stereo geometry review self-test: PASS')
def main(argv:Sequence[str]|None=None)->int:
 ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('--self-test',action='store_true'); ap.add_argument('calibration',nargs='?',type=Path); ap.add_argument('--physical-baseline-mm',type=float); ap.add_argument('--measurement-source'); ap.add_argument('--method'); ap.add_argument('--max-abs-delta-mm',type=float); ap.add_argument('--max-abs-delta-percent',type=float); ap.add_argument('--policy-source'); ap.add_argument('--output',type=Path); a=ap.parse_args(argv)
 if a.self_test:self_test();return 0
 if not a.calibration or a.physical_baseline_mm is None or not a.measurement_source or not a.method: raise ReviewError('calibration, physical baseline, measurement source, and method are required')
 r=review(a.calibration.resolve(),a); text=json.dumps(r,indent=2)+'\n';
 if a.output:a.output.write_text(text,encoding='utf-8')
 else:print(text,end='')
 return 0 if r['status']!='FAIL' else 3
if __name__=='__main__':
 try:raise SystemExit(main())
 except ReviewError as e: print(f'error: {e}',file=__import__('sys').stderr); raise SystemExit(2)
