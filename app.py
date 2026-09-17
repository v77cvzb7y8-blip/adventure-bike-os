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

UA = "AdventureBikeOS-MVP/0.5 (prototype; GitHub: v77cvzb7y8-blip/adventure-bike-os)"
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
    try:
        r = session.get(url, params=params, timeout=90)
        print(f"[BROUTER] status={r.status_code} content-type={r.headers.get('content-type')}", flush=True)
        if not r.ok:
            print(f"[BROUTER] response={r.text[:1000]}", flush=True)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        print(f"[BROUTER] REQUEST ERROR: {type(e).__name__}: {e}", flush=True)
        raise
    except ValueError as e:
        print(f"[BROUTER] JSON ERROR: {e}; body={r.text[:1000]}", flush=True)
        raise

@app.get("/")
def home():
    return jsonify(service="Adventure Bike OS API", status="ok", version="0.5-overnight-candidates")

@app.get("/health")
def health():
    return jsonify(status="ok")



def _place_label(tags):
    return tags.get("name") or tags.get("name:de") or tags.get("official_name")

@app.post("/api/stage-candidates")
def stage_candidates():
    try:
        body=request.get_json(force=True) or {}
        lat=float(body.get("lat")); lon=float(body.get("lon"))
        radius=max(3000,min(int(body.get("radius") or 12000),20000))
        query=f"""[out:json][timeout:25];(
        nwr["place"~"city|town|village"](around:{radius},{lat},{lon});
        nwr["tourism"~"hotel|hostel|guest_house"](around:{radius},{lat},{lon});
        nwr["shop"="supermarket"](around:{radius},{lat},{lon});
        nwr["amenity"~"restaurant|cafe"](around:{radius},{lat},{lon});
        nwr["shop"="bicycle"](around:{radius},{lat},{lon});
        );out center tags;"""
        r=session.post("https://overpass-api.de/api/interpreter",data={"data":query},timeout=45)
        print(f"[CANDIDATES] {lat},{lon} status={r.status_code}",flush=True); r.raise_for_status()
        elements=r.json().get("elements",[]); settlements=[]; amenities=[]
        for el in elements:
            tags=el.get("tags",{}); center=el.get("center") or {}
            plat=el.get("lat",center.get("lat")); plon=el.get("lon",center.get("lon"))
            if plat is None or plon is None: continue
            item={"lat":float(plat),"lon":float(plon),"tags":tags}
            if tags.get("place") in ("city","town","village") and _place_label(tags):
                item.update(name=_place_label(tags),place=tags.get("place")); settlements.append(item)
            else: amenities.append(item)
        import math
        def km(a,b,c,d):
            R=6371.; p1=math.radians(a); p2=math.radians(c); dp=math.radians(c-a); dl=math.radians(d-b)
            x=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
            return 2*R*math.asin(math.sqrt(x))
        scored=[]
        for s in settlements:
            d=km(lat,lon,s["lat"],s["lon"]); counts={"sleep":0,"food":0,"supermarket":0,"bike":0}
            for a in amenities:
                if km(s["lat"],s["lon"],a["lat"],a["lon"])>4: continue
                t=a["tags"]
                if t.get("tourism") in ("hotel","hostel","guest_house"): counts["sleep"]+=1
                if t.get("amenity") in ("restaurant","cafe"): counts["food"]+=1
                if t.get("shop")=="supermarket": counts["supermarket"]+=1
                if t.get("shop")=="bicycle": counts["bike"]+=1
            score={"city":4,"town":3,"village":1}.get(s["place"],0)+min(counts["sleep"],3)*3+min(counts["food"],3)*2+min(counts["supermarket"],2)*2+min(counts["bike"],1)*2-d*.75
            scored.append({"name":s["name"],"place":s["place"],"distance_km":round(d,1),"amenities":counts,"score":round(score,2)})
        scored.sort(key=lambda x:x["score"],reverse=True)
        return jsonify(candidates=scored[:5])
    except (TypeError,ValueError): return jsonify(error="Ungültige Koordinaten."),400
    except requests.RequestException as e:
        print(f"[CANDIDATES] ERROR: {type(e).__name__}: {e}",flush=True)
        return jsonify(error="Etappenorte konnten derzeit nicht recherchiert werden."),502


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

        feature = brouter(a, b, profile)
        f = feature["features"][0] if "features" in feature else feature

        print("[ROUTE] success", flush=True)
        return jsonify({
            "start": a,
            "destination": b,
            "geometry": f.get("geometry"),
            "properties": f.get("properties", {})
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
