from flask import Flask, request, jsonify
import redis, json, os, time, requests, hashlib

app = Flask(__name__)

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
METRICS_URL = os.getenv("METRICS_URL", "http://metrics_service:8003")
RESPONSE_GEN_URL = os.getenv("RESPONSE_GEN_URL", "http://response_generator:8002")
TTL_SECONDS = int(os.getenv("TTL_SECONDS", 60))
EVICTION_POLICY = os.getenv("EVICTION_POLICY", "allkeys-lru")

redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

def build_cache_key(query_type, params):
    if query_type == "Q1":
        return f"count:{params.get('zone_id')}:conf={params.get('confidence_min', 0.0)}"
    elif query_type == "Q2":
        return f"area:{params.get('zone_id')}:conf={params.get('confidence_min', 0.0)}"
    elif query_type == "Q3":
        return f"density:{params.get('zone_id')}:conf={params.get('confidence_min', 0.0)}"
    elif query_type == "Q4":
        return f"compare:density:{params.get('zone_a')}:{params.get('zone_b')}:conf={params.get('confidence_min', 0.0)}"
    elif query_type == "Q5":
        return f"confidence_dist:{params.get('zone_id')}:bins={params.get('bins', 5)}"
    else:
        params_list = []
        for key in sorted(params.keys()):
            params_list.append(f"{key}:{params[key]}")
        params_str = ",".join(params_list)
        h = hashlib.md5(params_str.encode()).hexdigest()
        return f"{query_type}:{h}"

def send_metric(event, query_type, latency_ms, cache_key=""):
    try:
        requests.post(f"{METRICS_URL}/record", json={
            "event": event,
            "query_type": query_type,
            "latency_ms": latency_ms,
            "cache_key": cache_key,
        }, timeout=0.5)
    except Exception:
        pass

@app.route("/query", methods=["POST"])
def handle_query():
    body = request.get_json()
    query_type = body.get("query_type")
    params = body.get("params", {})

    cache_key = build_cache_key(query_type, params)
    start = time.time()

    cached = redis_client.get(cache_key)
    if cached is not None:
        latency = (time.time() - start) * 1000
        send_metric("hit", query_type, latency, cache_key)
        return jsonify({"result": json.loads(cached), "source": "cache", "latency_ms": latency})

    try:
        response = requests.post(f"{RESPONSE_GEN_URL}/query", json={
            "query_type": query_type,
            "params": params,
        }, timeout=10)
        data = response.json()
    except Exception as e:
        latency = (time.time() - start) * 1000
        send_metric("error", query_type, latency, cache_key)
        return jsonify({"error": str(e)}), 503

    result = data.get("result")

    redis_client.setex(cache_key, TTL_SECONDS, json.dumps(result))

    latency = (time.time() - start) * 1000
    send_metric("miss", query_type, latency, cache_key)

    return jsonify({"result": result, "source": "computed", "latency_ms": latency})

@app.route("/stats")
def stats():
    info = redis_client.info("stats")
    keyspace = redis_client.info("keyspace")
    return jsonify({
        "hits": info.get("keyspace_hits", 0),
        "misses": info.get("keyspace_misses", 0),
        "evicted_keys": info.get("evicted_keys", 0),
        "keyspace": keyspace,
    })

@app.route("/config", methods=["POST"])
def configure():
    global TTL_SECONDS
    body = request.get_json()
    if "ttl" in body:
        TTL_SECONDS = int(body["ttl"])
    if "maxmemory" in body:
        redis_client.config_set("maxmemory", body["maxmemory"])
    if "policy" in body:
        redis_client.config_set("maxmemory-policy", body["policy"])
    return jsonify({"ttl": TTL_SECONDS})

@app.route("/flush", methods=["POST"])
def flush_cache():
    redis_client.flushdb()
    return jsonify({"status": "flushed"})

@app.route("/health")
def health():
    try:
        redis_client.ping()
        return jsonify({"status": "ok", "redis": "connected"})
    except Exception as e:
        return jsonify({"status": "error", "redis": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8001)
