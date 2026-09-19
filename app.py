import os, time
import requests
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app, origins=[
    "https://v77cvzb7y8-blip.github.io",
    "http://localhost:*",
    "http://127.0.0.1:*"
])

UA = "AdventureBikeOS-MVP/0.34 (prototype; GitHub: v77cvzb7y8-blip/adventure-bike-os)"
session = requests.Session()
session.headers.update({"User-Agent": UA, "Accept": "application/json"})

def geocode(q):
    url = "https://nominatim.openstreetmap.org/search"
    print(f"[GEOCODE] {q}", flush=True)
    r = session.get(url, params={"q": q, "format": "jsonv2", "limit": 1}, timeout=20)
    print(f"[GEOCODE] status={r.status_code}", flush=True)
    r.raise_for_status()
    data = r.json()
    if not data:
        raise ValueError(f"Ort nicht gefunden: {q}")
    return {
        "lat": float(data[0]["lat"]),
        "lon": float(data[0]["lon"]),
        "name": data[0].get("display_name", q)
    }

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
    r=session.post("https://valhalla.openstreetmap.de/route",json=payload,headers=headers,timeout=22)
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
        hr=session.post("https://valhalla.openstreetmap.de/height",json=hreq,headers=headers,timeout=18)
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
        r=requests.post("https://valhalla.openstreetmap.de/height",json=req,headers={"X-Client-Id":"adventure-bike-os-prototype"},timeout=15)
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
    segments=max(3,min(6,math.ceil(straight/180)))
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
    with ThreadPoolExecutor(max_workers=min(segments,4)) as pool:
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

def race_route(a, b, profile="trekking"):
    """Race BRouter and Valhalla; if both fail, use OSRM Bike as a third independent fallback."""
    from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
    pool=ThreadPoolExecutor(max_workers=2)
    futures={
        pool.submit(brouter,a,b,profile):"BRouter",
        pool.submit(valhalla_route,a,b):"Valhalla"
    }
    errors=[]
    try:
        pending=set(futures)
        while pending:
            done,pending=wait(pending,timeout=24,return_when=FIRST_COMPLETED)
            if not done:
                break
            for fut in done:
                source=futures[fut]
                try:
                    feature=fut.result()
                    print(f"[ROUTE-RACE] success source={source}",flush=True)
                    for p in pending:
                        p.cancel()
                    return ensure_route_elevation(feature),source
                except Exception as e:
                    errors.append(f"{source}: {type(e).__name__}: {e}")
                    print(f"[ROUTE-RACE] {source} failed: {e}",flush=True)
    finally:
        pool.shutdown(wait=False,cancel_futures=True)

    print(f"[ROUTE-RACE] primary engines failed, trying OSRM Bike. errors={errors}",flush=True)
    try:
        feature=osrm_bike_route(a,b)
        print("[ROUTE-RACE] success source=OSRM Bike",flush=True)
        return ensure_route_elevation(feature),"OSRM Bike"
    except Exception as e:
        errors.append(f"OSRM Bike: {type(e).__name__}: {e}")
        print(f"[ROUTE-RACE] OSRM Bike failed: {e}",flush=True)

    print("[ROUTE-RACE] trying segmented OSRM Bike fallback",flush=True)
    try:
        feature=osrm_bike_segmented(a,b)
        print("[ROUTE-RACE] success source=OSRM Bike segmented",flush=True)
        return ensure_route_elevation(feature),"OSRM Bike segmented"
    except Exception as e:
        errors.append(f"OSRM Bike segmented: {type(e).__name__}: {e}")
        print(f"[ROUTE-RACE] segmented OSRM failed: {e}",flush=True)
        raise requests.RequestException(" | ".join(errors))



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

@app.get("/")
def home():
    return jsonify(service="Adventure Bike OS API", status="ok", version="0.34-independent-pack-route-7.7.0")

@app.get("/health")
def health():
    return jsonify(status="ok")



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
        if not points or not date:
            return jsonify(available=False, reason="Kein Reisedatum oder keine Etappenpunkte angegeben.", results=[])

        from datetime import date as _date, datetime as _dt
        try:
            trip_date=_dt.strptime(date,"%Y-%m-%d").date()
        except ValueError:
            return jsonify(available=False, reason="Ungültiges Reisedatum.", results=[])

        today=_date.today()
        delta=(trip_date-today).days
        # Open-Meteo's useful forecast window can vary. Treat near-term dates as forecast,
        # longer horizons as planning-only rather than returning a misleading error.
        if delta < 0:
            return jsonify(available=False, reason="Das Reisedatum liegt in der Vergangenheit.", results=[])
        if delta > 15:
            return jsonify(available=False, reason="Für dieses Datum ist noch keine belastbare Kurzfristprognose verfügbar.", results=[])

        results=[]
        for p in points:
            lat=float(p["lat"]); lon=float(p["lon"])
            params={
                "latitude":lat,
                "longitude":lon,
                "daily":"temperature_2m_max,temperature_2m_min,precipitation_probability_max,wind_speed_10m_max",
                "timezone":"auto",
                "forecast_days":16
            }
            r=session.get("https://api.open-meteo.com/v1/forecast",params=params,timeout=20)
            print(f"[WEATHER] {lat},{lon} target={date} delta={delta} status={r.status_code}",flush=True)
            if not r.ok:
                results.append({"available":False}); continue
            d=r.json().get("daily") or {}
            times=d.get("time") or []
            if date not in times:
                results.append({"available":False}); continue
            i=times.index(date)
            def pick(key):
                vals=d.get(key) or []
                return vals[i] if i < len(vals) else None
            results.append({
                "available":True,
                "date":date,
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
        body = request.get_json(force=True) or {}
        start = (body.get("start") or "").strip()
        dest = (body.get("destination") or "").strip()
        profile = body.get("profile") or "trekking"

        print(f"[ROUTE] start={start!r} destination={dest!r} profile={profile!r}", flush=True)

        if not start or not dest:
            return jsonify(error="Start und Ziel sind erforderlich."), 400

        a = geocode(start)
        time.sleep(1.05)
        b = geocode(dest)
        print(f"[ROUTE] geocoded start={a} destination={b}", flush=True)

        feature, routing_source = race_route(a, b, profile)
        f = feature["features"][0] if "features" in feature else feature

        print(f"[ROUTE] success source={routing_source}", flush=True)
        return jsonify({
            "start": a,
            "destination": b,
            "geometry": f.get("geometry"),
            "properties": {**f.get("properties", {}), "routing_source": routing_source}
        })

    except ValueError as e:
        print(f"[ROUTE] VALUE ERROR: {e}", flush=True)
        return jsonify(error=str(e)), 404
    except requests.RequestException as e:
        print(f"[ROUTE] EXTERNAL ERROR: {type(e).__name__}: {e}", flush=True)
        return jsonify(
            error="Externer Routingdienst derzeit nicht erreichbar.",
            detail=f"{type(e).__name__}: {str(e)[:500]}"
        ), 502
    except Exception as e:
        print(f"[ROUTE] INTERNAL ERROR: {type(e).__name__}: {e}", flush=True)
        return jsonify(
            error="Route konnte nicht berechnet werden.",
            detail=f"{type(e).__name__}: {str(e)[:500]}"
        ), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
