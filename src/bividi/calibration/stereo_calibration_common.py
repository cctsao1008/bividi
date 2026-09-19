#!/usr/bin/env python3
"""Offline stereo calibration workbench for Bividi #8.

Contract/session validation is dependency-free. ChArUco rendering/detection,
solving and rectification require Python OpenCV + NumPy. camera_a/camera_b names
are preserved until #35 proves physical left/right identity.
"""
from __future__ import annotations
import argparse,csv,datetime as dt,hashlib,json,math,os,statistics
from pathlib import Path

TARGET='bividi.calibration.stereo_target.v1'; SESSION='bividi.calibration.stereo_session.v1'; QUALITY='bividi.calibration.stereo_dataset_quality.v1'; CALIB='bividi.calibration.stereo.v1'; VERSION='1'; CAMS=('camera_a','camera_b')
class Error(ValueError):pass
def now():return dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00','Z')
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for c in iter(lambda:f.read(1024*1024),b''):h.update(c)
 return h.hexdigest()
def load(p):
 try:v=json.loads(p.read_text(encoding='utf-8'))
 except (OSError,json.JSONDecodeError) as e:raise Error(f'cannot read {p}: {e}') from e
 if not isinstance(v,dict):raise Error(f'{p}: expected JSON object')
 return v
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,indent=2)+'\n',encoding='utf-8')
def resolve(owner,text):
 p=Path(text);return p if p.is_absolute() else (owner.parent/p).resolve()
def rel(p,owner):
 try:return os.path.relpath(p.resolve(),owner.parent.resolve()).replace(os.sep,'/')
 except ValueError:return str(p.resolve()).replace(os.sep,'/')
def pctile(a,q):
 if not a:return None
 x=sorted(map(float,a));z=(len(x)-1)*q;i=int(math.floor(z));j=int(math.ceil(z));return x[i] if i==j else x[i]*(j-z)+x[j]*(z-i)
def dist(a):
 x=[float(v) for v in a if math.isfinite(float(v))]
 return {'count':len(x),'min':min(x) if x else None,'max':max(x) if x else None,'mean':statistics.fmean(x) if x else None,'median':statistics.median(x) if x else None,'p95':pctile(x,.95)}
def hull(pts):
 p=sorted(set((float(x),float(y)) for x,y in pts))
 if len(p)<=1:return p
 def cross(o,a,b):return (a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0])
 lo=[];hi=[]
 for x in p:
  while len(lo)>=2 and cross(lo[-2],lo[-1],x)<=0:lo.pop()
  lo.append(x)
 for x in reversed(p):
  while len(hi)>=2 and cross(hi[-2],hi[-1],x)<=0:hi.pop()
  hi.append(x)
 return lo[:-1]+hi[:-1]
def area(p):return 0.0 if len(p)<3 else abs(sum(p[i][0]*p[(i+1)%len(p)][1]-p[(i+1)%len(p)][0]*p[i][1] for i in range(len(p))))*.5
def coverage(pts,w,h):return 0.0 if len(pts)<3 or w<2 or h<2 else area(hull([(p[0]/(w-1),p[1]/(h-1)) for p in pts]))
def cv():
 try:import cv2;import numpy as np
 except ImportError as e:raise Error('this command requires Python OpenCV (cv2) and NumPy') from e
 return cv2,np
def board(cv2,t):
 c=t['charuco'];name=c['dictionary']
 if not hasattr(cv2.aruco,name):raise Error(f'unknown OpenCV aruco dictionary {name}')
 d=cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco,name));sz=(int(c['squares_x']),int(c['squares_y']));sq=c['square_length_mm']/1000.;mk=c['marker_length_mm']/1000.
 # OpenCV 4.6 exposes CharucoBoard but its Python constructor can crash for
 # the newer tuple-shaped signature. Prefer the stable legacy global factory
 # whenever it exists; newer OpenCV releases removed that factory and use the
 # constructor safely.
 if hasattr(cv2.aruco,'CharucoBoard_create'):
  return cv2.aruco.CharucoBoard_create(sz[0],sz[1],sq,mk,d)
 if hasattr(cv2.aruco,'CharucoBoard'):
  try:return cv2.aruco.CharucoBoard(sz,sq,mk,d)
  except TypeError:return cv2.aruco.CharucoBoard.create(sz[0],sz[1],sq,mk,d)
 raise Error('OpenCV aruco module does not provide a ChArUco board factory')
def board_pts(b,np):return np.asarray(b.getChessboardCorners() if hasattr(b,'getChessboardCorners') else b.chessboardCorners,dtype=np.float32).reshape(-1,3)
def detect(gray,b,cv2,np):
 if hasattr(cv2.aruco,'CharucoDetector'):c,i,_,_=cv2.aruco.CharucoDetector(b).detectBoard(gray)
 else:
  d=b.getDictionary() if hasattr(b,'getDictionary') else b.dictionary;m,mi,_=cv2.aruco.detectMarkers(gray,d)
  if mi is None:return [],[]
  _,c,i=cv2.aruco.interpolateCornersCharuco(m,mi,gray,b)
 if c is None or i is None:return [],[]
 c=np.asarray(c).reshape(-1,2);i=np.asarray(i).reshape(-1);return [[float(x),float(y)] for x,y in c],[int(x) for x in i]
def target_cmd(a):
 d={'schema':TARGET,'target_id':a.target_id,'family':a.family,'created_utc':now(),'physical_units':'millimetres','provenance':{'tool':Path(__file__).name,'tool_version':VERSION},'print_scale_verification':{'status':'UNVERIFIED','instruction':'Physically measure at least one long printed dimension before measured calibration.'}}
 if a.family=='charuco':
  if a.marker_mm>=a.square_mm:raise Error('marker length must be smaller than square length')
  d['charuco']={'dictionary':a.dictionary,'squares_x':a.squares_x,'squares_y':a.squares_y,'square_length_mm':a.square_mm,'marker_length_mm':a.marker_mm};d['physical_size_mm']={'width':a.squares_x*a.square_mm,'height':a.squares_y*a.square_mm}
 else:
  d['aprilgrid']={'tag_family':a.tag_family,'tag_rows':a.tag_rows,'tag_cols':a.tag_cols,'tag_size_mm':a.tag_size_mm,'tag_spacing_ratio':a.tag_spacing_ratio};d['physical_size_mm']={'width':a.tag_cols*a.tag_size_mm+(a.tag_cols-1)*a.tag_size_mm*a.tag_spacing_ratio,'height':a.tag_rows*a.tag_size_mm+(a.tag_rows-1)*a.tag_size_mm*a.tag_spacing_ratio}
 save(a.output,d)
 if a.render:
  if a.family!='charuco':raise Error('AprilGrid artwork stays external; use --kalibr-yaml for metadata')
  cv2,_=cv();b=board(cv2,d);im=b.generateImage((a.render_width_px,a.render_height_px),marginSize=a.render_margin_px,borderBits=1) if hasattr(b,'generateImage') else b.draw((a.render_width_px,a.render_height_px),a.render_margin_px,1);a.render.parent.mkdir(parents=True,exist_ok=True)
  if not cv2.imwrite(str(a.render),im):raise Error(f'cannot write {a.render}')
 if a.kalibr_yaml:
  if a.family!='aprilgrid':raise Error('--kalibr-yaml requires AprilGrid')
  c=d['aprilgrid'];a.kalibr_yaml.write_text(f"target_type: 'aprilgrid'\ntagCols: {c['tag_cols']}\ntagRows: {c['tag_rows']}\ntagSize: {c['tag_size_mm']/1000.:.12g}\ntagSpacing: {c['tag_spacing_ratio']:.12g}\n",encoding='utf-8')
def session_cmd(a):
 tp=a.target.resolve();t=load(tp)
 if t.get('schema')!=TARGET:raise Error('target schema mismatch')
 af={p.name:p for p in a.camera_a_dir.resolve().glob(a.glob) if p.is_file()};bf={p.name:p for p in a.camera_b_dir.resolve().glob(a.glob) if p.is_file()};names=sorted(set(af)&set(bf));ma=sorted(set(bf)-set(af));mb=sorted(set(af)-set(bf))
 if not names:raise Error('no matching stereo filenames')
 if (ma or mb) and not a.allow_unpaired:raise Error(f'unpaired files camera_a_missing={len(ma)} camera_b_missing={len(mb)}')
 out=a.output.resolve();pairs=[{'pair_id':f'pair-{i:06d}','camera_a':rel(af[n],out),'camera_b':rel(bf[n],out),'source_name':n} for i,n in enumerate(names)]
 save(out,{'schema':SESSION,'session_id':a.session_id,'created_utc':now(),'provenance':{'kind':a.provenance,'tool':Path(__file__).name,'tool_version':VERSION},'device':{'model':a.model,'serial':a.serial},'capture':{'device_index':a.device,'mode_index':a.mode,'pixel_format':a.pixel_format,'width':a.width,'height':a.height,'camera_a_identity':'camera_a','camera_b_identity':'camera_b','camera_mapping_evidence':a.camera_mapping_evidence},'target':{'path':rel(tp,out),'sha256':sha(tp),'target_id':t['target_id']},'pairs':pairs,'unpaired':{'camera_a_only':mb,'camera_b_only':ma}})
def verified_session(p):
 s=load(p)
 if s.get('schema')!=SESSION:raise Error(f'{p}: expected {SESSION}')
 te=s.get('target',{});tp=resolve(p,te.get('path',''))
 if not tp.is_file() or sha(tp)!=te.get('sha256'):raise Error('target file/hash mismatch')
 t=load(tp)
 if t.get('schema')!=TARGET:raise Error('target schema mismatch')
 pairs=[]
 for x in s.get('pairs',[]):
  pa,pb=resolve(p,x['camera_a']),resolve(p,x['camera_b'])
  if not pa.is_file() or not pb.is_file():raise Error(f'missing pair {pa} / {pb}')
  pairs.append((x,pa,pb))
 return s,tp,t,pairs
def inspect_cmd(a):
 cv2,np=cv();sp=a.session.resolve();s,tp,t,pairs=verified_session(sp)
 if t['family']!='charuco':raise Error('native inspection currently supports ChArUco; AprilGrid is external Kalibr reference')
 b=board(cv2,t);allp={c:[] for c in CAMS};ids={c:set() for c in CAMS};cent={c:[] for c in CAMS};rows=[]
 for meta,pa,pb in pairs:
  det={}
  for cam,p in [('camera_a',pa),('camera_b',pb)]:
   im=cv2.imread(str(p),cv2.IMREAD_GRAYSCALE)
   if im is None:raise Error(f'cannot decode {p}')
   if (im.shape[1],im.shape[0])!=(s['capture']['width'],s['capture']['height']):raise Error('image geometry differs from session')
   q,i=detect(im,b,cv2,np);sharp=float(cv2.Laplacian(im,cv2.CV_64F).var());sat=float(np.mean((im<=1)|(im>=254)));cen=[statistics.fmean(x[0] for x in q),statistics.fmean(x[1] for x in q)] if q else None
   det[cam]={'ids':i,'corner_count':len(i),'coverage_fraction':coverage(q,im.shape[1],im.shape[0]),'centroid_px':cen,'sharpness_laplacian_variance':sharp,'saturation_fraction':sat};allp[cam]+=q;ids[cam].update(i);cent[cam]+=[cen] if cen else []
  common=sorted(set(det['camera_a']['ids'])&set(det['camera_b']['ids']));rows.append({'pair_id':meta['pair_id'],'source_name':meta.get('source_name'),'camera_a':det['camera_a'],'camera_b':det['camera_b'],'common_corner_ids':common,'common_corner_count':len(common),'stereo_pair_detected':bool(det['camera_a']['ids'] and det['camera_b']['ids'])})
 ncorner=len(board_pts(b,np));cams={};w,h=s['capture']['width'],s['capture']['height']
 for cam in CAMS:
  xs=[x[0]/(w-1) for x in cent[cam]];ys=[x[1]/(h-1) for x in cent[cam]];cams[cam]={'unique_corner_ids':len(ids[cam]),'target_corner_fraction':len(ids[cam])/ncorner if ncorner else 0.,'global_image_plane_hull_fraction':coverage(allp[cam],w,h),'centroid_x_span_fraction':max(xs)-min(xs) if xs else 0.,'centroid_y_span_fraction':max(ys)-min(ys) if ys else 0.,'per_frame_coverage':dist([r[cam]['coverage_fraction'] for r in rows]),'sharpness':dist([r[cam]['sharpness_laplacian_variance'] for r in rows]),'saturation_fraction':dist([r[cam]['saturation_fraction'] for r in rows])}
 valid=sum(r['stereo_pair_detected'] and r['common_corner_count']>=4 for r in rows);g={}
 if a.min_valid_pairs is not None:g['min_valid_pairs']={'limit':a.min_valid_pairs,'observed':valid,'pass':valid>=a.min_valid_pairs}
 if a.min_common_corners is not None:
  o=dist([r['common_corner_count'] for r in rows])['median'] or 0.;g['min_median_common_corners']={'limit':a.min_common_corners,'observed':o,'pass':o>=a.min_common_corners}
 for cam in CAMS:
  if a.min_global_hull_fraction is not None:o=cams[cam]['global_image_plane_hull_fraction'];g[f'{cam}_min_global_hull_fraction']={'limit':a.min_global_hull_fraction,'observed':o,'pass':o>=a.min_global_hull_fraction}
  if a.min_sharpness is not None:o=cams[cam]['sharpness']['median'] or 0.;g[f'{cam}_min_median_sharpness']={'limit':a.min_sharpness,'observed':o,'pass':o>=a.min_sharpness}
  if a.max_saturation_fraction is not None:o=cams[cam]['saturation_fraction']['p95'] or 0.;g[f'{cam}_max_p95_saturation_fraction']={'limit':a.max_saturation_fraction,'observed':o,'pass':o<=a.max_saturation_fraction}
 if g and not a.policy_source:raise Error('explicit dataset gates require --policy-source')
 save(a.output,{'schema':QUALITY,'created_utc':now(),'session':{'path':str(sp),'sha256':sha(sp),'session_id':s['session_id']},'target':{'path':str(tp),'sha256':sha(tp),'target_id':t['target_id']},'pairs':rows,'summary':{'pair_count':len(rows),'valid_stereo_pair_count':valid,'valid_stereo_pair_fraction':valid/len(rows),'common_corner_count':dist([r['common_corner_count'] for r in rows])},'cameras':cams,'gates':g,'policy_source':a.policy_source,'status':('PASS' if all(x['pass'] for x in g.values()) else 'FAIL') if g else 'EVIDENCE_ONLY_NO_THRESHOLDS','provenance':{'tool':Path(__file__).name,'tool_version':VERSION,'opencv_version':cv2.__version__}})
