from flask import Flask, request, jsonify
import threading, time, json

app = Flask(__name__)
lock = threading.Lock()

events = []
start_time = time.time()

@app.route("/record", methods=["POST"])
def record():
    body = request.get_json()
    with lock:
        events.append({
            "ts": time.time(),
            "event": body.get("event"),
            "query_type": body.get("query_type"),
            "latency_ms": body.get("latency_ms", 0),
            "cache_key": body.get("cache_key", ""),
        })
    return jsonify({"ok": True})

@app.route("/stats")
def stats():
    with lock:
        events_copy = []
        for event in events:
            events_copy.append(event)

    hits = []
    for e in events_copy:
        if e["event"] == "hit":
            hits.append(e)

    misses = []
    for e in events_copy:
        if e["event"] == "miss":
            misses.append(e)

    errors = []
    for e in events_copy:
        if e["event"] == "error":
            errors.append(e)

    total = len(hits) + len(misses)

    hit_rate = len(hits) / total if total > 0 else 0
    miss_rate = len(misses) / total if total > 0 else 0

    all_latencies = []
    for e in events_copy:
        all_latencies.append(e["latency_ms"])

    hit_latencies = []
    for e in hits:
        hit_latencies.append(e["latency_ms"])

    miss_latencies = []
    for e in misses:
        miss_latencies.append(e["latency_ms"])

    def percentiles(data):
        if not data:
            return {"p50": 0, "p95": 0, "avg": 0}
        sorted_data = sorted(data)
        idx_50 = int(len(sorted_data) * 0.50)
        idx_95 = int(len(sorted_data) * 0.95)
        return {
            "p50": sorted_data[idx_50],
            "p95": sorted_data[idx_95],
            "avg": sum(sorted_data) / len(sorted_data),
        }

    elapsed = time.time() - start_time
    throughput = total / elapsed if elapsed > 0 else 0

    lat_hits = percentiles(hit_latencies)
    lat_misses = percentiles(miss_latencies)
    t_cache = lat_hits["avg"]
    t_db = lat_misses["avg"]
    cache_efficiency = (len(hits) * t_cache - len(misses) * t_db) / total if total > 0 else 0

    by_type = {}
    for e in hits:
        query_type = e["query_type"]
        if query_type not in by_type:
            by_type[query_type] = {"hits": 0, "misses": 0}
        by_type[query_type]["hits"] = by_type[query_type]["hits"] + 1

    for e in misses:
        query_type = e["query_type"]
        if query_type not in by_type:
            by_type[query_type] = {"hits": 0, "misses": 0}
        by_type[query_type]["misses"] = by_type[query_type]["misses"] + 1

    return jsonify({
        "total_queries": total,
        "hits": len(hits),
        "misses": len(misses),
        "errors": len(errors),
        "hit_rate": round(hit_rate, 4),
        "miss_rate": round(miss_rate, 4),
        "throughput_qps": round(throughput, 2),
        "latency_all": percentiles(all_latencies),
        "latency_hits": lat_hits,
        "latency_misses": lat_misses,
        "cache_efficiency": round(cache_efficiency, 4),
        "by_query_type": by_type,
        "elapsed_seconds": round(elapsed, 1),
    })

@app.route("/events")
def get_events():
    limit = int(request.args.get("limit", 200))
    with lock:
        limited_events = events[-limit:]
        return jsonify(limited_events)

@app.route("/reset", methods=["POST"])
def reset():
    global start_time
    with lock:
        events.clear()
        start_time = time.time()
    return jsonify({"ok": True})

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8003)
