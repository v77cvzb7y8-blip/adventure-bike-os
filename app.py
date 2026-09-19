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

UA = "AdventureBikeOS-MVP/0.73 (prototype; GitHub: v77cvzb7y8-blip/adventure-bike-os)"
session = requests.Session()
session.headers.update({"User-Agent": UA, "Accept": "application/json"})

CACHE_TTL_ROUTE = 6 * 3600
CACHE_TTL_PLACE = 24 * 3600
CACHE_TTL_TRANSPORT = 2 * 3600
_route_cache = {}
_place_cache = {}
_transport_cache = {}
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

    # Nominatim is only a fallback now. A 429 here must never break routing.
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

    # Sample the route for elevation to keep payload manageable.
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
    # Haversine distance for choosing segment count.
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
            # keep useful variety
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


@app.post("/api/osm-terrain")
def osm_terrain():
    """Fast, narrow terrain-only query around sampled route points."""
    try:
        body=request.get_json(force=True) or {}
        samples=(body.get("samples") or [])[:42]
        if not samples:return jsonify(ok=False,elements=[]),400
        clauses=[]
        for p in samples:
            lat=float(p["lat"]);lon=float(p["lon"])
            clauses.append(
                f'way(around:90,{lat},{lon})["highway"];'
            )
        q='[out:json][timeout:16];('+''.join(clauses)+');out tags center;'
        for url in OVERPASS_ENDPOINTS:
            try:
                r=session.post(url,data={"data":q},headers={"User-Agent":UA,"Accept":"application/json"},timeout=18)
                print(f"[OSM-TERRAIN] {url} status={r.status_code}",flush=True)
                if r.ok:
                    return jsonify(ok=True,elements=(r.json() or {}).get("elements") or [],source=url)
            except Exception as e:
                print(f"[OSM-TERRAIN] {url} failed {e}",flush=True)
        return jsonify(ok=False,elements=[],warning="Terrain-Zusatzdaten derzeit nicht erreichbar."),200
    except Exception as e:
        print(f"[OSM-TERRAIN] error {type(e).__name__}: {e}",flush=True)
        return jsonify(ok=False,elements=[],warning="Terrain-Zusatzdaten derzeit nicht erreichbar."),200

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
    return jsonify(service="Adventure Bike OS API", status="ok", version="0.73-terrain-supply-stages-8.2.3")

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
        # Text route cache can survive temporary geocoder problems.
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
