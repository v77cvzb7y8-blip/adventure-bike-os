import math, os, time
import requests
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app, origins=[
    "https://v77cvzb7y8-blip.github.io",
    "http://localhost:*",
    "http://127.0.0.1:*"
])

UA = "AdventureBikeOS-MVP/0.1 (prototype; GitHub: v77cvzb7y8-blip/adventure-bike-os)"
session = requests.Session()
session.headers.update({"User-Agent": UA, "Accept": "application/json"})

def geocode(q):
    r=session.get("https://nominatim.openstreetmap.org/search",
        params={"q":q,"format":"jsonv2","limit":1}, timeout=20)
    r.raise_for_status()
    data=r.json()
    if not data:
        raise ValueError(f"Ort nicht gefunden: {q}")
    return {"lat":float(data[0]["lat"]), "lon":float(data[0]["lon"]),
            "name":data[0].get("display_name",q)}

def brouter(a,b,profile="trekking"):
    params={
      "lonlats":f'{a["lon"]},{a["lat"]}|{b["lon"]},{b["lat"]}',
      "profile":profile,
      "alternativeidx":0,
      "format":"geojson"
    }
    r=session.get("https://brouter.de/brouter-web/brouter",params=params,timeout=90)
    r.raise_for_status()
    data=r.json()
    f=data["features"][0] if "features" in data else data
    return f

@app.get("/")
def home():
    return jsonify(service="Adventure Bike OS API", status="ok")

@app.get("/health")
def health():
    return jsonify(status="ok")

@app.post("/api/route")
def route():
    try:
        body=request.get_json(force=True) or {}
        start=(body.get("start") or "").strip()
        dest=(body.get("destination") or "").strip()
        profile=body.get("profile") or "trekking"
        if not start or not dest:
            return jsonify(error="Start und Ziel sind erforderlich."),400
        a=geocode(start)
        time.sleep(1.05)  # respect public Nominatim rate limit
        b=geocode(dest)
        feature=brouter(a,b,profile)
        return jsonify({
          "start":a, "destination":b,
          "geometry":feature.get("geometry"),
          "properties":feature.get("properties",{})
        })
    except ValueError as e:
        return jsonify(error=str(e)),404
    except requests.RequestException as e:
        return jsonify(error="Externer Routingdienst derzeit nicht erreichbar.",
                       detail=str(e)[:300]),502
    except Exception as e:
        return jsonify(error="Route konnte nicht berechnet werden.",
                       detail=str(e)[:300]),500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
