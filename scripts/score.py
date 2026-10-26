#!/usr/bin/env python3
"""V1.1 reproducible offline scoring. An independent, explicitly UNVERIFIED
port of V4.13.1; never misrepresent as byte-for-byte browser-score parity.
Uses existing immutable source JSONs; outputs separate provenance-linked scores.
No network required. Python standard library only.
"""
import argparse, datetime as dt, hashlib, json, math
from pathlib import Path

VERSION='offline-port-v1.1.0 (V4.13.1 logic; parity not certified)'
LV={'ecmwf':[1000,925,850,700,600,500], 'gfs':[1000,975,950,925,900,875,850,825,800,775,750,725,700,675,650,625,600,575,550,525,500]}

def ok(x): return type(x) in (int,float) and math.isfinite(x)
def avg(xs):
 v=[x for x in xs if ok(x)]
 return sum(v)/len(v) if v else None
def clamp(x): return min(100,max(0,x))
def jsround(x): return math.floor(x+0.5)
def by_time(d,day,hour):
 if not d:return None
 a=d.get('hourly',{});t=a.get('time',[])
 try:return t.index(f'{day}T{hour:02d}:00')
 except ValueError:return None
def val(d,key,i):
 if d is None or i is None:return None
 v=d.get('hourly',{}).get(key)
 return v[i] if isinstance(v,list) and i<len(v) and ok(v[i]) else None

def sunrise_local_approx(day,lat,lon):
 """NOAA approximate sunrise at horizon -0.833°. Only for window selection.
 Distinct from API's daily.sunrise, preserve method/version metadata.
 """
 date=dt.date.fromisoformat(day);n=date.timetuple().tm_yday
 lng_hour=lon/15.0;t=n+(6-lng_hour)/24.0
 m=(0.9856*t)-3.289
 L=(m+1.916*math.sin(math.radians(m))+0.020*math.sin(math.radians(2*m))+282.634)%360
 ra=(math.degrees(math.atan(0.91764*math.tan(math.radians(L))))%360)
 ra+=(math.floor(L/90)*90-math.floor(ra/90)*90);ra/=15
 sd=0.39782*math.sin(math.radians(L));cd=math.cos(math.asin(sd))
 cosh=(math.cos(math.radians(90.833))-(sd*math.sin(math.radians(lat))))/(cd*math.cos(math.radians(lat)))
 if abs(cosh)>1:return None
 h=(360-math.degrees(math.acos(cosh)))/15
 T=h+ra-(0.06571*t)-6.622
 utc=(T-lng_hour)%24
 minutes=int(round((utc+8)%24*60))%1440
 return f'{day}T{minutes//60:02d}:{minutes%60:02d}'

def interp(pts,h):
 for a,b in zip(pts,pts[1:]):
  gap=b['h']-a['h']
  if a['h']<=h<=b['h'] and 0<gap<=900 and ok(a['rh']) and ok(b['rh']):return a['rh']+(b['rh']-a['rh'])*(h-a['h'])/gap
 return None

def profiles(ds,day,h):
 out=[]
 for key in ['ecmwf','gfs']:
  d=ds.get(key+'_vertical',{}).get('data')
  if not d:continue
  i=by_time(d,day,5)
  ground=d.get('elevation');pts=[]
  for p in LV[key]:
   z=val(d,f'geopotential_height_{p}hPa',i);t=val(d,f'temperature_{p}hPa',i);rh=val(d,f'relative_humidity_{p}hPa',i)
   if ok(z) and ok(t) and -500<=z<=35000 and -100<=t<=65 and (not ok(ground) or z>=ground):pts.append({'h':z,'t':t,'rh':rh})
  pts.sort(key=lambda x:x['h'])
  if len(pts)<2:continue
  inside=any(a['h']<=h<=b['h'] and b['h']-a['h']>20 and b['t']-a['t']>0.2 for a,b in zip(pts,pts[1:]))
  out.append({'name':key.upper(),'inside':inside,'at':interp(pts,h),'below':interp(pts,h-300),'above':interp(pts,h+300)})
 return out

def evidence(ds,day):
 out=[]
 for key in ('ecmwf','gfs'):
  d=ds.get(key+'_vertical',{}).get('data')
  if not d:continue
  ground=d.get('elevation');times=[]
  for hour in (4,5,6,7,8):
   i=by_time(d,day,hour);rows=[]
   for p in LV[key]:
    z=val(d,f'geopotential_height_{p}hPa',i);cloud=val(d,f'cloud_cover_{p}hPa',i)
    rows.append({'h':z,'cloud':cloud if ok(z) and (not ok(ground) or z>=ground) else None})
   times.append({'hour':hour,'rows':rows})
  out.append({'name':key.upper(),'hourly':times,'rows':times[1]['rows']})
 return out

def daily_surface(ds,day):
 d=ds.get('composite_surface',{}).get('data');hr=range(4,9)
 def mean(k):return avg([val(d,k,by_time(d,day,i)) for i in hr])
 return {'rh':mean('relative_humidity_2m'),'low':mean('cloud_cover_low'),'wind':mean('wind_speed_10m')}

def formation(p,surf,cloud,h):
 nearvals=[x['at'] for x in p if ok(x['at'])];belowvals=[x['below'] for x in p if ok(x['below'])];parts=[]
 def add(name,w,v):
  if ok(v):parts.append({'name':name,'weight':w,'value':clamp(v)})
 if belowvals:
  lower=max(belowvals); near_dry=min(nearvals) if nearvals else None
  hum=clamp((lower-45)*1.8)
  if ok(near_dry) and lower-near_dry>=20:hum=clamp(hum+8)
  add('低层水汽',35,hum)
 elif ok(surf['rh']):add('低层水汽（近地面替代）',15,(surf['rh']-45)*1.8)
 if p:
  invcount=sum(bool(x['inside']) for x in p)
  add('逆温稳定度',25,85 if invcount==2 else 65 if invcount==1 else 30)
 # Browser prefers GFS if present; else ECMWF.
 g=next((x for x in cloud if x['name']=='GFS'),None) or next(iter(cloud),None)
 if g:
  near=[r['cloud'] for r in g['rows'] if ok(r['h']) and ok(r['cloud']) and abs(r['h']-h)<=450]
  below=[r['cloud'] for r in g['rows'] if ok(r['h']) and ok(r['cloud']) and h-1200<=r['h']<h-150]
  if near or below:
   nc=max(near) if near else None;bc=max(below) if below else None
   score=clamp(bc*1.15) if ok(bc) else clamp(nc*.6) if ok(nc) else None
   if ok(bc) and ok(nc) and bc>nc+20:score=clamp(score+10)
   add('逐层低云',25,score)
 if not any(x['name']=='逐层低云' for x in parts) and ok(surf['low']):add('低云总量',25,surf['low']*1.1)
 if ok(surf['wind']):add('风速条件',15,85 if surf['wind']<=10 else 65 if surf['wind']<=20 else 35 if surf['wind']<=30 else 10)
 total=sum(x['weight'] for x in parts)
 score=jsround(sum(x['weight']*x['value'] for x in parts)/total) if len(parts)>=2 and total>=40 else None
 return {'score':score,'factors':parts,'available_weight':total}

def rain_cap(ds,day,sunrise):
 # Browser hourly precipitation is *preceding* hour, so retain intervals overlap test.
 cap=None;wet=[];usable=0;sun=None
 if sunrise:sun=dt.datetime.fromisoformat(sunrise)
 for key in ('ecmwf','gfs'):
  d=ds.get(key+'_surface',{}).get('data')
  nums=[]
  for hour in range(24):
   v=val(d,'precipitation',by_time(d,day,hour))
   if not ok(v):continue
   if sun:
    stamp=dt.datetime.fromisoformat(f'{day}T{hour:02d}:00')
    flag=stamp>sun-dt.timedelta(minutes=30) and stamp-dt.timedelta(hours=1)<sun+dt.timedelta(minutes=60)
   else:flag=6<=hour<=8
   if flag:nums.append(v)
  if nums:usable+=1;wet.append(max(nums))
 if usable==2:
  if all(v>=.5 for v in wet):cap=30
  elif all(v>=.2 for v in wet):cap=45
  elif sum(v>=.2 for v in wet)==1:cap=65
 return {'cap':cap,'modes_available':usable,'maximums_mm':wet}

def vis_min(ds,day,sunrise):
 d=ds.get('composite_surface',{}).get('data');sun=dt.datetime.fromisoformat(sunrise) if sunrise else None;arr=[]
 for hour in range(24):
  v=val(d,'visibility',by_time(d,day,hour))
  if not ok(v):continue
  ts=dt.datetime.fromisoformat(f'{day}T{hour:02d}:00')
  if (sun and abs((ts-sun).total_seconds())<=5400) or (not sun and 5<=hour<=8):arr.append(v)
 return min(arr) if arr else None

def watchability(e,evi,h,visibility,rain):
 base=e['score']
 if base is None:return {'score':None,'title':'核心预报缺失','near':None,'below':None,'factor':None}
 ss=[]
 for m in evi:
  ns=[];bs=[]
  for t in m['hourly']:
   near=[r['cloud'] for r in t['rows'] if ok(r['h']) and ok(r['cloud']) and abs(r['h']-h)<=450]
   below=[r['cloud'] for r in t['rows'] if ok(r['h']) and ok(r['cloud']) and h-1200<=r['h']<h-150]
   ns.append(max(near) if near else None);bs.append(max(below) if below else None)
  ss.append({'name':m['name'],'near':avg(ns),'below':avg(bs)})
 def mix(key):
  d={r['name']:r[key] for r in ss if ok(r[key])}
  return .7*d['GFS']+.3*d['ECMWF'] if len(d)==2 else next(iter(d.values()),None)
 near=mix('near');below=mix('below');fac=1
 if ok(near):
  c=.48 if near>=85 else .57 if near>=70 else .73 if near>=50 else .87 if near>=30 else .94 if near>=15 else 1
  fac*=c
  if ok(below) and below>=40 and near<=20:fac=min(1,fac*1.07)
 if ok(visibility) and ok(near) and near>=60 and visibility<5000:
  fac*=.88 if visibility<1000 else .93 if visibility<3000 else .97
 score=jsround(clamp(base*fac))
 if ok(rain['cap']):score=min(score,rain['cap'])
 wash=ok(near) and near>=65 and ((ok(visibility) and visibility<3000) or near>=85)
 title='山顶洗头风险偏高' if wash else '观赏条件相对有利' if score>=70 else '有机会，但需复核云层位置' if score>=50 else '观赏条件偏弱' if score>=30 else '不宜仅为云海专程出发'
 return {'score':score,'title':title,'near':near,'below':below,'factor':fac}

def score_archive(path, output):
 raw=path.read_bytes();data=json.loads(raw);ds=data['datasets'];site=data['site'];h=site['altitude_m'];results=[]
 start,end=data['forecast_target_dates'];day=dt.date.fromisoformat(start);last=dt.date.fromisoformat(end)
 while day<=last:
  d=day.isoformat();sun=sunrise_local_approx(d,site['lat'],site['lon'])
  p=profiles(ds,d,h);evi=evidence(ds,d);surface=daily_surface(ds,d)
  e=formation(p,surface,evi,h);rain=rain_cap(ds,d,sun);visibility=vis_min(ds,d,sun)
  w=watchability(e,evi,h,visibility,rain)
  results.append({'target_date':d,'window':'04:00-08:00 Asia/Shanghai', 'sunrise_used':sun,
   'formation_index':e['score'],'viewability_index':w['score'],'risk_title':w['title'],
   'formation_factors':e['factors'],'formation_available_weight':e['available_weight'],
   'near_viewpoint_cloud_pct':w['near'],'below_viewpoint_cloud_pct':w['below'],
   'visibility_grid_min_m':visibility,'rain':rain,'cloud_discount_factor':w['factor'],
   'profile_models_available':len(p),'cloud_models_available':len(evi),'composite_inputs':surface})
  day+=dt.timedelta(days=1)
 result={'schema':'cloudsea-offline-score-v1', 'scoring_version':VERSION,
  'algorithm_source':'V4.13 base logic + V4.13.1 below-terrain filtering',
  'parity_with_live_web':'NOT_YET_CERTIFIED; browser sunrise and raw API request timing can differ',
  'sunrise_method':'NOAA approximate algorithm (not Open-Meteo daily.sunrise; archive did not record sunrise)',
  'source_snapshot':str(path.as_posix()),'source_sha256':hashlib.sha256(raw).hexdigest(),
  'source_capture_beijing':data['capture_beijing'],'site':site,
  'scored_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
  'scores_are_probabilities':False,'daily_results':results}
 dest=output/path.relative_to('snapshots');dest.parent.mkdir(parents=True,exist_ok=True);dest=dest.with_suffix('.scores.json')
 if dest.exists():
  old=json.loads(dest.read_text(encoding='utf8'))
  if old.get('source_sha256')!=result['source_sha256'] or old.get('scoring_version')!=VERSION:raise RuntimeError('existing score conflict: '+str(dest))
  print('SKIP immutable score:',dest);return
 with dest.open('x',encoding='utf8') as f:json.dump(result,f,ensure_ascii=False,indent=2);f.write('\n')
 print('SCORED:',dest,'targets:',len(results))

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--input',default='snapshots');ap.add_argument('--output',default='scores');args=ap.parse_args()
 paths=sorted(Path(args.input).rglob('*.json'))
 if not paths:raise SystemExit('No snapshots found; run collector first')
 for p in paths:score_archive(p,Path(args.output))
if __name__=='__main__':main()
