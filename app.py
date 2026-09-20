import os, time, threading, copy
import requests
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app, origins=[
    "https://v77cvzb7y8-blip.github.io",
    "http://localhost:*",
    "http://127.0.0.1:*"
])

UA = "AdventureBikeOS-MVP/1.00-lodging-photon-first (prototype; GitHub: v77cvzb7y8-blip/adventure-bike-os)"
session = requests.Session()
session.headers.update({"User-Agent": UA, "Accept": "application/json"})

CACHE_TTL_ROUTE = 6 * 3600
CACHE_TTL_PLACE = 24 * 3600
CACHE_TTL_TRANSPORT = 2 * 3600
_route_cache = {}
_place_cache = {}
_transport_cache = {}
_lodging_cache = {}
CACHE_TTL_LODGING = 60 * 60
SUPPLY_CACHE = {}
SUPPLY_CACHE_TTL = 30 * 60
_cache_lock = threading.Lock()
_nominatim_lock = threading.Lock()
_last_nominatim_request = 0.0

def _cache_get(store, key, ttl):
    now=time.time()
    with _cache_lock:
        item=store.get(key)
        if not item: return None
        ts,value=item
        if now-ts>ttl:
            store.pop(key,None); return None
        return copy.deepcopy(value)

def _cache_set(store, key, value):
    with _cache_lock:
        store[key]=(time.time(), copy.deepcopy(value))

def _nominatim_get(params, timeout=14):
    """Respect the public Nominatim cadence and centralise all place lookups."""
    global _last_nominatim_request
    with _nominatim_lock:
        wait=max(0.0,1.05-(time.time()-_last_nominatim_request))
        if wait: time.sleep(wait)
        r=session.get("https://nominatim.openstreetmap.org/search",params=params,timeout=timeout)
        _last_nominatim_request=time.time()
    r.raise_for_status()
    return r


def _photon_search(q, limit=5):
    """Primary geocoder for interactive place lookup; keeps Nominatim out of the hot path."""
    r=session.get(
        "https://photon.komoot.io/api/",
        params={"q":q,"limit":max(1,min(int(limit),6)),"lang":"de"},
        timeout=10
    )
    print(f"[PHOTON] {q!r} status={r.status_code}",flush=True)
    r.raise_for_status()
    rows=[]
    for f in (r.json() or {}).get("features") or []:
        g=f.get("geometry") or {}; c=g.get("coordinates") or []
        p=f.get("properties") or {}
        if len(c)<2: continue
        name=p.get("name") or p.get("city") or p.get("town") or p.get("village") or q
        parts=[name,p.get("state"),p.get("country")]
        label=", ".join(str(x) for x in parts if x)
        rows.append({
            "lat":float(c[1]),"lon":float(c[0]),
            "name":name,"display_name":label or name,
            "country":p.get("country"),"country_code":p.get("countrycode"),
            "type":p.get("type") or p.get("osm_key") or "",
            "importance":float(p.get("importance") or 0),
            "source":"Photon"
        })
    return rows

def _nominatim_search_rows(q, limit=5):
    r=_nominatim_get({
        "q":q,"format":"jsonv2","limit":max(1,min(int(limit),6)),
        "addressdetails":1,"featuretype":"settlement"
    })
    rows=[]
    for x in r.json():
        a=x.get("address") or {}
        label=x.get("display_name") or q
        short=a.get("city") or a.get("town") or a.get("village") or a.get("municipality") or x.get("name") or label.split(",")[0]
        rows.append({
            "lat":float(x["lat"]),"lon":float(x["lon"]),
            "name":short,"display_name":label,
            "country":a.get("country"),"country_code":a.get("country_code"),
            "type":x.get("type"),"importance":float(x.get("importance") or 0),
            "source":"Nominatim"
        })
    return rows

def place_suggestions(q, limit=5):
    q=(q or "").strip()
    if len(q)<2: return []
    key=(q.casefold(), int(limit))
    cached=_cache_get(_place_cache,key,CACHE_TTL_PLACE)
    if cached is not None:
        print(f"[PLACE-CACHE] {q}",flush=True)
        return cached

    rows=[]
    photon_error=None
    try:
        rows=_photon_search(q,limit=limit)
    except Exception as e:
        photon_error=e
        print(f"[PHOTON] failed {type(e).__name__}: {e}",flush=True)

    if not rows:
        try:
            rows=_nominatim_search_rows(q,limit=limit)
        except Exception as e:
            print(f"[NOMINATIM-FALLBACK] failed {type(e).__name__}: {e}",flush=True)

    if not rows and photon_error:
        raise requests.RequestException(f"Ortssuche nicht erreichbar: {photon_error}")

    _cache_set(_place_cache,key,rows)
    return rows

def geocode(q):
    rows=place_suggestions(q,limit=1)
    if not rows: raise ValueError(f"Ort nicht gefunden: {q}")
    x=rows[0]
    return {"lat":x["lat"],"lon":x["lon"],"name":x["display_name"]}

def brouter(a, b, profile="trekking"):
    url = "https://brouter.de/brouter"
    params = {
        "lonlats": f'{a["lon"]},{a["lat"]}|{b["lon"]},{b["lat"]}',
        "profile": profile,
        "alternativeidx": 0,
        "format": "geojson"
    }
    print(f"[BROUTER] request profile={profile} lonlats={params['lonlats']}", flush=True)
    r = requests.get(url, params=params, headers={"User-Agent":"AdventureBikeOS/0.25"}, timeout=22)
    print(f"[BROUTER] status={r.status_code} content-type={r.headers.get('content-type')}", flush=True)
    if not r.ok:
        print(f"[BROUTER] response={r.text[:500]}", flush=True)
    r.raise_for_status()
    return r.json()


def _decode_polyline6(encoded):
    coords=[]
    index=0
    lat=0
    lon=0
    length=len(encoded)
    while index < length:
        result=1; shift=0; b=0
        while True:
            b=ord(encoded[index])-63; index+=1
            result += (b & 0x1f) << shift; shift += 5
            if b < 0x20: break
        dlat = ~(result >> 1) if (result & 1) else (result >> 1)
        lat += dlat
        result=1; shift=0
        while True:
            b=ord(encoded[index])-63; index+=1
            result += (b & 0x1f) << shift; shift += 5
            if b < 0x20: break
        dlon = ~(result >> 1) if (result & 1) else (result >> 1)
        lon += dlon
        coords.append([lon * 1e-6, lat * 1e-6])
    return coords

def valhalla_route(a, b):
    """Fallback bicycle route via FOSSGIS Valhalla demo. Prototype/fair-use only."""
    headers={"X-Client-Id":"adventure-bike-os-prototype"}
    payload={
        "locations":[{"lat":a["lat"],"lon":a["lon"]},{"lat":b["lat"],"lon":b["lon"]}],
        "costing":"bicycle",
        "units":"kilometers",
        "directions_options":{"units":"kilometers"}
    }
    print("[VALHALLA] fallback route request", flush=True)
    r=session.post("https://valhalla1.openstreetmap.de/route",json=payload,headers=headers,timeout=32)
    print(f"[VALHALLA] route status={r.status_code}", flush=True)
    r.raise_for_status()
    data=r.json()
    legs=(data.get("trip") or {}).get("legs") or []
    if not legs:
        raise ValueError("Valhalla returned no route legs")
    coords=[]
    for leg in legs:
        shape=leg.get("shape")
        if not shape: continue
        pts=_decode_polyline6(shape)
        if coords and pts and coords[-1]==pts[0]:
            pts=pts[1:]
        coords.extend(pts)
    if len(coords)<2:
        raise ValueError("Valhalla returned no usable route geometry")

    step=max(1, len(coords)//450)
    sampled=coords[::step]
    if sampled[-1] != coords[-1]:
        sampled.append(coords[-1])
    hreq={"shape":[{"lat":c[1],"lon":c[0]} for c in sampled],"height_precision":0}
    try:
        hr=session.post("https://valhalla1.openstreetmap.de/height",json=hreq,headers=headers,timeout=18)
        print(f"[VALHALLA] height status={hr.status_code}", flush=True)
        hr.raise_for_status()
        hd=hr.json()
        heights=hd.get("height") or []
        if len(heights)==len(sampled):
            coords3=[[c[0],c[1],heights[i] if heights[i] is not None else 0] for i,c in enumerate(sampled)]
        else:
            coords3=[[c[0],c[1],0] for c in sampled]
    except Exception as e:
        print(f"[VALHALLA] height fallback failed: {e}", flush=True)
        coords3=[[c[0],c[1],0] for c in sampled]

    return {
        "type":"Feature",
        "geometry":{"type":"LineString","coordinates":coords3},
        "properties":{"routing_source":"Valhalla fallback"}
    }


def _interp(a, b, t):
    return {"lat": a["lat"] + (b["lat"]-a["lat"])*t, "lon": a["lon"] + (b["lon"]-a["lon"])*t}

def segmented_route(a, b, profile="trekking"):
    """Last-resort prototype fallback: split long trips into shorter routing legs."""
    import math
    lat1,lon1,lat2,lon2=map(math.radians,[a["lat"],a["lon"],b["lat"],b["lon"]])
    h=math.sin((lat2-lat1)/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    straight=6371*2*math.asin(math.sqrt(h))
    segments=max(2,min(6,math.ceil(straight/260)))
    pts=[a]+[_interp(a,b,i/segments) for i in range(1,segments)]+[b]
    merged=[]
    sources=[]
    for i in range(len(pts)-1):
        leg_a,leg_b=pts[i],pts[i+1]
        try:
            f=brouter(leg_a,leg_b,profile)
            feat=f["features"][0] if "features" in f else f
            sources.append("BRouter")
        except Exception:
            feat=valhalla_route(leg_a,leg_b)
            sources.append("Valhalla")
        coords=(feat.get("geometry") or {}).get("coordinates") or []
        if not coords:
            raise requests.RequestException(f"Segment {i+1} lieferte keine Geometrie")
        if merged and merged[-1][:2]==coords[0][:2]:
            coords=coords[1:]
        merged.extend(coords)
    return {"type":"Feature","geometry":{"type":"LineString","coordinates":merged},"properties":{"routing_source":"Segmented "+"/".join(sorted(set(sources))),"segments":segments}}


def _sample_for_height(coords, limit=450):
    if len(coords) <= limit:
        return coords
    step=max(1,len(coords)//limit)
    out=coords[::step]
    if out[-1]!=coords[-1]:
        out.append(coords[-1])
    return out


def add_open_meteo_height(coords):
    """Enrich a 2D route with terrain elevation using Open-Meteo's elevation API."""
    sampled=_sample_for_height(coords, limit=600)
    out=[]
    try:
        for i in range(0,len(sampled),100):
            batch=sampled[i:i+100]
            params={
                "latitude": ",".join(f"{c[1]:.6f}" for c in batch),
                "longitude": ",".join(f"{c[0]:.6f}" for c in batch)
            }
            r=requests.get(
                "https://api.open-meteo.com/v1/elevation",
                params=params,
                headers={"User-Agent":"AdventureBikeOS/0.27"},
                timeout=18
            )
            print(f"[ELEVATION-OPENMETEO] batch={i//100+1} status={r.status_code}",flush=True)
            r.raise_for_status()
            elev=(r.json() or {}).get("elevation") or []
            if len(elev)!=len(batch):
                raise ValueError("Open-Meteo returned incomplete elevation batch")
            out.extend([[c[0],c[1],float(elev[j]) if elev[j] is not None else 0] for j,c in enumerate(batch)])
        if len(out)>=2:
            return out,"Open-Meteo"
    except Exception as e:
        print(f"[ELEVATION-OPENMETEO] failed: {type(e).__name__}: {e}",flush=True)
    return None,None

def add_valhalla_height(coords):
    """Secondary elevation fallback. Failure is non-fatal."""
    sampled=_sample_for_height(coords, limit=450)
    req={"shape":[{"lat":c[1],"lon":c[0]} for c in sampled],"height_precision":0}
    try:
        r=requests.post("https://valhalla1.openstreetmap.de/height",json=req,headers={"X-Client-Id":"adventure-bike-os-prototype"},timeout=15)
        print(f"[HEIGHT-VALHALLA] status={r.status_code}",flush=True)
        r.raise_for_status()
        heights=(r.json() or {}).get("height") or []
        if len(heights)==len(sampled):
            return [[c[0],c[1],heights[i] if heights[i] is not None else 0] for i,c in enumerate(sampled)],"Valhalla height"
    except Exception as e:
        print(f"[HEIGHT-VALHALLA] unavailable: {e}",flush=True)
    return None,None


def osrm_bike_route(a,b):
    """Third routing fallback via OSM Deutschland's OSRM bicycle demo service."""
    url=f"https://routing.openstreetmap.de/routed-bike/route/v1/driving/{a['lon']},{a['lat']};{b['lon']},{b['lat']}"
    params={"overview":"full","geometries":"geojson","steps":"false"}
    print("[OSRM-BIKE] request",flush=True)
    r=requests.get(url,params=params,headers={"User-Agent":"AdventureBikeOS/0.26"},timeout=24)
    print(f"[OSRM-BIKE] status={r.status_code}",flush=True)
    r.raise_for_status()
    data=r.json()
    routes=data.get("routes") or []
    if not routes:
        raise ValueError("OSRM Bike returned no route")
    coords=(routes[0].get("geometry") or {}).get("coordinates") or []
    if len(coords)<2:
        raise ValueError("OSRM Bike returned no usable geometry")
    coords3,height_source=add_open_meteo_height(coords)
    if not coords3:
        coords3,height_source=add_valhalla_height(coords)
    if not coords3:
        coords3=[[c[0],c[1]] for c in _sample_for_height(coords,limit=600)]
        height_source="unavailable"
    return {
        "type":"Feature",
        "geometry":{"type":"LineString","coordinates":coords3},
        "properties":{"routing_source":"OSRM Bike fallback","distance_m":routes[0].get("distance"),"height_source":height_source}
    }


def osrm_bike_segmented(a,b):
    """Last-resort long-distance fallback: split the trip into shorter OSRM-bike legs and merge them."""
    import math
    from concurrent.futures import ThreadPoolExecutor, as_completed
    lat1,lon1,lat2,lon2=map(math.radians,[a["lat"],a["lon"],b["lat"],b["lon"]])
    h=math.sin((lat2-lat1)/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    straight=6371*2*math.asin(math.sqrt(h))
    segments=max(3,min(10,math.ceil(straight/130)))
    pts=[a]+[_interp(a,b,i/segments) for i in range(1,segments)]+[b]

    def one_leg(i):
        aa,bb=pts[i],pts[i+1]
        url=f"https://routing.openstreetmap.de/routed-bike/route/v1/driving/{aa['lon']},{aa['lat']};{bb['lon']},{bb['lat']}"
        params={"overview":"full","geometries":"geojson","steps":"false"}
        r=requests.get(url,params=params,headers={"User-Agent":"AdventureBikeOS/0.34"},timeout=18)
        print(f"[OSRM-SEG] leg={i+1}/{segments} status={r.status_code}",flush=True)
        r.raise_for_status()
        routes=(r.json() or {}).get("routes") or []
        if not routes:
            raise ValueError(f"OSRM segment {i+1} ohne Route")
        coords=(routes[0].get("geometry") or {}).get("coordinates") or []
        if len(coords)<2:
            raise ValueError(f"OSRM segment {i+1} ohne Geometrie")
        return i,coords

    results=[None]*segments
    with ThreadPoolExecutor(max_workers=min(segments,3)) as pool:
        futures=[pool.submit(one_leg,i) for i in range(segments)]
        for fut in as_completed(futures):
            i,coords=fut.result()
            results[i]=coords

    merged=[]
    for coords in results:
        if not coords:
            raise ValueError("Segmentierter OSRM-Fallback unvollständig")
        if merged and merged[-1][:2]==coords[0][:2]:
            coords=coords[1:]
        merged.extend(coords)

    coords3,height_source=add_open_meteo_height(merged)
    if not coords3:
        coords3=[[c[0],c[1]] for c in _sample_for_height(merged,limit=700)]
        height_source="unavailable"
    return {
        "type":"Feature",
        "geometry":{"type":"LineString","coordinates":coords3},
        "properties":{"routing_source":"OSRM Bike segmented fallback","segments":segments,"height_source":height_source}
    }

def ensure_route_elevation(feature):
    geom=(feature.get("geometry") or {})
    coords=geom.get("coordinates") or []
    if len(coords)<2:
        return feature
    z=[c[2] for c in coords if len(c)>2 and isinstance(c[2],(int,float))]
    useful=len(z)>=2 and (max(z)-min(z)>3 or max(z)>10)
    if useful:
        feature.setdefault("properties",{})["height_source"]=feature.get("properties",{}).get("height_source","routing engine")
        return feature
    enriched,source=add_open_meteo_height(coords)
    if enriched:
        feature["geometry"]={"type":"LineString","coordinates":enriched}
        feature.setdefault("properties",{})["height_source"]=source
    else:
        feature.setdefault("properties",{})["height_source"]="unavailable"
    return feature

def valhalla_route_fast(a,b):
    """Geometry-first Valhalla route. Elevation is deliberately fetched later."""
    headers={"X-Client-Id":"adventure-bike-os-prototype"}
    payload={
        "locations":[{"lat":a["lat"],"lon":a["lon"]},{"lat":b["lat"],"lon":b["lon"]}],
        "costing":"bicycle","units":"kilometers",
        "directions_options":{"units":"kilometers"}
    }
    r=session.post("https://valhalla1.openstreetmap.de/route",json=payload,headers=headers,timeout=19)
    print(f"[VALHALLA-FAST] status={r.status_code}",flush=True)
    r.raise_for_status()
    data=r.json(); legs=(data.get("trip") or {}).get("legs") or []
    coords=[]
    for leg in legs:
        shape=leg.get("shape")
        if not shape: continue
        pts=_decode_polyline6(shape)
        if coords and pts and coords[-1]==pts[0]: pts=pts[1:]
        coords.extend(pts)
    if len(coords)<2: raise ValueError("Valhalla returned no usable geometry")
    step=max(1,len(coords)//900); sampled=coords[::step]
    if sampled[-1]!=coords[-1]: sampled.append(coords[-1])
    return {"type":"Feature","geometry":{"type":"LineString","coordinates":sampled},"properties":{"routing_source":"Valhalla"}}

def osrm_bike_route_fast(a,b):
    """Geometry-first OSM bicycle route. Elevation is deliberately fetched later."""
    url=f"https://routing.openstreetmap.de/routed-bike/route/v1/driving/{a['lon']},{a['lat']};{b['lon']},{b['lat']}"
    r=session.get(url,params={"overview":"full","geometries":"geojson","steps":"false"},timeout=18)
    print(f"[OSRM-BIKE-FAST] status={r.status_code}",flush=True)
    r.raise_for_status()
    data=r.json(); routes=data.get("routes") or []
    if not routes: raise ValueError("OSRM Bike returned no route")
    coords=(routes[0].get("geometry") or {}).get("coordinates") or []
    if len(coords)<2: raise ValueError("OSRM Bike returned no usable geometry")
    step=max(1,len(coords)//900); sampled=coords[::step]
    if sampled[-1]!=coords[-1]: sampled.append(coords[-1])
    return {"type":"Feature","geometry":{"type":"LineString","coordinates":sampled},
            "properties":{"routing_source":"OSRM Bike","distance_m":routes[0].get("distance")}}

def race_route(a, b, profile="trekking"):
    """Race three independent public routing engines and return the first valid geometry."""
    from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
    errors=[]
    pool=ThreadPoolExecutor(max_workers=3)
    futures={
        pool.submit(brouter,a,b,profile):"BRouter",
        pool.submit(valhalla_route_fast,a,b):"Valhalla",
        pool.submit(osrm_bike_route_fast,a,b):"OSRM Bike"
    }
    try:
        pending=set(futures)
        deadline=time.time()+21
        while pending and time.time()<deadline:
            done,pending=wait(pending,timeout=max(0.1,deadline-time.time()),return_when=FIRST_COMPLETED)
            if not done: break
            for fut in done:
                source=futures[fut]
                try:
                    feature=fut.result()
                    f=feature["features"][0] if isinstance(feature,dict) and "features" in feature else feature
                    coords=((f or {}).get("geometry") or {}).get("coordinates") or []
                    if len(coords)<2: raise ValueError("keine nutzbare Geometrie")
                    print(f"[ROUTE-RACE] success source={source}",flush=True)
                    for p in pending: p.cancel()
                    return f,source
                except Exception as e:
                    errors.append(f"{source}: {type(e).__name__}: {e}")
                    print(f"[ROUTE-RACE] {source} failed: {e}",flush=True)
    finally:
        pool.shutdown(wait=False,cancel_futures=True)
    raise requests.RequestException(" | ".join(errors) or "Alle Routingdienste ohne Antwort")


OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

@app.post("/api/osm-detail")
def osm_detail():
    """Server-side Overpass proxy with failover so Safari/iPad never has to call Overpass directly."""
    body=request.get_json(force=True) or {}
    query=(body.get("query") or "").strip()
    if not query or len(query)>120000:
        return jsonify(ok=False,elements=[],warning="Ungültige OSM-Abfrage."),400
    errors=[]
    for url in OVERPASS_ENDPOINTS:
        try:
            print(f"[OVERPASS] trying {url}",flush=True)
            r=requests.post(
                url,
                data={"data":query},
                headers={"User-Agent":UA,"Accept":"application/json"},
                timeout=28
            )
            print(f"[OVERPASS] {url} status={r.status_code}",flush=True)
            if r.ok:
                data=r.json()
                elements=data.get("elements") or []
                return jsonify(ok=True,elements=elements,source=url)
            errors.append(f"{url}: HTTP {r.status_code}")
        except Exception as ex:
            errors.append(f"{url}: {type(ex).__name__}")
            print(f"[OVERPASS] failed {url}: {ex}",flush=True)
    return jsonify(ok=False,elements=[],warning="OSM-Zusatzdaten derzeit nicht erreichbar.",errors=errors),200


@app.get("/api/place-suggest")
def place_suggest():
    try:
        q=(request.args.get("q") or "").strip()
        if len(q)<2:return jsonify(results=[])
        return jsonify(results=place_suggestions(q,limit=5))
    except requests.RequestException as e:
        print(f"[PLACE] unavailable: {e}",flush=True)
        return jsonify(results=[],warning="Ortssuche gerade nicht erreichbar. Du kannst den Ortsnamen trotzdem eingeben und die Route starten."),200

@app.post("/api/transport-nearby")
def transport_nearby():
    """Potential rail/bus/ferry access near route/stage points. Not a live timetable."""
    try:
        body=request.get_json(force=True) or {}
        points=(body.get("points") or [])[:12]
        if not points:return jsonify(ok=False,points=[]),400
        key=tuple((round(float(p["lat"]),3),round(float(p["lon"]),3),str(p.get("label") or "")) for p in points)
        cached=_cache_get(_transport_cache,key,CACHE_TTL_TRANSPORT)
        if cached is not None:return jsonify(**cached,cached=True)

        clauses=[]
        for p in points:
            lat=float(p["lat"]);lon=float(p["lon"])
            clauses += [
                f'nwr(around:6500,{lat},{lon})["railway"~"station|halt"];',
                f'nwr(around:4500,{lat},{lon})["amenity"="bus_station"];',
                f'nwr(around:2500,{lat},{lon})["highway"="bus_stop"];',
                f'nwr(around:6500,{lat},{lon})["amenity"="ferry_terminal"];'
            ]
        q='[out:json][timeout:22];('+''.join(clauses)+');out center tags;'
        elements=[];source=None
        for url in OVERPASS_ENDPOINTS:
            try:
                r=session.post(url,data={"data":q},headers={"User-Agent":UA,"Accept":"application/json"},timeout=25)
                print(f"[TRANSPORT] {url} status={r.status_code}",flush=True)
                if r.ok:
                    elements=(r.json() or {}).get("elements") or [];source=url;break
            except Exception as e:
                print(f"[TRANSPORT] {url} failed {e}",flush=True)
        if source is None:
            return jsonify(ok=False,points=[],warning="ÖV-Zusatzdaten derzeit nicht erreichbar."),200

        import math
        def dist(lat1,lon1,lat2,lon2):
            R=6371
            p1,p2=math.radians(lat1),math.radians(lat2)
            dp=math.radians(lat2-lat1);dl=math.radians(lon2-lon1)
            a=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
            return 2*R*math.asin(math.sqrt(a))
        parsed=[]
        seen=set()
        for el in elements:
            t=el.get("tags") or {}
            lat=el.get("lat") or (el.get("center") or {}).get("lat")
            lon=el.get("lon") or (el.get("center") or {}).get("lon")
            if lat is None or lon is None: continue
            kind="train" if t.get("railway") in ("station","halt") else ("bus" if t.get("amenity")=="bus_station" or t.get("highway")=="bus_stop" else ("ferry" if t.get("amenity")=="ferry_terminal" else None))
            if not kind: continue
            name=t.get("name") or t.get("ref") or {"train":"Bahnhof","bus":"Bushaltestelle","ferry":"Fährterminal"}[kind]
            sk=(kind,name,round(float(lat),4),round(float(lon),4))
            if sk in seen: continue
            seen.add(sk)
            parsed.append({"kind":kind,"name":name,"lat":float(lat),"lon":float(lon),"operator":t.get("operator") or "",
                           "network":t.get("network") or "","bicycle":t.get("bicycle") or "","website":t.get("website") or t.get("contact:website") or ""})
        out=[]
        for p in points:
            lat=float(p["lat"]);lon=float(p["lon"]);label=str(p.get("label") or "Punkt")
            arr=[]
            for x in parsed:
                d=dist(lat,lon,x["lat"],x["lon"])
                if d<=7:
                    y=dict(x);y["distance_km"]=round(d,1)
                    query=f'{x["name"]} {label} {x["kind"]} Fahrrad Fahrplan'
                    y["search"]="https://www.google.com/search?q="+requests.utils.quote(query)
                    arr.append(y)
            arr.sort(key=lambda x:x["distance_km"])
            chosen=[]
            for kind in ("train","bus","ferry"):
                chosen += [x for x in arr if x["kind"]==kind][:3]
            out.append({"label":label,"options":chosen[:7]})
        result={"ok":True,"points":out,"source":source}
        _cache_set(_transport_cache,key,result)
        return jsonify(**result,cached=False)
    except Exception as e:
        print(f"[TRANSPORT] error {type(e).__name__}: {e}",flush=True)
        return jsonify(ok=False,points=[],warning="ÖV-Zusatzdaten derzeit nicht erreichbar."),200



def _terrain_point_segment_m(p, a, b):
    """Approximate point-to-segment distance in meters for short OSM segments."""
    import math
    R=6371000.0
    lat0=math.radians((p["lat"]+a["lat"]+b["lat"])/3.0)
    def xy(q):
        return (
            math.radians(q["lon"])*R*math.cos(lat0),
            math.radians(q["lat"])*R
        )
    px,py=xy(p); ax,ay=xy(a); bx,by=xy(b)
    vx,vy=bx-ax,by-ay
    wx,wy=px-ax,py-ay
    vv=vx*vx+vy*vy
    t=(wx*vx+wy*vy)/vv if vv>0 else 0.0
    t=max(0.0,min(1.0,t))
    dx=px-(ax+t*vx); dy=py-(ay+t*vy)
    return (dx*dx+dy*dy)**0.5

def _terrain_way_distance_m(sample, el):
    geom=el.get("geometry") or []
    if not geom:
        return None
    if len(geom)==1:
        import math
        p={"lat":float(geom[0]["lat"]),"lon":float(geom[0]["lon"])}
        lat1,lon1,lat2,lon2=map(math.radians,[sample["lat"],sample["lon"],p["lat"],p["lon"]])
        h=math.sin((lat2-lat1)/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
        return 6371000*2*math.asin(math.sqrt(h))
    best=None
    for i in range(len(geom)-1):
        try:
            a={"lat":float(geom[i]["lat"]),"lon":float(geom[i]["lon"])}
            b={"lat":float(geom[i+1]["lat"]),"lon":float(geom[i+1]["lon"])}
        except (TypeError,ValueError,KeyError):
            continue
        d=_terrain_point_segment_m(sample,a,b)
        if best is None or d<best:
            best=d
    return best

def _terrain_normalize(tags):
    tags=tags or {}
    highway=str(tags.get("highway") or "").lower()
    surface=str(tags.get("surface") or "").lower()
    tracktype=str(tags.get("tracktype") or "").lower()
    smoothness=str(tags.get("smoothness") or "").lower()
    mtb_raw=str(tags.get("mtb:scale") or "")
    try:
        mtb_scale=float(mtb_raw.split(";")[0]) if mtb_raw else 0.0
    except Exception:
        mtb_scale=0.0

    cls="unknown"; risk=.35
    if mtb_scale>=1 or smoothness in ("very_bad","horrible","very_horrible","impassable") or tracktype in ("grade4","grade5"):
        cls="rough";risk=1.0
    elif surface in ("ground","dirt","earth","mud","sand","grass") or tracktype=="grade3":
        cls="rough";risk=.85
    elif surface in ("gravel","pebblestone") or tracktype=="grade2":
        cls="gravel";risk=.55
    elif surface in ("fine_gravel","compacted") or tracktype=="grade1":
        cls="fine";risk=.28
    elif surface in ("asphalt","paved","concrete","concrete:plates","paving_stones"):
        cls="paved";risk=.08
    elif surface=="unpaved":
        cls="gravel";risk=.55
    elif highway=="track":
        cls="unknown";risk=.60
    elif highway in ("path","bridleway"):
        cls="unknown";risk=.78
    elif highway in ("motorway","trunk","primary","secondary","tertiary","residential","living_street","service","cycleway"):
        cls="unknown";risk=.18

    evidence=[]
    if mtb_scale>=1:evidence.append(f"mtb:scale={mtb_raw}")
    if smoothness:evidence.append(f"smoothness={smoothness}")
    if tracktype:evidence.append(f"tracktype={tracktype}")
    if surface:evidence.append(f"surface={surface}")

    return {
        "surface_class":cls,
        "risk":round(risk,3),
        "highway":highway,
        "surface":surface,
        "tracktype":tracktype,
        "smoothness":smoothness,
        "mtb_scale":mtb_scale,
        "sac_scale":str(tags.get("sac_scale") or ""),
        "bicycle":str(tags.get("bicycle") or ""),
        "evidence":evidence[:4],
    }

_terrain_match_cache = {}
TERRAIN_MATCH_CACHE_TTL = 6 * 3600

def _terrain_cache_key(sample):
    return (round(float(sample["lat"]),4), round(float(sample["lon"]),4))

def _terrain_cache_get(sample):
    key=_terrain_cache_key(sample)
    item=_terrain_match_cache.get(key)
    if not item:
        return None
    ts,value=item
    if time.time()-ts > TERRAIN_MATCH_CACHE_TTL:
        _terrain_match_cache.pop(key,None)
        return None
    return copy.deepcopy(value)

def _terrain_cache_set(sample,value):
    _terrain_match_cache[_terrain_cache_key(sample)] = (time.time(),copy.deepcopy(value))

def _terrain_query_one(sample):
    """
    Small sequential Overpass lookup for one route point.
    This deliberately avoids concurrent geometry-heavy batches.
    """
    cached=_terrain_cache_get(sample)
    if cached is not None:
        cached["cache"]=True
        return cached

    lat=float(sample["lat"])
    lon=float(sample["lon"])
    last_errors=[]
    any_success=False

    for radius in (70,140):
        q=(
            f'[out:json][timeout:6];'
            f'way(around:{radius},{lat},{lon})["highway"];'
            f'out tags geom qt;'
        )

        radius_had_response=False

        for url in OVERPASS_ENDPOINTS:
            try:
                r=session.post(
                    url,
                    data={"data":q},
                    headers={"User-Agent":UA,"Accept":"application/json"},
                    timeout=9
                )
                print(
                    f"[TERRAIN-V1.1] point={sample['sample_index']} "
                    f"r={radius} source={url} status={r.status_code}",
                    flush=True
                )

                if not r.ok:
                    last_errors.append(f"{url}:HTTP{r.status_code}")
                    continue

                any_success=True
                radius_had_response=True
                elements=(r.json() or {}).get("elements") or []

                best=None
                best_d=None
                for el in elements:
                    d=_terrain_way_distance_m(sample,el)
                    if d is None:
                        continue
                    if best_d is None or d<best_d:
                        best_d=d
                        best=el

                if best is not None and best_d is not None and best_d<=120:
                    if best_d<=25:
                        confidence="high"
                    elif best_d<=60:
                        confidence="medium"
                    else:
                        confidence="low"

                    norm=_terrain_normalize(best.get("tags") or {})
                    out={
                        **sample,
                        "status":"matched",
                        "matched":True,
                        "confidence":confidence,
                        "distance_to_way_m":round(best_d,1),
                        "osm_type":best.get("type"),
                        "osm_id":best.get("id"),
                        "source":url,
                        "cache":False,
                        **norm,
                    }
                    _terrain_cache_set(sample,out)
                    return out

                # Valid service response but no useful match at this radius.
                break

            except Exception as e:
                last_errors.append(f"{url}:{type(e).__name__}")
                print(
                    f"[TERRAIN-V1.1] point={sample['sample_index']} "
                    f"r={radius} source={url} failed {type(e).__name__}: {e}",
                    flush=True
                )

        # If a mirror answered successfully but no match existed, widen once.
        if radius_had_response:
            continue

    if not any_success:
        return {
            **sample,
            "status":"unavailable",
            "matched":False,
            "confidence":"none",
            "distance_to_way_m":None,
            "errors":last_errors[-3:],
        }

    out={
        **sample,
        "status":"no_match",
        "matched":False,
        "confidence":"none",
        "distance_to_way_m":None,
    }
    _terrain_cache_set(sample,out)
    return out


def _valhalla_surface_class(surface, unpaved=False):
    s=str(surface or "").lower()
    if s in ("paved_smooth","paved"):
        return "paved",0.08
    if s in ("paved_rough","compacted"):
        return "fine",0.30
    if s=="gravel":
        return "gravel",0.58
    if s in ("dirt","path"):
        return "rough",0.88
    if s=="impassable":
        return "rough",1.20
    if unpaved:
        return "gravel",0.62
    return "unknown",0.35

def _summarize_valhalla_edges(edges):
    total_km=0.0
    known_km=0.0
    buckets={"paved":0.0,"fine":0.0,"gravel":0.0,"rough":0.0,"unknown":0.0}
    use_km={}
    risk_sum=0.0
    grade_max=0.0
    way_ids=set()

    for e in edges or []:
        try:
            length=max(0.0,float(e.get("length") or 0.0))
        except Exception:
            length=0.0
        if length<=0:
            continue
        total_km += length
        cls,risk=_valhalla_surface_class(e.get("surface"), bool(e.get("unpaved")))
        buckets[cls]+=length
        if cls!="unknown":
            known_km+=length
        risk_sum += risk*length
        use=str(e.get("use") or "other").lower()
        use_km[use]=use_km.get(use,0.0)+length
        try:
            grade_max=max(grade_max,abs(float(e.get("max_upward_grade") or 0)),abs(float(e.get("max_downward_grade") or 0)))
        except Exception:
            pass
        if e.get("way_id") is not None:
            way_ids.add(str(e.get("way_id")))

    denom=max(total_km,1e-9)
    pct=lambda x: round(100.0*x/denom)
    technical_km=sum(use_km.get(k,0.0) for k in ("track","mountain_bike","footway","steps"))
    return {
        "ok": total_km>0,
        "edge_count": len(edges or []),
        "distance_km": round(total_km,2),
        "coverage": round(100.0*known_km/denom),
        "paved": pct(buckets["paved"]),
        "fine": pct(buckets["fine"]),
        "gravel": pct(buckets["gravel"]),
        "rough": pct(buckets["rough"]),
        "unknown": pct(buckets["unknown"]),
        "track": pct(use_km.get("track",0.0)),
        "path": pct(use_km.get("footway",0.0)+use_km.get("mountain_bike",0.0)+use_km.get("steps",0.0)),
        "technical_share": pct(technical_km),
        "risk": round(risk_sum/denom,3),
        "max_grade": round(grade_max,1),
        "way_count": len(way_ids),
    }

def _terrain_merge_edge_segments(edges, matched_shape):
    """
    Build compact visual terrain segments from Valhalla edge shape indices.
    Consecutive edges with the same normalized surface class are merged.
    """
    if not matched_shape:
        return []

    usable=[]
    total_length=0.0
    for e in edges or []:
        try:
            length=max(0.0,float(e.get("length") or 0.0))
            b=int(e.get("begin_shape_index"))
            z=int(e.get("end_shape_index"))
        except (TypeError,ValueError):
            continue
        if length<=0 or b<0 or z<b or b>=len(matched_shape):
            continue
        z=min(z,len(matched_shape)-1)
        cls,risk=_valhalla_surface_class(e.get("surface"),bool(e.get("unpaved")))
        usable.append({
            "class":cls,
            "risk":risk,
            "length_km":length,
            "begin":b,
            "end":z,
            "surface":str(e.get("surface") or ""),
            "use":str(e.get("use") or ""),
        })
        total_length+=length

    if not usable or total_length<=0:
        return []

    merged=[]
    progressed=0.0
    for e in usable:
        start_fraction=progressed/total_length
        progressed+=e["length_km"]
        end_fraction=min(1.0,progressed/total_length)

        coords=[
            [float(matched_shape[i][0]),float(matched_shape[i][1])]
            for i in range(e["begin"],e["end"]+1)
            if i < len(matched_shape)
        ]
        if len(coords)<2:
            continue

        can_merge=(
            merged and
            merged[-1]["class"]==e["class"] and
            merged[-1]["use"]==e["use"] and
            abs(merged[-1]["end_fraction"]-start_fraction)<0.03
        )
        if can_merge:
            m=merged[-1]
            if m["geometry"][-1]==coords[0]:
                coords=coords[1:]
            m["geometry"].extend(coords)
            m["length_km"]=round(m["length_km"]+e["length_km"],3)
            m["end_fraction"]=round(end_fraction,5)
            m["risk"]=round(max(m["risk"],e["risk"]),3)
        else:
            merged.append({
                "class":e["class"],
                "risk":round(e["risk"],3),
                "length_km":round(e["length_km"],3),
                "start_fraction":round(start_fraction,5),
                "end_fraction":round(end_fraction,5),
                "surface":e["surface"],
                "use":e["use"],
                "geometry":coords,
            })

    return merged[:160]

def _valhalla_trace_stage(stage):
    shape=stage.get("shape") or []
    clean=[]
    for p in shape[:70]:
        try:
            clean.append({"lat":float(p["lat"]),"lon":float(p["lon"])})
        except (TypeError,ValueError,KeyError):
            continue
    if len(clean)<2:
        raise ValueError("Zu wenige Punkte für Terrain-Profil")

    payload={
        "shape":clean,
        "costing":"bicycle",
        "shape_match":"walk_or_snap",
        "units":"kilometers",
        "filters":{
            "action":"include",
            "attributes":[
                "shape",
                "edge.length",
                "edge.surface",
                "edge.unpaved",
                "edge.use",
                "edge.road_class",
                "edge.way_id",
                "edge.weighted_grade",
                "edge.max_upward_grade",
                "edge.max_downward_grade",
                "edge.bicycle_type",
                "edge.begin_shape_index",
                "edge.end_shape_index"
            ]
        }
    }
    r=session.post(
        "https://valhalla1.openstreetmap.de/trace_attributes",
        json=payload,
        headers={"X-Client-Id":"adventure-bike-os-prototype","User-Agent":UA},
        timeout=18
    )
    print(f"[TERRAIN-V2.1] stage={stage.get('stage_index')} valhalla status={r.status_code}",flush=True)
    r.raise_for_status()
    data=r.json() or {}
    edges=data.get("edges") or []
    if not edges:
        raise ValueError("Valhalla lieferte keine Terrain-Kanten")

    matched_shape=[]
    encoded=data.get("shape")
    if isinstance(encoded,str) and encoded:
        try:
            matched_shape=_decode_polyline6(encoded)
        except Exception as e:
            print(f"[TERRAIN-V2.1] shape decode failed: {e}",flush=True)

    summary=_summarize_valhalla_edges(edges)
    summary["stage_index"]=int(stage.get("stage_index") or 0)
    summary["source"]="Valhalla trace_attributes"
    summary["status"]="matched" if summary["ok"] else "no_match"
    summary["segments"]=_terrain_merge_edge_segments(edges,matched_shape)
    summary["visual_coverage"]=round(
        100*sum(float(s.get("length_km") or 0) for s in summary["segments"])/max(.001,float(summary.get("distance_km") or 0))
    ) if summary["segments"] else 0
    return summary

@app.post("/api/terrain-profile-v2")
def terrain_profile_v2():
    """
    Route-matched terrain profile.
    Primary source: Valhalla trace_attributes, which follows the route itself
    and returns normalized edge surface/use attributes.
    Existing Overpass point matching remains available as a fallback path.
    """
    try:
        body=request.get_json(force=True) or {}
        raw=(body.get("stages") or [])[:8]
        stages=[]
        for i,s in enumerate(raw):
            shape=s.get("shape") or []
            if len(shape)>=2:
                stages.append({"stage_index":int(s.get("stage_index",i)),"shape":shape[:70]})
        if not stages:
            return jsonify(ok=False,version="terrain-profile-v2.1",stages=[],warning="Keine gültigen Etappen-Geometrien."),400

        results=[]
        errors=[]
        for stage in stages:
            try:
                results.append(_valhalla_trace_stage(stage))
            except Exception as e:
                print(f"[TERRAIN-V2] stage={stage['stage_index']} failed {type(e).__name__}: {e}",flush=True)
                errors.append({"stage_index":stage["stage_index"],"error":type(e).__name__})
                results.append({
                    "stage_index":stage["stage_index"],
                    "ok":False,
                    "status":"unavailable",
                    "source":"Valhalla trace_attributes",
                    "coverage":0,
                    "paved":0,"fine":0,"gravel":0,"rough":0,"unknown":100,
                    "track":0,"path":0,"technical_share":0,
                    "risk":0.0,"max_grade":0.0,"distance_km":0.0,"edge_count":0,"way_count":0
                })

        successful=sum(1 for x in results if x.get("ok"))
        avg_cov=round(sum(float(x.get("coverage") or 0) for x in results)/max(1,len(results)))
        return jsonify(
            ok=successful>0,
            version="terrain-profile-v2.1",
            source="Valhalla trace_attributes",
            stages=sorted(results,key=lambda x:x["stage_index"]),
            stage_success=successful,
            stage_total=len(results),
            reliable_coverage=avg_cov,
            partial=successful<len(results),
            warning=("Terrain-Profil nur teilweise verfügbar." if successful<len(results) else None),
            errors=errors
        ),200
    except Exception as e:
        print(f"[TERRAIN-V2] error {type(e).__name__}: {e}",flush=True)
        return jsonify(ok=False,version="terrain-profile-v2.1",stages=[],warning="Terrain-Profil derzeit nicht erreichbar."),200


@app.post("/api/terrain-match-v1")
def terrain_match_v1():
    """
    Terrain data v1.1:
    - nine small route-point queries
    - sequential, not bursty
    - 70 m search + one 140 m fallback
    - six-hour cache per rounded coordinate
    """
    try:
        body=request.get_json(force=True) or {}
        raw=(body.get("samples") or [])[:9]
        samples=[]

        for idx,p in enumerate(raw):
            try:
                samples.append({
                    "sample_index":idx,
                    "lat":float(p["lat"]),
                    "lon":float(p["lon"]),
                    "stage_index":int(p.get("stageIndex") or 0),
                    "route_index":int(p.get("routeIndex") or 0),
                })
            except (TypeError,ValueError,KeyError):
                continue

        if not samples:
            return jsonify(ok=False,matches=[],warning="Keine gültigen Terrain-Stichproben."),400

        matches=[_terrain_query_one(s) for s in samples]

        total=len(matches)
        service=sum(1 for x in matches if x["status"]!="unavailable")
        matched=sum(1 for x in matches if x.get("matched"))
        reliable=sum(1 for x in matches if x.get("confidence") in ("high","medium"))
        cached=sum(1 for x in matches if x.get("cache"))
        sources=sorted({x.get("source") for x in matches if x.get("source")})

        print(
            f"[TERRAIN-V1.1] done total={total} service={service} "
            f"matched={matched} reliable={reliable} cached={cached}",
            flush=True
        )

        return jsonify(
            ok=True,
            version="terrain-data-v1.1",
            matches=matches,
            source=", ".join(sources),
            partial=service<total,
            service_coverage=round(100*service/max(1,total)),
            matched_coverage=round(100*matched/max(1,total)),
            reliable_coverage=round(100*reliable/max(1,total)),
            cached_points=cached,
            warning=("Ein Teil der Terrain-Dienste war nicht erreichbar." if service<total else None),
        )

    except Exception as e:
        print(f"[TERRAIN-V1.1] error {type(e).__name__}: {e}",flush=True)
        return jsonify(
            ok=False,
            version="terrain-data-v1.1",
            matches=[],
            warning="Terrain-Datenbasis derzeit nicht erreichbar."
        ),200


@app.post("/api/osm-terrain-batch")
def osm_terrain_batch():
    """Robuste Terrain-Stichproben: kleine parallele Overpass-Abfragen mit einmaligem Fallback."""
    try:
        body=request.get_json(force=True) or {}
        raw=(body.get("samples") or [])[:16]
        samples=[]
        for p in raw:
            try:
                samples.append({"lat":float(p["lat"]),"lon":float(p["lon"])})
            except (TypeError,ValueError,KeyError):
                continue
        if not samples:
            return jsonify(ok=False,elements=[],warning="Keine gültigen Terrain-Stichproben."),400

        chunks=[samples[i:i+4] for i in range(0,len(samples),4)]

        def build_query(chunk):
            clauses=[f'way(around:100,{p["lat"]},{p["lon"]})["highway"];' for p in chunk]
            return '[out:json][timeout:6];('+''.join(clauses)+');out tags geom qt;'

        def one_request(chunk_index, endpoint_index, timeout=7):
            url=OVERPASS_ENDPOINTS[endpoint_index % len(OVERPASS_ENDPOINTS)]
            q=build_query(chunks[chunk_index])
            try:
                r=requests.post(
                    url,
                    data={"data":q},
                    headers={"User-Agent":UA,"Accept":"application/json"},
                    timeout=timeout
                )
                print(f"[OSM-TERRAIN-BATCH] chunk={chunk_index+1}/{len(chunks)} {url} status={r.status_code}",flush=True)
                if not r.ok:
                    return chunk_index,False,[],url,f"HTTP {r.status_code}"
                elements=(r.json() or {}).get("elements") or []
                return chunk_index,True,elements,url,None
            except Exception as e:
                print(f"[OSM-TERRAIN-BATCH] chunk={chunk_index+1} {url} failed {type(e).__name__}: {e}",flush=True)
                return chunk_index,False,[],url,type(e).__name__

        from concurrent.futures import ThreadPoolExecutor, as_completed

        results={}
        failed=[]
        with ThreadPoolExecutor(max_workers=min(4,len(chunks))) as pool:
            futures=[pool.submit(one_request,i,i % len(OVERPASS_ENDPOINTS),7) for i in range(len(chunks))]
            for fut in as_completed(futures):
                i,ok,elements,url,error=fut.result()
                if ok:
                    results[i]=(elements,url)
                else:
                    failed.append(i)

        if failed:
            retry_failed=[]
            with ThreadPoolExecutor(max_workers=min(4,len(failed))) as pool:
                futures=[pool.submit(one_request,i,(i+1) % len(OVERPASS_ENDPOINTS),5) for i in failed]
                for fut in as_completed(futures):
                    i,ok,elements,url,error=fut.result()
                    if ok:
                        results[i]=(elements,url)
                    else:
                        retry_failed.append(i)
            failed=retry_failed

        merged=[]
        seen=set()
        sources=[]
        for i in sorted(results):
            elements,url=results[i]
            sources.append(url)
            for el in elements:
                key=(el.get("type"),el.get("id"))
                if key in seen:
                    continue
                seen.add(key)
                merged.append(el)

        if not results:
            return jsonify(
                ok=False,
                elements=[],
                warning="Terrain-Dienste antworten derzeit nicht. Bitte später erneut versuchen.",
                failed_chunks=len(chunks)
            ),200

        partial=bool(failed)
        return jsonify(
            ok=True,
            elements=merged,
            source=", ".join(sorted(set(sources))),
            partial=partial,
            completed_chunks=len(results),
            total_chunks=len(chunks),
            warning=("Terrain nur teilweise verfügbar." if partial else None)
        )
    except Exception as e:
        print(f"[OSM-TERRAIN-BATCH] error {type(e).__name__}: {e}",flush=True)
        return jsonify(ok=False,elements=[],warning="Terrain-Batch derzeit nicht erreichbar."),200

@app.post("/api/osm-terrain")
def osm_terrain():
    try:
        body=request.get_json(force=True) or {}
        samples=(body.get("samples") or [])[:34]
        if not samples:
            return jsonify(ok=False,elements=[]),400
        clauses=[f'way(around:120,{float(p["lat"])},{float(p["lon"])})["highway"];' for p in samples]
        q='[out:json][timeout:18];('+''.join(clauses)+');out tags geom qt;'
        for url in OVERPASS_ENDPOINTS:
            try:
                r=session.post(url,data={"data":q},headers={"User-Agent":UA,"Accept":"application/json"},timeout=22)
                print(f"[OSM-TERRAIN] {url} status={r.status_code}",flush=True)
                if r.ok:
                    return jsonify(ok=True,elements=(r.json() or {}).get("elements") or [],source=url)
            except Exception as e:
                print(f"[OSM-TERRAIN] {url} failed {e}",flush=True)
        return jsonify(ok=False,elements=[],warning="Terrain-Zusatzdaten derzeit nicht erreichbar."),200
    except Exception as e:
        print(f"[OSM-TERRAIN] error {type(e).__name__}: {e}",flush=True)
        return jsonify(ok=False,elements=[],warning="Terrain-Zusatzdaten derzeit nicht erreichbar."),200




LODGING_TYPES = {
    "hotel","guest_house","hostel","motel","apartment","chalet",
    "alpine_hut","wilderness_hut","camp_site","caravan_site"
}
LODGING_HOTEL_TYPES = {
    "hotel","guest_house","hostel","motel","apartment","chalet","alpine_hut"
}
LODGING_CAMP_TYPES = {"camp_site","caravan_site"}

def _lodging_allowed_types(mode):
    if mode=="camping":
        return LODGING_CAMP_TYPES
    if mode=="mixed":
        return LODGING_TYPES
    return LODGING_HOTEL_TYPES

def _lodging_photon_point(lat,lon,lodging,radius_km=10,limit=24):
    """
    Photon reverse search supports radius + osm_tag filters.
    Query the broad tourism key, then keep only accommodation values ourselves.
    """
    r=session.get(
        "https://photon.komoot.io/reverse",
        params={
            "lat":float(lat),"lon":float(lon),
            "radius":max(1,min(float(radius_km),25)),
            "limit":max(1,min(int(limit),30)),
            "lang":"de",
            "osm_tag":"tourism"
        },
        timeout=6
    )
    print(f"[LODGING-PHOTON] {lat:.4f},{lon:.4f} status={r.status_code}",flush=True)
    r.raise_for_status()

    allowed=_lodging_allowed_types(lodging)
    out=[]
    for f in (r.json() or {}).get("features") or []:
        g=f.get("geometry") or {}
        c=g.get("coordinates") or []
        p=f.get("properties") or {}
        if len(c)<2:
            continue
        osm_value=str(p.get("osm_value") or "")
        osm_key=str(p.get("osm_key") or "")
        if osm_key!="tourism" or osm_value not in allowed:
            continue
        name=p.get("name") or p.get("street") or osm_value.replace("_"," ").title()
        out.append({
            "id":f'photon-{p.get("osm_type") or "x"}-{p.get("osm_id") or len(out)}',
            "name":name,
            "type":osm_value,
            "lat":float(c[1]),"lon":float(c[0]),
            "website":p.get("website") or p.get("contact:website") or "",
            "phone":p.get("phone") or p.get("contact:phone") or "",
            "stars":p.get("stars") or "",
            "bicycle":p.get("bicycle") or "",
            "osm_type":str(p.get("osm_type") or ""),
            "osm_id":p.get("osm_id"),
            "source":"Photon"
        })
    return out

def _lodging_dedupe(rows):
    seen=set(); out=[]
    for x in rows:
        try:
            key=(str(x.get("name") or "").casefold(),str(x.get("type") or ""),
                 round(float(x["lat"]),4),round(float(x["lon"]),4))
        except Exception:
            continue
        if key in seen:
            continue
        seen.add(key);out.append(x)
    return out

def _lodging_overpass_fallback(points,lodging,radius=9000):
    """
    Last-resort fallback only. Unlike previous versions this is never the
    primary request, so a slow Overpass service cannot block normal results.
    """
    allowed=_lodging_allowed_types(lodging)
    sleep_regex="|".join(sorted(allowed))
    clauses=[
        f'nwr(around:{int(radius)},{lat},{lon})["tourism"~"{sleep_regex}"];'
        for lat,lon in points[:2]
    ]
    q='[out:json][timeout:7];('+''.join(clauses)+');out center tags 100;'

    from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
    def one(url):
        r=requests.post(
            url,data={"data":q},
            headers={"User-Agent":UA,"Accept":"application/json"},
            timeout=8
        )
        if not r.ok:
            raise requests.RequestException(f"HTTP {r.status_code}")
        return url,(r.json() or {}).get("elements") or []

    pool=ThreadPoolExecutor(max_workers=min(3,len(OVERPASS_ENDPOINTS)))
    futs={pool.submit(one,url):url for url in OVERPASS_ENDPOINTS}
    try:
        pending=set(futs)
        deadline=time.time()+9
        while pending and time.time()<deadline:
            done,pending=wait(
                pending,timeout=max(.1,deadline-time.time()),
                return_when=FIRST_COMPLETED
            )
            if not done:
                break
            for fut in done:
                try:
                    source,elements=fut.result()
                    for p in pending: p.cancel()
                    rows=[]
                    for el in elements:
                        t=el.get("tags") or {}
                        typ=t.get("tourism") or ""
                        if typ not in allowed:
                            continue
                        lat=el.get("lat") or (el.get("center") or {}).get("lat")
                        lon=el.get("lon") or (el.get("center") or {}).get("lon")
                        if lat is None or lon is None:
                            continue
                        rows.append({
                            "id":f'overpass-{el.get("type")}-{el.get("id")}',
                            "name":t.get("name") or typ.replace("_"," ").title(),
                            "type":typ,
                            "lat":float(lat),"lon":float(lon),
                            "website":t.get("website") or t.get("contact:website") or "",
                            "phone":t.get("phone") or t.get("contact:phone") or "",
                            "stars":t.get("stars") or "",
                            "bicycle":t.get("bicycle") or "",
                            "shower":t.get("shower") or "",
                            "toilets":t.get("toilets") or "",
                            "drinking_water":t.get("drinking_water") or "",
                            "power_supply":t.get("power_supply") or t.get("electricity") or "",
                            "tents":t.get("tents") or "",
                            "reservation":t.get("reservation") or "",
                            "fee":t.get("fee") or "",
                            "osm_type":str(el.get("type") or ""),
                            "osm_id":el.get("id"),
                            "source":"Overpass fallback"
                        })
                    return source,rows
                except Exception:
                    pass
        return None,[]
    finally:
        pool.shutdown(wait=False,cancel_futures=True)

@app.post("/api/lodging-nearby")
def lodging_nearby():
    """
    Fast-first accommodation lookup.
    1) Photon reverse POI search (primary, short timeout)
    2) public Overpass only if Photon returns no usable accommodation
    """
    try:
        body=request.get_json(force=True) or {}
        lodging=(body.get("lodging") or "hotel").lower()
        raw_points=body.get("points") or []
        if not raw_points and body.get("lat") is not None and body.get("lon") is not None:
            raw_points=[{"lat":body["lat"],"lon":body["lon"]}]

        points=[]
        for p in raw_points[:4]:
            try:
                points.append((float(p["lat"]),float(p["lon"])))
            except (TypeError,ValueError,KeyError):
                continue
        if not points:
            return jsonify(ok=False,results=[],warning="Kein gültiger Suchpunkt."),400

        key=(tuple((round(lat,3),round(lon,3)) for lat,lon in points[:2]),lodging,"photon-v1")
        cached=_cache_get(_lodging_cache,key,CACHE_TTL_LODGING)
        if cached is not None:
            return jsonify(**cached,cached=True)

        from concurrent.futures import ThreadPoolExecutor, as_completed
        rows=[]
        photon_errors=[]
        with ThreadPoolExecutor(max_workers=min(2,len(points))) as pool:
            futs=[pool.submit(_lodging_photon_point,lat,lon,lodging,10,24) for lat,lon in points[:2]]
            for fut in as_completed(futs):
                try:
                    rows.extend(fut.result())
                except Exception as e:
                    photon_errors.append(type(e).__name__)

        rows=_lodging_dedupe(rows)
        if rows:
            out={
                "ok":True,"results":rows[:20],
                "source":"Photon","fallback_used":False,
                "warning":None
            }
            _cache_set(_lodging_cache,key,out)
            return jsonify(**out)

        source,rows=_lodging_overpass_fallback(points,lodging,9000)
        rows=_lodging_dedupe(rows)
        if rows:
            out={
                "ok":True,"results":rows[:20],
                "source":source or "Overpass fallback","fallback_used":True,
                "warning":"Photon ohne Treffer; OSM-Fallback verwendet."
            }
            _cache_set(_lodging_cache,key,out)
            return jsonify(**out)

        return jsonify(
            ok=True,results=[],source="Photon + OSM fallback",
            fallback_used=True,
            warning="Keine passenden Unterkünfte im Suchbereich gefunden.",
            diagnostics={"photon_errors":photon_errors}
        ),200
    except Exception as e:
        print(f"[LODGING] error {type(e).__name__}: {e}",flush=True)
        return jsonify(ok=False,results=[],warning="Unterkunftssuche derzeit nicht erreichbar."),200

@app.post("/api/lodging-enrich")
def lodging_enrich():
    """
    Optional detail enrichment. The UI never waits for this endpoint before
    showing lodging results.
    """
    try:
        body=request.get_json(force=True) or {}
        items=(body.get("items") or [])[:8]
        node_ids=[];way_ids=[];rel_ids=[]
        for x in items:
            oid=x.get("osm_id")
            typ=str(x.get("osm_type") or "").lower()
            try: oid=int(oid)
            except Exception: continue
            if typ in ("n","node"): node_ids.append(oid)
            elif typ in ("w","way"): way_ids.append(oid)
            elif typ in ("r","relation"): rel_ids.append(oid)
        clauses=[]
        if node_ids: clauses.append(f'node(id:{",".join(map(str,node_ids))});')
        if way_ids: clauses.append(f'way(id:{",".join(map(str,way_ids))});')
        if rel_ids: clauses.append(f'relation(id:{",".join(map(str,rel_ids))});')
        if not clauses:
            return jsonify(ok=True,details=[])

        q='[out:json][timeout:5];('+''.join(clauses)+');out center tags;'
        details=[]
        for url in OVERPASS_ENDPOINTS:
            try:
                r=requests.post(
                    url,data={"data":q},
                    headers={"User-Agent":UA,"Accept":"application/json"},
                    timeout=6
                )
                if not r.ok:
                    continue
                for el in (r.json() or {}).get("elements") or []:
                    t=el.get("tags") or {}
                    details.append({
                        "osm_type":str(el.get("type") or ""),
                        "osm_id":el.get("id"),
                        "website":t.get("website") or t.get("contact:website") or "",
                        "phone":t.get("phone") or t.get("contact:phone") or "",
                        "stars":t.get("stars") or "",
                        "bicycle":t.get("bicycle") or "",
                        "shower":t.get("shower") or "",
                        "toilets":t.get("toilets") or "",
                        "drinking_water":t.get("drinking_water") or "",
                        "power_supply":t.get("power_supply") or t.get("electricity") or "",
                        "tents":t.get("tents") or "",
                        "reservation":t.get("reservation") or "",
                        "fee":t.get("fee") or ""
                    })
                return jsonify(ok=True,details=details,source=url)
            except Exception:
                continue
        return jsonify(ok=True,details=[],warning="Zusatzdetails derzeit nicht erreichbar.")
    except Exception as e:
        print(f"[LODGING-ENRICH] error {type(e).__name__}: {e}",flush=True)
        return jsonify(ok=True,details=[],warning="Zusatzdetails derzeit nicht erreichbar.")


@app.post("/api/osm-supply-batch")
def osm_supply_batch():
    try:
        body=request.get_json(force=True) or {}
        pts=(body.get("points") or [])[:12]
        lodging=(body.get("lodging") or "hotel").lower()
        if not pts:
            return jsonify(ok=False,elements=[]),400
        sleep_regex="hotel|guest_house|hostel|motel|camp_site" if lodging=="mixed" else ("camp_site|caravan_site" if lodging=="camping" else "hotel|guest_house|hostel|motel")
        clauses=[]
        for p in pts:
            lat=float(p["lat"]);lon=float(p["lon"])
            clauses += [
                f'nwr(around:3500,{lat},{lon})["tourism"~"{sleep_regex}"];',
                f'nwr(around:2200,{lat},{lon})["amenity"~"restaurant|cafe|fast_food|drinking_water|bicycle_repair_station"];',
                f'nwr(around:2200,{lat},{lon})["shop"~"supermarket|convenience|bakery|bicycle"];'
            ]
        q='[out:json][timeout:14];('+''.join(clauses)+');out center tags 250;'
        for url in OVERPASS_ENDPOINTS:
            try:
                r=session.post(url,data={"data":q},headers={"User-Agent":UA,"Accept":"application/json"},timeout=17)
                print(f"[OSM-SUPPLY-BATCH] {url} status={r.status_code}",flush=True)
                if r.ok:
                    return jsonify(ok=True,elements=(r.json() or {}).get("elements") or [],source=url)
            except Exception as e:
                print(f"[OSM-SUPPLY-BATCH] {url} failed {e}",flush=True)
        return jsonify(ok=False,elements=[],warning="Versorgungs-Batch derzeit nicht erreichbar."),200
    except Exception as e:
        print(f"[OSM-SUPPLY-BATCH] error {type(e).__name__}: {e}",flush=True)
        return jsonify(ok=False,elements=[],warning="Versorgungs-Batch derzeit nicht erreichbar."),200

@app.post("/api/osm-supply-stage")
def osm_supply_stage():
    try:
        import time
        body=request.get_json(force=True) or {}
        lat=float(body.get("lat"))
        lon=float(body.get("lon"))
        lodging=(body.get("lodging") or "hotel").lower()
        key=(round(lat,3),round(lon,3),lodging)
        cached=SUPPLY_CACHE.get(key)
        if cached and time.time()-cached["ts"] < SUPPLY_CACHE_TTL:
            return jsonify(ok=True,elements=cached["elements"],source="cache",cached=True)

        sleep_regex="hotel|guest_house|hostel|motel|camp_site" if lodging=="mixed" else ("camp_site|caravan_site" if lodging=="camping" else "hotel|guest_house|hostel|motel")

        queries=[
            (
                f'[out:json][timeout:8];('
                f'nwr(around:3200,{lat},{lon})["tourism"~"{sleep_regex}"];'
                f'nwr(around:2200,{lat},{lon})["amenity"~"drinking_water|restaurant|cafe|fast_food|bicycle_repair_station"];'
                f'nwr(around:2200,{lat},{lon})["shop"~"supermarket|convenience|bakery|bicycle"];'
                f');out center tags 80;'
            ),
            (
                f'[out:json][timeout:6];('
                f'nwr(around:2500,{lat},{lon})["tourism"~"{sleep_regex}"];'
                f'nwr(around:1800,{lat},{lon})["amenity"="drinking_water"];'
                f'nwr(around:1800,{lat},{lon})["shop"~"supermarket|convenience"];'
                f');out center tags 50;'
            )
        ]

        for qidx,q in enumerate(queries):
            for url in OVERPASS_ENDPOINTS:
                try:
                    r=session.post(url,data={"data":q},headers={"User-Agent":UA,"Accept":"application/json"},timeout=10 if qidx==0 else 8)
                    print(f"[OSM-SUPPLY-STAGE] q={qidx} {url} status={r.status_code}",flush=True)
                    if r.ok:
                        els=(r.json() or {}).get("elements") or []
                        SUPPLY_CACHE[key]={"ts":time.time(),"elements":els}
                        return jsonify(ok=True,elements=els,source=url,partial=(qidx>0))
                except Exception as e:
                    print(f"[OSM-SUPPLY-STAGE] q={qidx} {url} failed {e}",flush=True)

        return jsonify(ok=False,elements=[],warning="Versorgungsdaten für diese Etappe derzeit nicht erreichbar."),200
    except Exception as e:
        print(f"[OSM-SUPPLY-STAGE] error {type(e).__name__}: {e}",flush=True)
        return jsonify(ok=False,elements=[],warning="Versorgungsdaten derzeit nicht erreichbar."),200


@app.post("/api/osm-supply")
def osm_supply():
    """POI-only query around stage endpoints; deliberately separate from terrain."""
    try:
        body=request.get_json(force=True) or {}
        points=(body.get("points") or [])[:12]
        lodging=(body.get("lodging") or "hotel").lower()
        if not points:return jsonify(ok=False,elements=[]),400
        sleep_regex="hotel|guest_house|hostel|motel|camp_site" if lodging=="mixed" else ("camp_site|caravan_site" if lodging=="camping" else "hotel|guest_house|hostel|motel")
        clauses=[]
        for p in points:
            lat=float(p["lat"]);lon=float(p["lon"])
            clauses += [
                f'nwr(around:5500,{lat},{lon})["tourism"~"{sleep_regex}"];',
                f'nwr(around:4000,{lat},{lon})["amenity"~"restaurant|cafe|fast_food|drinking_water|bicycle_repair_station"];',
                f'nwr(around:4000,{lat},{lon})["shop"~"supermarket|convenience|bakery|bicycle"];'
            ]
        q='[out:json][timeout:18];('+''.join(clauses)+');out center tags;'
        for url in OVERPASS_ENDPOINTS:
            try:
                r=session.post(url,data={"data":q},headers={"User-Agent":UA,"Accept":"application/json"},timeout=20)
                print(f"[OSM-SUPPLY] {url} status={r.status_code}",flush=True)
                if r.ok:
                    return jsonify(ok=True,elements=(r.json() or {}).get("elements") or [],source=url)
            except Exception as e:
                print(f"[OSM-SUPPLY] {url} failed {e}",flush=True)
        return jsonify(ok=False,elements=[],warning="Versorgungsdaten derzeit nicht erreichbar."),200
    except Exception as e:
        print(f"[OSM-SUPPLY] error {type(e).__name__}: {e}",flush=True)
        return jsonify(ok=False,elements=[],warning="Versorgungsdaten derzeit nicht erreichbar."),200

@app.get("/")
def home():
    return jsonify(service="Adventure Bike OS API", status="ok", version="0.93-terrain-visual-v2.1")

@app.get("/health")
def health():
    return jsonify(status="ok")


@app.post("/api/elevation")
def elevation():
    """Retry elevation independently from routing, so a valid route does not lose HM just because the first height lookup failed."""
    try:
        body=request.get_json(force=True) or {}
        coords=body.get("coordinates") or []
        if len(coords)<2:
            return jsonify(ok=False,error="Zu wenige Routenpunkte."),400
        clean=[]
        for c in coords[:5000]:
            if isinstance(c,(list,tuple)) and len(c)>=2:
                clean.append([float(c[0]),float(c[1])])
        enriched,source=add_open_meteo_height(clean)
        if not enriched:
            enriched,source=add_valhalla_height(clean)
        if not enriched:
            return jsonify(ok=False,coordinates=clean,height_source="unavailable"),200
        return jsonify(ok=True,coordinates=enriched,height_source=source or "elevation fallback")
    except Exception as e:
        print(f"[ELEVATION-RETRY] failed: {type(e).__name__}: {e}",flush=True)
        return jsonify(ok=False,error="Höhendaten derzeit nicht verfügbar.",height_source="unavailable"),200

@app.post("/api/stage-candidates")
def stage_candidates():
    try:
        body=request.get_json(force=True) or {}
        points=(body.get("points") or [])[:5]
        if not points:
            points=[{"lat":float(body.get("lat")),"lon":float(body.get("lon")),"route_delta_km":0}]
        seen=set(); candidates=[]
        for p in points:
            lat=float(p["lat"]); lon=float(p["lon"])
            r=session.get("https://nominatim.openstreetmap.org/reverse",params={"lat":lat,"lon":lon,"format":"jsonv2","zoom":10,"addressdetails":1},timeout=20)
            print(f"[STAGE-PLACE] reverse {lat},{lon} status={r.status_code}",flush=True)
            r.raise_for_status(); data=r.json(); a=data.get("address") or {}
            name=a.get("city") or a.get("town") or a.get("village") or a.get("municipality") or a.get("county") or data.get("name")
            if not name or name.casefold() in seen: continue
            seen.add(name.casefold()); candidates.append({
                "name":name,
                "lat":lat,"lon":lon,
                "route_delta_km":round(float(p.get("route_delta_km") or 0),1),
                "route_index":int(p.get("route_index") or 0),
                "place_type":a.get("city") and "city" or a.get("town") and "town" or a.get("village") and "village" or a.get("municipality") and "municipality" or "place",
                "importance":round(float(data.get("importance") or 0),4),
                "display_name":data.get("display_name") or name,
                "source":"Nominatim"
            })
            if len(candidates)>=3: break
        return jsonify(candidates=candidates)
    except (TypeError,ValueError,KeyError): return jsonify(error="Ungültige Koordinaten."),400
    except requests.RequestException as ex:
        print(f"[STAGE-PLACE] ERROR: {type(ex).__name__}: {ex}",flush=True)
        return jsonify(candidates=[],warning="Etappenort-Suche derzeit nicht verfügbar."),200

@app.post("/api/reverse")
def reverse():
    """Resolve a route coordinate to a nearby town/city label for stage naming."""
    try:
        body = request.get_json(force=True) or {}
        lat = float(body.get("lat"))
        lon = float(body.get("lon"))
        zoom = int(body.get("zoom") or 10)

        r = session.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={
                "lat": lat,
                "lon": lon,
                "format": "jsonv2",
                "zoom": zoom,
                "addressdetails": 1
            },
            timeout=20
        )
        print(f"[REVERSE] {lat},{lon} status={r.status_code}", flush=True)
        r.raise_for_status()
        data = r.json()
        address = data.get("address", {})

        name = (
            address.get("city")
            or address.get("town")
            or address.get("village")
            or address.get("municipality")
            or address.get("county")
            or data.get("name")
            or data.get("display_name")
            or "Etappenort"
        )

        return jsonify({
            "name": name,
            "display_name": data.get("display_name", name),
            "lat": lat,
            "lon": lon
        })
    except (TypeError, ValueError):
        return jsonify(error="Ungültige Koordinaten."), 400
    except requests.RequestException as e:
        print(f"[REVERSE] ERROR: {type(e).__name__}: {e}", flush=True)
        return jsonify(error="Ortsname konnte nicht ermittelt werden."), 502


@app.post("/api/weather")
def weather():
    """Optional per-stage weather. Never blocks route planning."""
    try:
        body=request.get_json(force=True) or {}
        points=(body.get("points") or [])[:10]
        date=(body.get("date") or "").strip()
        dates=(body.get("dates") or [])[:10]
        if not points or (not date and not dates):
            return jsonify(available=False, reason="Kein Reisedatum oder keine Etappenpunkte angegeben.", results=[])

        from datetime import date as _date, datetime as _dt
        def parse_date(s):
            try:
                return _dt.strptime(s,"%Y-%m-%d").date()
            except Exception:
                return None

        today=_date.today()
        targets=[]
        for i,_p in enumerate(points):
            s=(dates[i] if i < len(dates) else date) or date
            d=parse_date(s)
            targets.append((s,d))

        if any(d is None for _s,d in targets):
            return jsonify(available=False, reason="Ungültiges Reisedatum.", results=[])

        results=[]
        for pi,p in enumerate(points):
            target_str,target_date=targets[pi]
            delta=(target_date-today).days
            if delta < 0 or delta > 15:
                results.append({"available":False,"date":target_str}); continue
            lat=float(p["lat"]); lon=float(p["lon"])
            params={
                "latitude":lat,
                "longitude":lon,
                "daily":"temperature_2m_max,temperature_2m_min,precipitation_probability_max,wind_speed_10m_max",
                "timezone":"auto",
                "forecast_days":16
            }
            r=session.get("https://api.open-meteo.com/v1/forecast",params=params,timeout=20)
            print(f"[WEATHER] {lat},{lon} target={target_str} delta={delta} status={r.status_code}",flush=True)
            if not r.ok:
                results.append({"available":False}); continue
            d=r.json().get("daily") or {}
            times=d.get("time") or []
            if target_str not in times:
                results.append({"available":False}); continue
            i=times.index(target_str)
            def pick(key):
                vals=d.get(key) or []
                return vals[i] if i < len(vals) else None
            results.append({
                "available":True,
                "date":target_str,
                "tmax":pick("temperature_2m_max"),
                "tmin":pick("temperature_2m_min"),
                "rain":pick("precipitation_probability_max"),
                "wind":pick("wind_speed_10m_max")
            })
        return jsonify(
            available=any(x.get("available") for x in results),
            reason=None if any(x.get("available") for x in results) else "Wetterdienst lieferte für das gewählte Datum keine Etappenprognose.",
            results=results
        )
    except Exception as e:
        print(f"[WEATHER] ERROR: {type(e).__name__}: {e}",flush=True)
        return jsonify(available=False,reason="Wetterdaten derzeit nicht verfügbar.",results=[]),200


def _route_coord_distance_m(a,b):
    import math
    lat1,lon1=float(a[1]),float(a[0])
    lat2,lon2=float(b[1]),float(b[0])
    R=6371000.0
    p1,p2=math.radians(lat1),math.radians(lat2)
    dp=math.radians(lat2-lat1);dl=math.radians(lon2-lon1)
    q=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*R*math.asin(min(1.0,math.sqrt(q)))

def _nearest_route_indices(coords, points):
    out=[]
    start=0
    for p in points[1:]:
        target=[float(p["lon"]),float(p["lat"])]
        best_i=start
        best_d=None
        for i in range(start,len(coords)):
            try:
                d=_route_coord_distance_m(coords[i],target)
            except Exception:
                continue
            if best_d is None or d<best_d:
                best_d=d;best_i=i
        out.append(best_i)
        start=min(len(coords)-1,best_i+1)
    if out:
        out[-1]=len(coords)-1
    return out

def _brouter_via(points, profile="trekking"):
    lonlats="|".join(f'{float(p["lon"])},{float(p["lat"])}' for p in points)
    r=session.get(
        "https://brouter.de/brouter",
        params={"lonlats":lonlats,"profile":profile,"alternativeidx":0,"format":"geojson"},
        timeout=32
    )
    print(f"[ROUTE-VIA] BRouter status={r.status_code} points={len(points)}",flush=True)
    r.raise_for_status()
    data=r.json()
    f=(data.get("features") or [data])[0] if isinstance(data,dict) else data
    coords=((f or {}).get("geometry") or {}).get("coordinates") or []
    if len(coords)<2:
        raise ValueError("BRouter lieferte keine Via-Geometrie")
    return f

@app.post("/api/route-via")
def route_via():
    """
    Route through explicit stage-end waypoints.
    Used when an accommodation becomes the real end point of a day.
    """
    try:
        body=request.get_json(force=True) or {}
        raw=(body.get("points") or [])[:10]
        profile=body.get("profile") or "trekking"
        points=[]
        for p in raw:
            try:
                points.append({"lat":float(p["lat"]),"lon":float(p["lon"])})
            except (TypeError,ValueError,KeyError):
                continue
        if len(points)<2:
            return jsonify(error="Mindestens Start und Ziel sind erforderlich."),400

        key=("via",profile)+tuple((round(p["lat"],5),round(p["lon"],5)) for p in points)
        cached=_cache_get(_route_cache,key,CACHE_TTL_ROUTE)
        if cached is not None:
            cached["properties"]["cached"]=True
            return jsonify(cached)

        routing_source="BRouter via"
        try:
            f=_brouter_via(points,profile)
            coords=(f.get("geometry") or {}).get("coordinates") or []
            leg_end_indices=_nearest_route_indices(coords,points)
        except Exception as e:
            print(f"[ROUTE-VIA] BRouter failed {type(e).__name__}: {e}; using leg fallback",flush=True)
            routing_source="multi-engine leg fallback"
            coords=[]
            leg_end_indices=[]
            properties={}
            for i in range(len(points)-1):
                feature,source=race_route(points[i],points[i+1],profile)
                ff=feature["features"][0] if isinstance(feature,dict) and "features" in feature else feature
                leg=((ff or {}).get("geometry") or {}).get("coordinates") or []
                if len(leg)<2:
                    raise ValueError(f"Keine Geometrie für Via-Abschnitt {i+1}")
                if coords and coords[-1][:2]==leg[0][:2]:
                    leg=leg[1:]
                coords.extend(leg)
                leg_end_indices.append(len(coords)-1)
                properties.update((ff or {}).get("properties") or {})
            f={"geometry":{"type":"LineString","coordinates":coords},"properties":properties}

        result={
            "geometry":{"type":"LineString","coordinates":coords},
            "properties":{
                **((f or {}).get("properties") or {}),
                "routing_source":routing_source,
                "cached":False,
                "via_count":max(0,len(points)-2)
            },
            "leg_end_indices":leg_end_indices
        }
        _cache_set(_route_cache,key,result)
        return jsonify(result)
    except requests.RequestException as e:
        print(f"[ROUTE-VIA] EXTERNAL ERROR: {type(e).__name__}: {e}",flush=True)
        return jsonify(error="Route über Unterkunft konnte gerade nicht berechnet werden.",detail=str(e)[:500]),502
    except Exception as e:
        print(f"[ROUTE-VIA] INTERNAL ERROR: {type(e).__name__}: {e}",flush=True)
        return jsonify(error="Route über Unterkunft konnte nicht berechnet werden.",detail=f"{type(e).__name__}: {str(e)[:500]}"),500


@app.post("/api/route")
def route():
    try:
        body=request.get_json(force=True) or {}
        start=(body.get("start") or "").strip();dest=(body.get("destination") or "").strip()
        profile=body.get("profile") or "trekking"
        if not start or not dest:return jsonify(error="Start und Ziel sind erforderlich."),400

        def provided(prefix,text):
            try:
                lat=body.get(prefix+"_lat");lon=body.get(prefix+"_lon")
                if lat is None or lon is None:return None
                return {"lat":float(lat),"lon":float(lon),"name":body.get(prefix+"_name") or text}
            except Exception:return None

        a=provided("start",start);b=provided("destination",dest)
        text_key=(start.casefold(),dest.casefold(),profile)
        cached_text=_cache_get(_route_cache,("text",)+text_key,CACHE_TTL_ROUTE)
        if cached_text is not None and not (a and b):
            cached_text["properties"]["cached"]=True
            cached_text["properties"]["cache_reason"]="same start/destination/profile"
            return jsonify(cached_text)

        if a is None:
            a=geocode(start)
            print(f"[ROUTE-GEOCODE] start via cached/Photon fallback: {a['name']}",flush=True)
        if b is None:
            b=geocode(dest)
            print(f"[ROUTE-GEOCODE] destination via cached/Photon fallback: {b['name']}",flush=True)
        coord_key=("coords",round(a["lat"],5),round(a["lon"],5),round(b["lat"],5),round(b["lon"],5),profile)
        cached=_cache_get(_route_cache,coord_key,CACHE_TTL_ROUTE)
        if cached is not None:
            cached["properties"]["cached"]=True
            return jsonify(cached)

        print(f"[ROUTE] {start!r}->{dest!r} profile={profile} coords-ready",flush=True)
        feature,routing_source=race_route(a,b,profile)
        f=feature["features"][0] if "features" in feature else feature
        result={"start":a,"destination":b,"geometry":f.get("geometry"),
                "properties":{**f.get("properties",{}),"routing_source":routing_source,"cached":False}}
        _cache_set(_route_cache,coord_key,result)
        _cache_set(_route_cache,("text",)+text_key,result)
        return jsonify(result)
    except ValueError as e:
        return jsonify(error=str(e)),404
    except requests.RequestException as e:
        print(f"[ROUTE] EXTERNAL ERROR: {type(e).__name__}: {e}",flush=True)
        return jsonify(error="Externer Dienst antwortet gerade nicht.",detail=str(e)[:800]),502
    except Exception as e:
        print(f"[ROUTE] INTERNAL ERROR: {type(e).__name__}: {e}",flush=True)
        return jsonify(error="Route konnte nicht berechnet werden.",detail=f"{type(e).__name__}: {str(e)[:500]}"),500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
