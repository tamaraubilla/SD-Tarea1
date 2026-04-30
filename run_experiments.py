#!/usr/bin/env python3
import requests, time, json, subprocess, os, sys

URL_CACHE   = "http://localhost:8001"
METRICS_URL = "http://localhost:8003"
COMPOSE_DIR = os.path.dirname(os.path.abspath(__file__))

EXPERIMENTS = [
    ("LRU_200MB_TTL60_Zipf",    "200mb", "allkeys-lru",   60,  500, "zipf"),
    ("LFU_200MB_TTL60_Zipf",    "200mb", "allkeys-lfu",   60,  500, "zipf"),
    ("LRU_50MB_TTL60_Zipf",     "50mb",  "allkeys-lru",   60,  500, "zipf"),
    ("LRU_500MB_TTL60_Zipf",    "500mb", "allkeys-lru",   60,  500, "zipf"),
    ("LRU_200MB_TTL10_Zipf",    "200mb", "allkeys-lru",   10,  500, "zipf"),
    ("LRU_200MB_TTL300_Zipf",   "200mb", "allkeys-lru",  300,  500, "zipf"),
    ("LRU_200MB_TTL60_Uniform", "200mb", "allkeys-lru",   60,  500, "uniform"),
    ("LFU_200MB_TTL60_Uniform", "200mb", "allkeys-lfu",   60,  500, "uniform"),
]

results = []


def reset():
    requests.post(f"{METRICS_URL}/reset", timeout=3)
    requests.post(f"{URL_CACHE}/flush", timeout=3)
    time.sleep(1)


def get_metrics_stats():
    return requests.get(f"{METRICS_URL}/stats", timeout=5).json()


def get_cache_stats():
    return requests.get(f"{URL_CACHE}/stats", timeout=5).json()


def configure_cache(max_memory, policy, ttl):
    requests.post(f"{URL_CACHE}/config", json={
        "maxmemory": max_memory,
        "policy":    policy,
        "ttl":       ttl,
    }, timeout=5)


def run_traffic(queries, distribution, rate=20):
    command = [
        "docker", "compose", "run", "--rm",
        "traffic_generator",
        "python", "app.py",
        "--distribution", distribution,
        "--queries",      str(queries),
        "--rate",         str(rate),
    ]
    subprocess.run(command, check=True, cwd=COMPOSE_DIR)


for experiment in EXPERIMENTS:
    label, max_memory, policy, ttl, queries, distribution = experiment
    print(f"\n{'='*60}")
    print(f"Experiment: {label}")
    print(f"  maxmemory={max_memory}, policy={policy}, ttl={ttl}s, dist={distribution}")

    configure_cache(max_memory, policy, ttl)
    reset()

    evicted_before = get_cache_stats().get("evicted_keys", 0)
    t_start = time.time()

    try:
        run_traffic(queries, distribution)
        time.sleep(2)

        stats = get_metrics_stats()
        cache_stats = get_cache_stats()

        t_end = time.time()
        minutes = (t_end - t_start) / 60
        evicted_after = cache_stats.get("evicted_keys", 0)
        eviction_rate = (evicted_after - evicted_before) / minutes if minutes > 0 else 0

        stats["experiment"]   = label
        stats["eviction_rate"] = round(eviction_rate, 4)
        stats["evicted_keys"]  = evicted_after - evicted_before
        results.append(stats)

        print(
            f"  hit_rate={stats['hit_rate']:.3f}"
            f" | throughput={stats['throughput_qps']} qps"
            f" | p50={stats['latency_all']['p50']:.1f}ms"
            f" | p95={stats['latency_all']['p95']:.1f}ms"
            f" | eviction_rate={eviction_rate:.2f}/min"
            f" | cache_efficiency={stats.get('cache_efficiency', 0):.4f}"
        )
    except subprocess.CalledProcessError as e:
        print(f"  ERROR running traffic: {e}")
    except Exception as e:
        print(f"  ERROR: {e}")

configure_cache("200mb", "allkeys-lru", 60)

output = os.path.join(COMPOSE_DIR, "resultados_experimentos.json")
with open(output, "w") as f:
    json.dump(results, f, indent=2)

print(f"\n\nResults saved to {output}")
print("\n=== Summary ===")
print(f"{'Experiment':<40} {'hit_rate':>9} {'qps':>7} {'evict/min':>10} {'efficiency':>12}")
print("-" * 82)
for r in results:
    print(
        f"{r['experiment']:<40}"
        f" {r['hit_rate']:>9.3f}"
        f" {r['throughput_qps']:>7.2f}"
        f" {r.get('eviction_rate', 0):>10.2f}"
        f" {r.get('cache_efficiency', 0):>12.4f}"
    )
