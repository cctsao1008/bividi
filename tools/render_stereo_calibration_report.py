#!/usr/bin/env python3
"""Render a human-readable review report from #8 stereo evidence JSON files."""
from __future__ import annotations
import argparse, json, tempfile
from pathlib import Path
from typing import Any, Sequence
SCHEMAS={
 'target_scale':'bividi.calibration.stereo_target_scale_review.v1',
 'dataset_quality':'bividi.calibration.stereo_dataset_quality.v1',
 'calibration':'bividi.calibration.stereo.v1',
 'geometry':'bividi.calibration.stereo_geometry_review.v1',
 'repeatability':'bividi.calibration.stereo_repeatability.v1',
}
class ReportError(ValueError):pass
def load(path:Path,schema:str)->dict[str,Any]:
 try:d=json.loads(path.read_text(encoding='utf-8'))
 except (OSError,json.JSONDecodeError) as e:raise ReportError(f'cannot read {path}: {e}') from e
 if not isinstance(d,dict) or d.get('schema')!=schema:raise ReportError(f'{path}: expected {schema}')
 return d
def f(v,d=4):return 'n/a' if v is None else f'{float(v):.{d}f}'
def render(paths:dict[str,Path])->str:
 d={k:load(paths[k],SCHEMAS[k]) for k in SCHEMAS};c=d['calibration'];q=d['dataset_quality'];g=d['geometry'];r=d['repeatability'];ts=d['target_scale']
 lines=['# Stereo calibration evidence report','',f"Calibration: `{c.get('calibration_id','unknown')}`  ",f"Specimen: `{c.get('device',{}).get('model','?')}` / `{c.get('device',{}).get('serial','?')}`  ",f"Mode: `{c.get('capture',{}).get('mode_index','?')}`  ",f"Image: `{c.get('image',{}).get('width','?')}x{c.get('image',{}).get('height','?')}`",'', '## Evidence disposition','', '| Evidence | Status | Policy |','|---|---|---|',f"| Printed target scale | {ts.get('status')} | {ts.get('policy_source') or 'none'} |",f"| Dataset quality | {q.get('status')} | {q.get('policy_source') or 'none'} |",f"| Calibration fit | {c.get('quality',{}).get('status')} | {c.get('quality',{}).get('policy_source') or 'none'} |",f"| Physical geometry | {g.get('status')} | {g.get('policy_source') or 'none'} |",f"| Repeatability | {r.get('status')} | {r.get('policy_source') or 'none'} |",'', '## Intrinsics and reprojection','', '| Camera | fx | fy | cx | cy | mono RMS px | FOV x/y deg |','|---|---:|---:|---:|---:|---:|---:|']
 for cam in ('camera_a','camera_b'):
  x=c['cameras'][cam];K=x['K'];fv=x.get('pinhole_fov_deg',{});lines.append(f"| {cam} | {f(K[0][0])} | {f(K[1][1])} | {f(K[0][2])} | {f(K[1][2])} | {f(x.get('mono_rms_px'))} | {f(fv.get('x'),2)} / {f(fv.get('y'),2)} |")
 ve=c.get('rectification',{}).get('vertical_epipolar_abs_px',{})
 lines += ['', '## Stereo geometry / rectification','',f"- Stereo RMS: `{f(c.get('stereo',{}).get('stereo_rms_px'))} px`",f"- Baseline: `{f(c.get('stereo',{}).get('baseline_m'),6)} m`",f"- Vertical epipolar residual p95: `{f(ve.get('p95'))} px`",f"- Vertical epipolar residual max: `{f(ve.get('max'))} px`",f"- Physical baseline delta: `{f(g.get('comparison',{}).get('absolute_delta_mm'))} mm`",'', '## Dataset coverage','']
 for cam in ('camera_a','camera_b'):
  x=q.get('cameras',{}).get(cam,{});lines.append(f"- {cam}: global hull `{f(x.get('global_image_plane_hull_fraction'))}`, target-corner fraction `{f(x.get('target_corner_fraction'))}`, centroid span x/y `{f(x.get('centroid_x_span_fraction'))}` / `{f(x.get('centroid_y_span_fraction'))}`")
 rs=r.get('summary',{});lines += ['', '## Independent-session repeatability','',f"- Compared artifacts: `{rs.get('artifact_count','?')}`",f"- Max rotation delta: `{f(rs.get('max_rotation_delta_deg'))} deg`",f"- Max baseline delta: `{f(rs.get('max_baseline_delta_mm'))} mm`",f"- Max translation-direction delta: `{f(rs.get('max_translation_direction_delta_deg'))} deg`",f"- Max focal delta: `{f(rs.get('max_focal_delta_percent'))} %`",f"- Max principal-point delta: `{f(rs.get('max_principal_point_delta_px'))} px`",'', '## Interpretation boundary','', 'This report is a rendering of machine-readable evidence. It does not create new acceptance evidence, replace the final provenance gate, or prove physical accuracy by itself.','']
 return '\n'.join(lines)
def self_test():
 with tempfile.TemporaryDirectory() as td:
  root=Path(td);docs={
   'target_scale':{'schema':SCHEMAS['target_scale'],'status':'PASS','policy_source':'lab'},
   'dataset_quality':{'schema':SCHEMAS['dataset_quality'],'status':'PASS','policy_source':'lab','cameras':{'camera_a':{},'camera_b':{}}},
   'calibration':{'schema':SCHEMAS['calibration'],'calibration_id':'c','device':{'model':'M','serial':'S'},'capture':{'mode_index':0},'image':{'width':640,'height':480},'cameras':{'camera_a':{'K':[[500,0,320],[0,500,240],[0,0,1]],'mono_rms_px':.1},'camera_b':{'K':[[500,0,320],[0,500,240],[0,0,1]],'mono_rms_px':.1}},'stereo':{'baseline_m':.08,'stereo_rms_px':.2},'rectification':{'vertical_epipolar_abs_px':{'p95':.1,'max':.2}},'quality':{'status':'PASS','policy_source':'lab'}},
   'geometry':{'schema':SCHEMAS['geometry'],'status':'PASS','policy_source':'lab','comparison':{'absolute_delta_mm':.5}},
   'repeatability':{'schema':SCHEMAS['repeatability'],'status':'PASS','policy_source':'lab','summary':{'artifact_count':2}},
  };paths={}
  for k,v in docs.items():p=root/f'{k}.json';p.write_text(json.dumps(v));paths[k]=p
  text=render(paths);assert 'Stereo calibration evidence report' in text and '0.080000' in text
 print('Stereo calibration human-report renderer self-test: PASS')
def main(argv:Sequence[str]|None=None)->int:
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--self-test',action='store_true')
 for k in SCHEMAS:p.add_argument('--'+k.replace('_','-'),dest=k,type=Path)
 p.add_argument('--output',type=Path);a=p.parse_args(argv)
 if a.self_test:self_test();return 0
 paths={k:getattr(a,k) for k in SCHEMAS}
 if any(v is None for v in paths.values()) or a.output is None:raise ReportError('all evidence inputs and --output are required')
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(render(paths),encoding='utf-8');print(a.output);return 0
if __name__=='__main__':
 try:raise SystemExit(main())
 except ReportError as e:print(f'error: {e}',file=__import__('sys').stderr);raise SystemExit(2)
