#!/usr/bin/env python3
"""OpenCV solve/rectification helpers for stereo_calibration_workbench.py."""
from stereo_calibration_common import *

def collect(s,sp,t,pairs,cv2,np):
 if t['family']!='charuco':raise Error('native solve currently supports ChArUco')
 b=board(cv2,t);obj=board_pts(b,np);mono={c:{'o':[],'i':[]} for c in CAMS};st=[]
 for meta,pa,pb in pairs:
  d={}
  for cam,p in [('camera_a',pa),('camera_b',pb)]:
   im=cv2.imread(str(p),cv2.IMREAD_GRAYSCALE);q,ids=detect(im,b,cv2,np);d[cam]=(q,ids)
   if len(ids)>=4:mono[cam]['o'].append(np.asarray([obj[k] for k in ids],np.float32));mono[cam]['i'].append(np.asarray(q,np.float32).reshape(-1,1,2))
  common=sorted(set(d['camera_a'][1])&set(d['camera_b'][1]))
  if len(common)>=4:
   ia={v:i for i,v in enumerate(d['camera_a'][1])};ib={v:i for i,v in enumerate(d['camera_b'][1])};st.append((np.asarray([obj[k] for k in common],np.float32),np.asarray([d['camera_a'][0][ia[k]] for k in common],np.float32).reshape(-1,1,2),np.asarray([d['camera_b'][0][ib[k]] for k in common],np.float32).reshape(-1,1,2)))
 return mono,st
def solve_core(cv2,np,size,mono,st,flags=0):
 m={}
 for cam in CAMS:
  if len(mono[cam]['o'])<3:raise Error(f'{cam}: need >=3 views')
  rms,K,D,r,t=cv2.calibrateCamera(mono[cam]['o'],mono[cam]['i'],size,None,None,flags=flags);per=[]
  for o,i,rv,tv in zip(mono[cam]['o'],mono[cam]['i'],r,t):p,_=cv2.projectPoints(o,rv,tv,K,D);e=i.reshape(-1,2)-p.reshape(-1,2);per.append(float(np.sqrt(np.mean(np.sum(e*e,axis=1)))))
  m[cam]=(float(rms),K,D,per)
 if len(st)<3:raise Error('need >=3 stereo views with common corners')
 sr,K1,D1,K2,D2,R,T,E,F=cv2.stereoCalibrate([x[0] for x in st],[x[1] for x in st],[x[2] for x in st],m['camera_a'][1],m['camera_a'][2],m['camera_b'][1],m['camera_b'][2],size,criteria=(cv2.TERM_CRITERIA_EPS+cv2.TERM_CRITERIA_COUNT,100,1e-7),flags=cv2.CALIB_FIX_INTRINSIC)
 R1,R2,P1,P2,Q,roi1,roi2=cv2.stereoRectify(K1,D1,K2,D2,size,R,T,flags=cv2.CALIB_ZERO_DISPARITY,alpha=-1);res=[]
 for _,a,b in st:
  aa=cv2.undistortPoints(a,K1,D1,R=R1,P=P1).reshape(-1,2);bb=cv2.undistortPoints(b,K2,D2,R=R2,P=P2).reshape(-1,2);res += [abs(float(x)-float(y)) for x,y in zip(aa[:,1],bb[:,1])]
 return m,(float(sr),K1,D1,K2,D2,R,T,E,F),(R1,R2,P1,P2,Q,list(map(int,roi1)),list(map(int,roi2))),res
def mat(x):return [[float(v) for v in r] for r in x.tolist()]
def vec(x):return [float(v) for v in x.reshape(-1).tolist()]
def rot_ok(r,tol=1e-5):
 if not isinstance(r,list) or len(r)!=3 or any(len(x)!=3 for x in r):return False
 for i in range(3):
  for j in range(3):
   if abs(sum(float(r[k][i])*float(r[k][j]) for k in range(3))-(1. if i==j else 0.))>tol:return False
 d=r[0][0]*(r[1][1]*r[2][2]-r[1][2]*r[2][1])-r[0][1]*(r[1][0]*r[2][2]-r[1][2]*r[2][0])+r[0][2]*(r[1][0]*r[2][1]-r[1][1]*r[2][0]);return abs(d-1.)<=tol
def validate(d):
 e=[]
 if d.get('schema')!=CALIB:e.append(f'schema must be {CALIB}')
 for cam in CAMS:
  c=d.get('cameras',{}).get(cam,{});K=c.get('K');D=c.get('D')
  if not isinstance(K,list) or len(K)!=3 or any(not isinstance(r,list) or len(r)!=3 for r in K) or float(K[0][0])<=0 or float(K[1][1])<=0:e.append(f'{cam}.K invalid')
  if not isinstance(D,list) or not D:e.append(f'{cam}.D invalid')
 s=d.get('stereo',{});T=s.get('T_camera_b_from_camera_a_m')
 if not rot_ok(s.get('R_camera_b_from_camera_a')):e.append('stereo rotation invalid')
 if not isinstance(T,list) or len(T)!=3 or math.sqrt(sum(float(x)**2 for x in T))<=0:e.append('stereo translation invalid')
 r=d.get('rectification',{})
 for k,n,m in [('R1',3,3),('R2',3,3),('P1',3,4),('P2',3,4),('Q',4,4)]:
  x=r.get(k)
  if not isinstance(x,list) or len(x)!=n or any(len(y)!=m for y in x):e.append(f'{k} invalid')
 if d.get('provenance',{}).get('kind') not in ('synthetic','measured','imported'):e.append('provenance.kind invalid')
 return e
def solve_cmd(a):
 cv2,np=cv();sp=a.session.resolve();s,tp,t,pairs=verified_session(sp);size=(s['capture']['width'],s['capture']['height']);mono,st=collect(s,sp,t,pairs,cv2,np);flags=cv2.CALIB_RATIONAL_MODEL if a.distortion_model=='opencv-rational' else 0;m,z,r,res=solve_core(cv2,np,size,mono,st,flags);sr,K1,D1,K2,D2,R,T,E,F=z;R1,R2,P1,P2,Q,roi1,roi2=r;base=float(np.linalg.norm(T));g={}
 d={'schema':CALIB,'calibration_id':a.calibration_id,'created_utc':now(),'provenance':{'kind':a.provenance,'tool':Path(__file__).name,'tool_version':VERSION,'opencv_version':cv2.__version__,'source_session_path':str(sp),'source_session_sha256':sha(sp)},'device':s['device'],'capture':s['capture'],'image':{'width':size[0],'height':size[1]},'target':{'target_id':t['target_id'],'family':t['family'],'path':str(tp),'sha256':sha(tp)},'camera_model':{'projection':'pinhole','distortion':a.distortion_model},'cameras':{'camera_a':{'K':mat(K1),'D':vec(D1),'mono_rms_px':m['camera_a'][0],'per_view_reprojection_rms_px':m['camera_a'][3],'pinhole_fov_deg':{'x':math.degrees(2*math.atan(size[0]/(2*float(K1[0,0])))),'y':math.degrees(2*math.atan(size[1]/(2*float(K1[1,1]))))}},'camera_b':{'K':mat(K2),'D':vec(D2),'mono_rms_px':m['camera_b'][0],'per_view_reprojection_rms_px':m['camera_b'][3],'pinhole_fov_deg':{'x':math.degrees(2*math.atan(size[0]/(2*float(K2[0,0])))),'y':math.degrees(2*math.atan(size[1]/(2*float(K2[1,1]))))}}},'stereo':{'frame_convention':'R/T transform points from camera_a into camera_b','R_camera_b_from_camera_a':mat(R),'T_camera_b_from_camera_a_m':vec(T),'baseline_m':base,'E':mat(E),'F':mat(F),'stereo_rms_px':sr,'valid_pair_count':len(st)},'rectification':{'R1':mat(R1),'R2':mat(R2),'P1':mat(P1),'P2':mat(P2),'Q':mat(Q),'valid_roi_camera_a':roi1,'valid_roi_camera_b':roi2,'vertical_epipolar_abs_px':dist(res)},'quality':{'gates':{},'policy_source':a.policy_source,'status':'EVIDENCE_ONLY_NO_THRESHOLDS'},'guardrails':['camera_a/camera_b naming preserved until #35 mapping evidence exists.','Vendor nominal FOV/baseline are not solver inputs.','Low global RMS alone is not promotion evidence.']}
 if a.max_mono_rms_px is not None:
  for cam in CAMS:o=d['cameras'][cam]['mono_rms_px'];g[f'{cam}_max_mono_rms_px']={'limit':a.max_mono_rms_px,'observed':o,'pass':o<=a.max_mono_rms_px}
 if a.max_stereo_rms_px is not None:g['max_stereo_rms_px']={'limit':a.max_stereo_rms_px,'observed':sr,'pass':sr<=a.max_stereo_rms_px}
 if a.max_epipolar_p95_px is not None:o=d['rectification']['vertical_epipolar_abs_px']['p95'] or 0.;g['max_vertical_epipolar_p95_px']={'limit':a.max_epipolar_p95_px,'observed':o,'pass':o<=a.max_epipolar_p95_px}
 if g:
  if not a.policy_source:raise Error('explicit calibration gates require --policy-source')
  d['quality']={'gates':g,'policy_source':a.policy_source,'status':'PASS' if all(x['pass'] for x in g.values()) else 'FAIL'}
 e=validate(d)
 if e:raise Error('generated artifact invalid: '+'; '.join(e))
 save(a.output,d)
def rectify_cmd(a):
 cv2,np=cv();d=load(a.calibration.resolve());e=validate(d)
 if e:raise Error('; '.join(e))
 A=cv2.imread(str(a.camera_a.resolve()));B=cv2.imread(str(a.camera_b.resolve()));w,h=d['image']['width'],d['image']['height']
 if A is None or B is None or (A.shape[1],A.shape[0])!=(w,h) or (B.shape[1],B.shape[0])!=(w,h):raise Error('rectification input geometry mismatch')
 n=lambda x:np.asarray(x,np.float64);K1=n(d['cameras']['camera_a']['K']);D1=n(d['cameras']['camera_a']['D']);K2=n(d['cameras']['camera_b']['K']);D2=n(d['cameras']['camera_b']['D']);R1=n(d['rectification']['R1']);R2=n(d['rectification']['R2']);P1=n(d['rectification']['P1']);P2=n(d['rectification']['P2']);m1x,m1y=cv2.initUndistortRectifyMap(K1,D1,R1,P1,(w,h),cv2.CV_32FC1);m2x,m2y=cv2.initUndistortRectifyMap(K2,D2,R2,P2,(w,h),cv2.CV_32FC1);canvas=np.hstack([cv2.remap(A,m1x,m1y,cv2.INTER_LINEAR),cv2.remap(B,m2x,m2y,cv2.INTER_LINEAR)])
 for y in range(max(20,a.line_spacing_px)//2,h,max(20,a.line_spacing_px)):cv2.line(canvas,(0,y),(canvas.shape[1]-1,y),(0,255,0),1)
 a.output.parent.mkdir(parents=True,exist_ok=True)
 if not cv2.imwrite(str(a.output),canvas):raise Error(f'cannot write {a.output}')
