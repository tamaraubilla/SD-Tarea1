import requests, random, time, os, math, argparse, json
from collections import Counter

URL_CACHE = os.getenv("CACHE_URL", "http://cache_service:8001")
METRICS_URL = os.getenv("METRICS_URL", "http://metrics_service:8003")

ZONES = ["Z1", "Z2", "Z3", "Z4", "Z5"]
QUERY_TYPES = ["Q1", "Q2", "Q3", "Q4", "Q5"]
CONFIDENCE_LEVELS = [0.0, 0.5, 0.7, 0.9]

def zipf_weights(n, s=1.2):
    weights = []
    for i in range(1, n + 1):
        weight = 1.0 / (i ** s)
        weights.append(weight)
    total = 0
    for weight in weights:
        total = total + weight
    normalized_weights = []
    for weight in weights:
        normalized_weight = weight / total
        normalized_weights.append(normalized_weight)
    return normalized_weights

ZONE_ZIPF_WEIGHTS = zipf_weights(len(ZONES))
QUERY_ZIPF_WEIGHTS = zipf_weights(len(QUERY_TYPES))

def choose_zipf(items, weights):
    return random.choices(items, weights=weights, k=1)[0]

def choose_uniform(items):
    return random.choice(items)

def build_query(query_type, zone_id, distribution):
    confidence = random.choice(CONFIDENCE_LEVELS)

    if query_type == "Q1":
        return {"query_type": "Q1", "params": {"zone_id": zone_id, "confidence_min": confidence}}
    elif query_type == "Q2":
        return {"query_type": "Q2", "params": {"zone_id": zone_id, "confidence_min": confidence}}
    elif query_type == "Q3":
        return {"query_type": "Q3", "params": {"zone_id": zone_id, "confidence_min": confidence}}
    elif query_type == "Q4":
        other_zones = []
        for z in ZONES:
            if z != zone_id:
                other_zones.append(z)
        if distribution == "zipf":
            zone_b = choose_zipf(other_zones, zipf_weights(len(other_zones)))
        else:
            zone_b = choose_uniform(other_zones)
        return {"query_type": "Q4", "params": {"zone_a": zone_id, "zone_b": zone_b, "confidence_min": confidence}}
    elif query_type == "Q5":
        bins = random.choice([5, 10])
        return {"query_type": "Q5", "params": {"zone_id": zone_id, "bins": bins}}

def run(distribution, total_queries, rate_qps):
    print(f"[TrafficGen] Starting: distribution={distribution}, queries={total_queries}, rate={rate_qps} qps")

    interval = 1.0 / rate_qps
    sent = 0
    errors = 0
    counter = Counter()

    while sent < total_queries:
        t0 = time.time()

        if distribution == "zipf":
            zone = choose_zipf(ZONES, ZONE_ZIPF_WEIGHTS)
            query_type = choose_zipf(QUERY_TYPES, QUERY_ZIPF_WEIGHTS)
        else:
            zone = choose_uniform(ZONES)
            query_type = choose_uniform(QUERY_TYPES)

        query = build_query(query_type, zone, distribution)
        counter[f"{query_type}:{zone}"] = counter[f"{query_type}:{zone}"] + 1

        try:
            response = requests.post(f"{URL_CACHE}/query", json=query, timeout=5)
            data = response.json()
            source = data.get("source", "?")
        except Exception as e:
            errors = errors + 1
            source = "error"

        sent = sent + 1
        if sent % 50 == 0:
            print(f"[TrafficGen] {sent}/{total_queries} sent | errors={errors}")

        elapsed = time.time() - t0
        sleep_time = interval - elapsed
        if sleep_time > 0:
            time.sleep(sleep_time)

    print(f"\n[TrafficGen] Done. Sent={sent}, Errors={errors}")
    print(f"Top 5 patterns: {counter.most_common(5)}")

def wait_for_services(max_retries=30, delay=2):
    print("[TrafficGen] Waiting for services to be ready...")
    for service_url in [URL_CACHE, METRICS_URL]:
        for i in range(max_retries):
            try:
                r = requests.get(f"{service_url}/health", timeout=2)
                if r.status_code == 200:
                    print(f"   {service_url} ready")
                    break
            except Exception:
                pass
            time.sleep(delay)
        else:
            print(f"   {service_url} not reachable after {max_retries} retries")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--distribution", choices=["zipf", "uniform", "both"], default="both")
    parser.add_argument("--queries", type=int, default=500)
    parser.add_argument("--rate", type=float, default=10.0, help="Queries per second")
    args = parser.parse_args()

    wait_for_services()
    time.sleep(3)

    if args.distribution == "both":
        print("\n=== Running ZIPF distribution ===")
        run("zipf", args.queries, args.rate)

        try:
            requests.post(f"{METRICS_URL}/reset", timeout=2000)
            requests.post(f"{URL_CACHE}/flush", timeout=2000)
        except Exception:
            pass
        time.sleep(2)

        print("\n=== Running UNIFORM distribution ===")
        run("uniform", args.queries, args.rate)
    else:
        run(args.distribution, args.queries, args.rate)

    try:
        stats = requests.get(f"{METRICS_URL}/stats", timeout=3).json()
        print("\n=== Final Metrics ===")
        print(json.dumps(stats, indent=2))
    except Exception:
        pass
