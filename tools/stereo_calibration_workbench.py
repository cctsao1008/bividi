#!/usr/bin/env python3
"""CLI entry point for the Bividi #8 stereo calibration workbench."""
import argparse
import math
from pathlib import Path
from stereo_calibration_common import *
from stereo_calibration_solve import *

def self_test():
 assert abs(coverage([[0,0],[99,0],[99,99],[0,99]],100,100)-1)<1e-12
 d={'schema':CALIB,'provenance':{'kind':'synthetic'},'cameras':{'camera_a':{'K':[[700,0,640],[0,700,360],[0,0,1]],'D':[0,0,0,0,0]},'camera_b':{'K':[[700,0,640],[0,700,360],[0,0,1]],'D':[0,0,0,0,0]}},'stereo':{'R_camera_b_from_camera_a':[[1,0,0],[0,1,0],[0,0,1]],'T_camera_b_from_camera_a_m':[-.08,0,0]},'rectification':{'R1':[[1,0,0],[0,1,0],[0,0,1]],'R2':[[1,0,0],[0,1,0],[0,0,1]],'P1':[[1,0,0,0],[0,1,0,0],[0,0,1,0]],'P2':[[1,0,0,-.08],[0,1,0,0],[0,0,1,0]],'Q':[[1,0,0,0],[0,1,0,0],[0,0,0,1],[0,0,12.5,0]]}}
 assert not validate(d);print('Stereo calibration workbench dependency-free self-test: PASS')
def self_test_cv():
 cv2,np=cv();w,h=1280,720;K=np.asarray([[760.,0,640],[0,758.,360],[0,0,1]],np.float64);D=np.zeros((5,1));base=.08;obj=np.asarray([[x*.035,y*.035,0] for y in range(5) for x in range(7)],np.float32);mono={c:{'o':[],'i':[]} for c in CAMS};st=[]
 for i in range(10):
  rv=np.asarray([[.03*math.sin(i)],[.05*math.cos(i*.7)],[.02*math.sin(i*.4)]]);tv=np.asarray([[-.10+.02*i],[-.06+.012*(i%4)],[.75+.03*(i%3)]]);Ra,_=cv2.Rodrigues(rv);tb=tv+np.asarray([[-base],[0],[0]]);rb,_=cv2.Rodrigues(Ra);pa,_=cv2.projectPoints(obj,rv,tv,K,D);pb,_=cv2.projectPoints(obj,rb,tb,K,D);pa=pa.astype(np.float32);pb=pb.astype(np.float32)
  for cam,p in [('camera_a',pa),('camera_b',pb)]:mono[cam]['o'].append(obj.copy());mono[cam]['i'].append(p)
  st.append((obj.copy(),pa,pb))
 _,z,_,res=solve_core(cv2,np,(w,h),mono,st);assert abs(float(np.linalg.norm(z[6]))-base)<2e-3;assert (pctile(res,.95) or 99)<.05;print('Stereo calibration OpenCV synthetic solver self-test: PASS')
def args(argv=None):
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--self-test',action='store_true');p.add_argument('--self-test-opencv',action='store_true');s=p.add_subparsers(dest='cmd')
 q=s.add_parser('target');q.add_argument('--family',choices=('charuco','aprilgrid'),required=True);q.add_argument('--target-id',required=True);q.add_argument('--output',type=Path,required=True);q.add_argument('--render',type=Path);q.add_argument('--render-width-px',type=int,default=2400);q.add_argument('--render-height-px',type=int,default=1600);q.add_argument('--render-margin-px',type=int,default=40);q.add_argument('--dictionary',default='DICT_5X5_1000');q.add_argument('--squares-x',type=int,default=8);q.add_argument('--squares-y',type=int,default=6);q.add_argument('--square-mm',type=float,default=30.);q.add_argument('--marker-mm',type=float,default=22.);q.add_argument('--tag-family',default='tag36h11');q.add_argument('--tag-rows',type=int,default=6);q.add_argument('--tag-cols',type=int,default=6);q.add_argument('--tag-size-mm',type=float,default=36.);q.add_argument('--tag-spacing-ratio',type=float,default=.3);q.add_argument('--kalibr-yaml',type=Path)
 q=s.add_parser('session');q.add_argument('--session-id',required=True);q.add_argument('--output',type=Path,required=True);q.add_argument('--target',type=Path,required=True);q.add_argument('--camera-a-dir',type=Path,required=True);q.add_argument('--camera-b-dir',type=Path,required=True);q.add_argument('--glob',default='*.png');q.add_argument('--allow-unpaired',action='store_true');q.add_argument('--model',required=True);q.add_argument('--serial',required=True);q.add_argument('--device',type=int,required=True);q.add_argument('--mode',type=int,required=True);q.add_argument('--pixel-format',required=True);q.add_argument('--width',type=int,required=True);q.add_argument('--height',type=int,required=True);q.add_argument('--camera-mapping-evidence');q.add_argument('--provenance',choices=('synthetic','measured','imported'),required=True)
 q=s.add_parser('inspect');q.add_argument('session',type=Path);q.add_argument('--output',type=Path,required=True);q.add_argument('--policy-source');q.add_argument('--min-valid-pairs',type=int);q.add_argument('--min-common-corners',type=float);q.add_argument('--min-global-hull-fraction',type=float);q.add_argument('--min-sharpness',type=float);q.add_argument('--max-saturation-fraction',type=float)
 q=s.add_parser('solve');q.add_argument('session',type=Path);q.add_argument('--output',type=Path,required=True);q.add_argument('--calibration-id',required=True);q.add_argument('--provenance',choices=('synthetic','measured','imported'),required=True);q.add_argument('--distortion-model',choices=('opencv5','opencv-rational'),default='opencv5');q.add_argument('--policy-source');q.add_argument('--max-mono-rms-px',type=float);q.add_argument('--max-stereo-rms-px',type=float);q.add_argument('--max-epipolar-p95-px',type=float)
 q=s.add_parser('validate');q.add_argument('artifact',type=Path)
 q=s.add_parser('rectify');q.add_argument('--calibration',type=Path,required=True);q.add_argument('--camera-a',type=Path,required=True);q.add_argument('--camera-b',type=Path,required=True);q.add_argument('--output',type=Path,required=True);q.add_argument('--line-spacing-px',type=int,default=60)
 return p.parse_args(argv)
def main(argv=None):
 a=args(argv)
 if a.self_test:self_test();return 0
 if a.self_test_opencv:self_test_cv();return 0
 if a.cmd=='target':target_cmd(a)
 elif a.cmd=='session':session_cmd(a)
 elif a.cmd=='inspect':inspect_cmd(a)
 elif a.cmd=='solve':solve_cmd(a)
 elif a.cmd=='validate':
  e=validate(load(a.artifact.resolve()));
  if e:
   for x in e:print('ERROR:',x)
   return 2
  print('Stereo calibration artifact: VALID')
 elif a.cmd=='rectify':rectify_cmd(a)
 else:raise Error('choose command or --self-test')
 return 0
if __name__=='__main__':
 try:raise SystemExit(main())
 except Error as e:print(f'error: {e}',file=__import__('sys').stderr);raise SystemExit(2)
