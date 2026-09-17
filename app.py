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

UA = "AdventureBikeOS-MVP/0.3 (prototype; GitHub: v77cvzb7y8-blip/adventure-bike-os)"
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
    return jsonify(service="Adventure Bike OS API", status="ok", version="0.3-brouter-endpoint-fix")

@app.get("/health")
def health():
    return jsonify(status="ok")

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
