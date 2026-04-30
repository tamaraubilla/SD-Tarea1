from flask import Flask, request, jsonify
import csv, math, time, os, requests, random

DATA_CSV = os.getenv("DATA_CSV", "/data/open_buildings.csv")

app = Flask(__name__)

METRICS_URL = os.getenv("METRICS_URL", "http://metrics_service:8003")

ZONES = {
    "Z1": {"lat_min": -33.445, "lat_max": -33.420, "lon_min": -70.640, "lon_max": -70.600},
    "Z2": {"lat_min": -33.420, "lat_max": -33.390, "lon_min": -70.600, "lon_max": -70.550},
    "Z3": {"lat_min": -33.530, "lat_max": -33.490, "lon_min": -70.790, "lon_max": -70.740},
    "Z4": {"lat_min": -33.460, "lat_max": -33.430, "lon_min": -70.670, "lon_max": -70.630},
    "Z5": {"lat_min": -33.470, "lat_max": -33.430, "lon_min": -70.810, "lon_max": -70.760},
}

def zone_area_km2(zone_id):
    zone = ZONES[zone_id]
    lat_diff = abs(zone["lat_max"] - zone["lat_min"]) * 111.0
    lon_diff = abs(zone["lon_max"] - zone["lon_min"]) * 111.0 * math.cos(math.radians((zone["lat_max"] + zone["lat_min"]) / 2))
    return lat_diff * lon_diff

def load_from_csv(path):
    data = {z: [] for z in ZONES}
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                lat = float(row["latitude"])
                lon = float(row["longitude"])
                area = float(row["area_in_meters"])
                conf = float(row["confidence"])
            except (KeyError, ValueError):
                continue
            for zone_id, zone in ZONES.items():
                if zone["lat_min"] <= lat <= zone["lat_max"] and zone["lon_min"] <= lon <= zone["lon_max"]:
                    data[zone_id].append({
                        "latitude": lat,
                        "longitude": lon,
                        "area_in_meters": area,
                        "confidence": conf,
                    })
                    break
    return data

def generate_synthetic_data():
    data = {}
    for zone_id in ZONES:
        zone = ZONES[zone_id]
        records = []
        n = random.randint(800, 2500)
        for _ in range(n):
            records.append({
                "latitude": random.uniform(zone["lat_min"], zone["lat_max"]),
                "longitude": random.uniform(zone["lon_min"], zone["lon_max"]),
                "area_in_meters": random.lognormvariate(4.5, 0.8),
                "confidence": random.betavariate(5, 2),
            })
        data[zone_id] = records
    return data

print("Loading dataset into memory...")
if os.path.exists(DATA_CSV):
    print(f"  Found CSV: {DATA_CSV}")
    DATA = load_from_csv(DATA_CSV)
    print(f"  Loaded real data: { {z: len(r) for z, r in DATA.items()} }")
else:
    print(f"  [WARNING] {DATA_CSV} not found. Using synthetic data.")
    DATA = generate_synthetic_data()
ZONE_AREAS = {}
for zid in ZONES:
    ZONE_AREAS[zid] = zone_area_km2(zid)
print(f"Dataset ready. Zones: { {z: len(r) for z, r in DATA.items()} }")

def q1_count(zone_id, min_confidence=0.0):
    count = 0
    for r in DATA[zone_id]:
        if r["confidence"] >= min_confidence:
            count = count + 1
    return count

def q2_area(zone_id, min_confidence=0.0):
    areas = []
    for r in DATA[zone_id]:
        if r["confidence"] >= min_confidence:
            areas.append(r["area_in_meters"])
    if not areas:
        return {"avg_area": 0, "total_area": 0, "n": 0}
    total_area = 0
    for area in areas:
        total_area = total_area + area
    avg_area = total_area / len(areas)
    return {"avg_area": avg_area, "total_area": total_area, "n": len(areas)}

def q3_density(zone_id, min_confidence=0.0):
    count = q1_count(zone_id, min_confidence)
    return count / ZONE_AREAS[zone_id]

def q4_compare(zone_a, zone_b, min_confidence=0.0):
    da = q3_density(zone_a, min_confidence)
    db = q3_density(zone_b, min_confidence)
    if da > db:
        winner = zone_a
    else:
        winner = zone_b
    return {"zone_a": da, "zone_b": db, "winner": winner}

def q5_confidence_distribution(zone_id, bins=5):
    scores = []
    for r in DATA[zone_id]:
        scores.append(r["confidence"])
    step = 1.0 / bins
    edges = []
    for i in range(bins + 1):
        edges.append(i * step)
    counts = []
    for i in range(bins):
        counts.append(0)
    for s in scores:
        idx = int(s / step)
        if idx > bins - 1:
            idx = bins - 1
        counts[idx] = counts[idx] + 1
    result = []
    for i in range(bins):
        bucket = {"bucket": i, "min": edges[i], "max": edges[i+1], "count": counts[i]}
        result.append(bucket)
    return result

def handle_q1(params):
    return q1_count(params["zone_id"], params.get("confidence_min", 0.0))

def handle_q2(params):
    return q2_area(params["zone_id"], params.get("confidence_min", 0.0))

def handle_q3(params):
    return q3_density(params["zone_id"], params.get("confidence_min", 0.0))

def handle_q4(params):
    return q4_compare(params["zone_a"], params["zone_b"], params.get("confidence_min", 0.0))

def handle_q5(params):
    return q5_confidence_distribution(params["zone_id"], params.get("bins", 5))

QUERY_MAP = {
    "Q1": handle_q1,
    "Q2": handle_q2,
    "Q3": handle_q3,
    "Q4": handle_q4,
    "Q5": handle_q5,
}

@app.route("/query", methods=["POST"])
def handle_query():
    body = request.get_json()
    query_type = body.get("query_type")
    params = body.get("params", {})

    if query_type not in QUERY_MAP:
        return jsonify({"error": "Unknown query type"}), 400

    t0 = time.time()
    time.sleep(random.uniform(0.01, 0.05))
    result = QUERY_MAP[query_type](params)
    latency = (time.time() - t0) * 1000

    try:
        requests.post(f"{METRICS_URL}/record", json={
            "event": "miss_processed",
            "query_type": query_type,
            "latency_ms": latency,
        }, timeout=0.5)
    except Exception:
        pass

    return jsonify({"result": result, "latency_ms": latency})

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8002)
