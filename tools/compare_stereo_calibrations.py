#!/usr/bin/env python3
"""Compare independent Bividi stereo calibration artifacts for repeatability.

No universal tolerance is invented. Without explicit gates the report remains
EVIDENCE_ONLY_NO_THRESHOLDS. With gates, a named policy source is required.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import tempfile
from itertools import combinations
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA = "bividi.calibration.stereo.v1"
REPORT_SCHEMA = "bividi.calibration.stereo_repeatability.v1"
TOOL_VERSION = "1"
CAMERAS = ("camera_a", "camera_b")

class CompareError(ValueError): pass

def sha256_file(path: Path) -> str:
    h=hashlib.sha256();
    with path.open('rb') as f:
        for c in iter(lambda:f.read(1024*1024), b''): h.update(c)
    return h.hexdigest()

def load(path: Path) -> dict[str,Any]:
    try: v=json.loads(path.read_text(encoding='utf-8'))
    except (OSError,json.JSONDecodeError) as e: raise CompareError(f"cannot read {path}: {e}") from e
    if not isinstance(v,dict) or v.get('schema')!=SCHEMA: raise CompareError(f"{path}: expected {SCHEMA}")
    return v

def vec_norm(v): return math.sqrt(sum(float(x)**2 for x in v))
def dot(a,b): return sum(float(x)*float(y) for x,y in zip(a,b))
def rotation_delta_deg(a,b):
    r=[[sum(float(a[i][k])*float(b[j][k]) for k in range(3)) for j in range(3)] for i in range(3)]
    c=max(-1.0,min(1.0,(r[0][0]+r[1][1]+r[2][2]-1.0)/2.0))
    return math.degrees(math.acos(c))
def direction_delta_deg(a,b):
    na,nb=vec_norm(a),vec_norm(b)
    if na<=0 or nb<=0: raise CompareError('zero stereo translation')
    c=max(-1.0,min(1.0,dot(a,b)/(na*nb)))
    return math.degrees(math.acos(c))
def percent_delta(a,b):
    denom=max(abs(float(a)),abs(float(b)))
    return 0.0 if denom==0 else abs(float(a)-float(b))/denom*100.0

def identity_key(d: Mapping[str,Any]):
    return {
      'device_model': d.get('device',{}).get('model'), 'device_serial': d.get('device',{}).get('serial'),
      'mode_index': d.get('capture',{}).get('mode_index'), 'pixel_format': d.get('capture',{}).get('pixel_format'),
      'width': d.get('image',{}).get('width'), 'height': d.get('image',{}).get('height'),
      'target_id': d.get('target',{}).get('target_id'), 'target_sha256': d.get('target',{}).get('sha256'),
      'camera_model': d.get('camera_model'),
    }

def compare(paths: Sequence[Path], args) -> dict[str,Any]:
    if len(paths)<2: raise CompareError('at least two calibration artifacts are required')
    docs=[load(p.resolve()) for p in paths]
    base=identity_key(docs[0])
    for p,d in zip(paths[1:],docs[1:]):
        if identity_key(d)!=base: raise CompareError(f"{p}: incompatible device/mode/target/camera-model identity")
    pair_reports=[]
    for (ia,a),(ib,b) in combinations(list(enumerate(docs)),2):
        ta=a['stereo']['T_camera_b_from_camera_a_m']; tb=b['stereo']['T_camera_b_from_camera_a_m']
        entry={
          'a_index':ia,'b_index':ib,
          'rotation_delta_deg':rotation_delta_deg(a['stereo']['R_camera_b_from_camera_a'], b['stereo']['R_camera_b_from_camera_a']),
          'baseline_delta_mm':abs(vec_norm(ta)-vec_norm(tb))*1000.0,
          'translation_direction_delta_deg':direction_delta_deg(ta,tb),
          'camera_a_fx_delta_percent':percent_delta(a['cameras']['camera_a']['K'][0][0], b['cameras']['camera_a']['K'][0][0]),
          'camera_a_fy_delta_percent':percent_delta(a['cameras']['camera_a']['K'][1][1], b['cameras']['camera_a']['K'][1][1]),
          'camera_b_fx_delta_percent':percent_delta(a['cameras']['camera_b']['K'][0][0], b['cameras']['camera_b']['K'][0][0]),
          'camera_b_fy_delta_percent':percent_delta(a['cameras']['camera_b']['K'][1][1], b['cameras']['camera_b']['K'][1][1]),
          'camera_a_principal_point_delta_px':math.hypot(float(a['cameras']['camera_a']['K'][0][2])-float(b['cameras']['camera_a']['K'][0][2]), float(a['cameras']['camera_a']['K'][1][2])-float(b['cameras']['camera_a']['K'][1][2])),
          'camera_b_principal_point_delta_px':math.hypot(float(a['cameras']['camera_b']['K'][0][2])-float(b['cameras']['camera_b']['K'][0][2]), float(a['cameras']['camera_b']['K'][1][2])-float(b['cameras']['camera_b']['K'][1][2])),
        }
        pair_reports.append(entry)
    def maxv(k): return max(float(x[k]) for x in pair_reports)
    summary={
      'artifact_count':len(docs),'pair_count':len(pair_reports),
      'max_rotation_delta_deg':maxv('rotation_delta_deg'),'max_baseline_delta_mm':maxv('baseline_delta_mm'),
      'max_translation_direction_delta_deg':maxv('translation_direction_delta_deg'),
      'max_focal_delta_percent':max(maxv('camera_a_fx_delta_percent'),maxv('camera_a_fy_delta_percent'),maxv('camera_b_fx_delta_percent'),maxv('camera_b_fy_delta_percent')),
      'max_principal_point_delta_px':max(maxv('camera_a_principal_point_delta_px'),maxv('camera_b_principal_point_delta_px')),
    }
    gates={}
    for name,limit,key in [
      ('max_rotation_delta_deg',args.max_rotation_delta_deg,'max_rotation_delta_deg'),
      ('max_baseline_delta_mm',args.max_baseline_delta_mm,'max_baseline_delta_mm'),
      ('max_translation_direction_delta_deg',args.max_translation_direction_delta_deg,'max_translation_direction_delta_deg'),
      ('max_focal_delta_percent',args.max_focal_delta_percent,'max_focal_delta_percent'),
      ('max_principal_point_delta_px',args.max_principal_point_delta_px,'max_principal_point_delta_px')]:
        if limit is not None: gates[name]={'limit':limit,'observed':summary[key],'pass':summary[key]<=limit}
    status='EVIDENCE_ONLY_NO_THRESHOLDS'
    if gates:
        if not args.policy_source: raise CompareError('explicit repeatability gates require --policy-source')
        status='PASS' if all(v['pass'] for v in gates.values()) else 'FAIL'
    return {
      'schema':REPORT_SCHEMA,'provenance':{'tool':Path(__file__).name,'tool_version':TOOL_VERSION},
      'identity':base,
      'artifacts':[{'path':str(p.resolve()),'sha256':sha256_file(p.resolve()),'calibration_id':d.get('calibration_id'),'provenance_kind':d.get('provenance',{}).get('kind')} for p,d in zip(paths,docs)],
      'pairs':pair_reports,'summary':summary,'gates':gates,'policy_source':args.policy_source,'status':status,
      'guardrails':['Repeatability is consistency evidence, not independent calibration truth.','Independent captures/solves are required; copied artifacts do not establish repeatability.']
    }

def self_test():
    with tempfile.TemporaryDirectory() as td:
      root=Path(td)
      def doc(cid,b,r00=1.0):
        return {'schema':SCHEMA,'calibration_id':cid,'device':{'model':'S','serial':'1'},'capture':{'mode_index':0,'pixel_format':'GRAY8'},'image':{'width':1280,'height':720},'target':{'target_id':'t','sha256':'abc'},'camera_model':{'projection':'pinhole','distortion':'opencv5'},'provenance':{'kind':'synthetic'},
        'cameras':{'camera_a':{'K':[[700,0,640],[0,700,360],[0,0,1]]},'camera_b':{'K':[[701,0,640],[0,701,360],[0,0,1]]}},
        'stereo':{'R_camera_b_from_camera_a':[[r00,0,0],[0,1,0],[0,0,r00]],'T_camera_b_from_camera_a_m':[-b,0,0]}}
      a=doc('a',0.080)
      angle=math.radians(0.2); c=math.cos(angle); s=math.sin(angle)
      b=doc('b',0.0805); b['stereo']['R_camera_b_from_camera_a']=[[c,-s,0],[s,c,0],[0,0,1]]
      p1=root/'a.json'; p2=root/'b.json'; p1.write_text(json.dumps(a)); p2.write_text(json.dumps(b))
      args=argparse.Namespace(max_rotation_delta_deg=None,max_baseline_delta_mm=None,max_translation_direction_delta_deg=None,max_focal_delta_percent=None,max_principal_point_delta_px=None,policy_source=None)
      r=compare([p1,p2],args); assert 0.49<r['summary']['max_baseline_delta_mm']<0.51; assert r['status'].startswith('EVIDENCE')
    print('Stereo calibration repeatability comparator self-test: PASS')

def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('--self-test',action='store_true'); ap.add_argument('artifacts',nargs='*',type=Path); ap.add_argument('--output',type=Path)
    ap.add_argument('--policy-source'); ap.add_argument('--max-rotation-delta-deg',type=float); ap.add_argument('--max-baseline-delta-mm',type=float); ap.add_argument('--max-translation-direction-delta-deg',type=float); ap.add_argument('--max-focal-delta-percent',type=float); ap.add_argument('--max-principal-point-delta-px',type=float)
    args=ap.parse_args(argv)
    if args.self_test: self_test(); return 0
    report=compare(args.artifacts,args); text=json.dumps(report,indent=2)+'\n'
    if args.output: args.output.write_text(text,encoding='utf-8')
    else: print(text,end='')
    return 0 if report['status']!='FAIL' else 3
if __name__=='__main__':
    try: raise SystemExit(main())
    except CompareError as e: print(f'error: {e}',file=__import__('sys').stderr); raise SystemExit(2)
