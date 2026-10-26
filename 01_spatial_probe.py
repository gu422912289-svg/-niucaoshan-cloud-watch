#!/usr/bin/env python3
"""Cloud-sea spatial diagnostic EXPERIMENT; does not change V1.1 scores.

Samples a small fixed coordinate grid near the user's selected summit.
Requested coordinates are NOT asserted to be verified valleys or Langguangling.
The Open-Meteo grid cell can be kilometers away from the requested point;
always store both and separately count distinct model grid coordinates.
"""
import argparse
import datetime as dt
import json
import math
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

TZ = dt.timezone(dt.timedelta(hours=8))
SITES = {
    'taizijian': {'name':'太子尖','lat':30.1756,'lon':118.8997,'view_m':1557},
    'niucaoshan': {'name':'牛草山','lat':31.044687,'lon':116.265979,'view_m':1350},
}
MODELS = {
    'composite':('https://api.open-meteo.com/v1/forecast',None),
    'ecmwf':('https://api.open-meteo.com/v1/ecmwf','ecmwf_ifs025'),
    'gfs':('https://api.open-meteo.com/v1/gfs','gfs_global'),
}
HOURLY = 'relative_humidity_2m,temperature_2m,dew_point_2m,cloud_cover_low,cloud_cover,wind_speed_10m,precipitation'
SPACING_KM = 5.0
# This is a neutral diagnostic grid, not a topographically verified valley network.
OFFSETS = [('center',0,0),('N',5,0),('NE',5,5),('E',0,5),('SE',-5,5),('S',-5,0),('SW',-5,-5),('W',0,-5),('NW',5,-5)]

def stamp():return dt.datetime.now(TZ).isoformat(timespec='seconds')
def request(url):
    last=None
    for attempt in range(3):
        try:
            req=Request(url,headers={'User-Agent':'CloudSeaSpatialResearch/0.1','Accept':'application/json'})
            with urlopen(req,timeout=40) as response: data=json.load(response)
            if data.get('error'):raise ValueError(data.get('reason','Open-Meteo error'))
            return data,None
        except Exception as e:
            last=f'{type(e).__name__}: {e}'
            if attempt<2:time.sleep(2**attempt)
    return None,last

def point(site, north_km, east_km):
    lat=site['lat']+north_km/111.195
    lon=site['lon']+east_km/(111.195*math.cos(math.radians(site['lat'])))
    return {'lat':round(lat,6),'lon':round(lon,6),'offset_north_km':north_km,'offset_east_km':east_km}

def url_for(base,model,p,start,end):
    q={'latitude':p['lat'],'longitude':p['lon'],'timezone':'Asia/Shanghai',
       'start_date':start,'end_date':end,'hourly':HOURLY,
       'cell_selection':'land'}
    if model:q['models']=model
    return base+'?'+urlencode(q)

def slim(data,start,end):
    h=data.get('hourly') or {}
    times=h.get('time') or []
    indexes=[i for i,t in enumerate(times) if start<=t[:10]<=end and 3<=int(t[11:13])<=9]
    if not indexes:raise ValueError('no hourly values between 03:00 and 09:00')
    return {'grid_lat':data.get('latitude'),'grid_lon':data.get('longitude'),
            'grid_elevation_m':data.get('elevation'),
            'hourly_units':data.get('hourly_units'),
            'hourly':{k:[values[i] if i<len(values) else None for i in indexes] for k,values in h.items() if isinstance(values,list)},
            'time_zone':data.get('timezone')}

def numeric(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)

def summaries(model_records, dates):
    bydate=[]
    for day in dates:
        daily={'date':day,'model_comparison':{}}
        for model in MODELS:
            rows=[]
            cell_set=set()
            for label,rec in model_records.items():
                d=rec.get(model,{}).get('data')
                if not d:continue
                center=(d['grid_lat'],d['grid_lon'])
                cell_set.add(center)
                h=d['hourly'];ids=[i for i,t in enumerate(h['time']) if t.startswith(day+'T') and 4<=int(t[11:13])<=8]
                if not ids:continue
                vals=lambda key:[h.get(key,[])[i] for i in ids if i<len(h.get(key,[])) and numeric(h[key][i])]
                lows=vals('cloud_cover_low');rhs=vals('relative_humidity_2m');temps=vals('temperature_2m');dew=vals('dew_point_2m')
                rows.append({'requested_point':label,'actual_grid_center':center,'returned_elevation_m':d['grid_elevation_m'],
                             'low_cloud_mean_pct':round(sum(lows)/len(lows),1) if lows else None,
                             'rh_mean_pct':round(sum(rhs)/len(rhs),1) if rhs else None,
                             'dewpoint_spread_mean_c':round(sum(t-x for t,x in zip(temps,dew))/len(temps),2) if len(temps)==len(dew) and temps else None,
                             'is_center':label=='center'})
            daily['model_comparison'][model]={'distinct_grid_centers':len(cell_set),'point_rows':rows,
                       'interpretation_note':'No valley cloud top inferred; low cloud is a modeled grid value, not observed sea-of-clouds.'}
        bydate.append(daily)
    return bydate

def run(out,site_key,days,dry_run=False):
    site=SITES[site_key]
    now=dt.datetime.now(TZ)
    start=now.date().isoformat();end=(now.date()+dt.timedelta(days=days-1)).isoformat()
    dates=[(now.date()+dt.timedelta(days=i)).isoformat() for i in range(days)]
    points={label:point(site,n,e) for label,n,e in OFFSETS}
    snapshot={'schema':'cloudsea-spatial-research-v0.1','capture_beijing':stamp(),'location':site_key,
              'summit':site,'sampling_rule':'9 point 5-km compass cross/ring; not verified valleys',
              'model_grid_selection':'land; may select distant grid cell with similar DEM elevation',
              'dates':dates,'point_requests':points,'records':{},'research_warnings':[
                  'This experiment is not a predictor or a valid replacement for V1.1.',
                  'Do not claim any sample as Langguangling or a specific valley before coordinate/terrain verification.',
                  'Requested sample coordinates, model grid centers, and terrain elevation are distinct concepts.',
                  'Same model grid center appearing at multiple points is not independent evidence.',
                  'Predictions from this capture must not be described as earlier forecast runs.' ]}
    ok=0;failed=0
    for label,p in points.items():
        snapshot['records'][label]={}
        for model,(base,model_id) in MODELS.items():
            url=url_for(base,model_id,p,start,end)
            if dry_run:
                print(label,model,url);continue
            data,error=request(url)
            if data:
                try:data=slim(data,start,end)
                except Exception as exc:error=str(exc);data=None
            snapshot['records'][label][model]={'requested_url':url,'captured_beijing':stamp(),'data':data,'error':error}
            ok+=data is not None;failed+=data is None
            print(f'{label}/{model}: {"OK" if data is not None else error}',flush=True)
            time.sleep(.25)
    if dry_run:return 0
    snapshot['source_success_count']=ok;snapshot['source_failure_count']=failed
    snapshot['summaries']=summaries(snapshot['records'],dates)
    dest=Path(out)/site_key/now.strftime('%Y-%m')
    dest.mkdir(parents=True,exist_ok=True)
    filename=now.strftime('%Y%m%dT%H%M%S%z')+'_'+site_key+'_spatial_v0_1.json'
    path=dest/filename
    with path.open('x',encoding='utf8') as f:json.dump(snapshot,f,ensure_ascii=False,indent=2);f.write('\n')
    print('Saved:',path,'Successful sources:',ok,'Failed sources:',failed,flush=True)
    return 0 if failed==0 and ok>0 else 2

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--out',default='research/spatial')
    ap.add_argument('--site',choices=list(SITES),default='taizijian')
    ap.add_argument('--days',type=int,default=4)
    ap.add_argument('--dry-run',action='store_true')
    a=ap.parse_args()
    if not 1<=a.days<=7:ap.error('days must be 1..7')
    sys.exit(run(a.out,a.site,a.days,a.dry_run))
if __name__=='__main__':main()
