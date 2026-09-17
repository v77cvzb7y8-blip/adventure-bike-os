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

UA = "AdventureBikeOS-MVP/0.7 (prototype; GitHub: v77cvzb7y8-blip/adventure-bike-os)"
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
    return jsonify(service="Adventure Bike OS API", status="ok", version="0.7-stage-optimizer")

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
            seen.add(name.casefold()); candidates.append({"name":name,"lat":lat,"lon":lon,"route_delta_km":round(float(p.get("route_delta_km") or 0),1),"route_index":int(p.get("route_index") or 0),"source":"Nominatim"})
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
