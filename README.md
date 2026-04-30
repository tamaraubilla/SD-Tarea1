# Tarea 1 — Sistemas Distribuidos 2026-1

Plataforma de caché distribuida para consultas de densidad de edificaciones sobre el dataset Google Open Buildings (Santiago RM, Chile). Soporta políticas de evicción LRU y LFU, TTL configurable y dos distribuciones de tráfico (Zipf / Uniforme).

---

## Arquitectura

```
[Traffic Generator]
        │
        ▼
[Cache Service :8001]  ──miss──►  [Response Generator :8002]
        │                                    │
        ▼                                    ▼
   [Redis :6379]              [Metrics Service :8003]
        │                                    ▲
        └────────────────────────────────────┘
                  (todos los eventos se registran)
```

| Servicio | Puerto | Rol |
|---|---|---|
| `cache_service` | 8001 | Punto de entrada; consulta Redis antes de delegar |
| `response_generator` | 8002 | Computa Q1–Q5 desde dataset en memoria |
| `metrics_service` | 8003 | Agrega hits, misses y latencias |
| `traffic_generator` | — | Envía carga sintética (Zipf o Uniforme) |
| `redis` | 6379 | Store de caché con TTL y evicción LRU/LFU |

---

## Requisitos

| Herramienta | Versión mínima | Verificar |
|---|---|---|
| Docker | 24.x | `docker --version` |
| Docker Compose | 2.x (plugin) | `docker compose version` |
| Python | 3.10+ | `python3 --version` |
| pip | cualquiera | `pip3 --version` |

> Python y pip solo son necesarios para ejecutar `run_experiments.py` desde el host. Todo lo demás corre dentro de Docker.

---

## Instalación

### 1. Clonar el repositorio

```bash
git clone <url_del_repo>
cd tarea1
```

## Ejecución


Construye todas las imágenes, levanta los servicios y ejecuta el generador de tráfico con 500 consultas (Zipf + Uniforme):

```bash
docker compose up --build
```

Esperar hasta ver:
```
traffic_generator  | [TrafficGen] Done. Sent=500, Errors=0
```


**Paso 1 — Instalar dependencias en el host**

```bash
python3 -m venv venv
source venv/bin/activate        
pip install requests
```


**Paso 2 — Verificar que todos los servicios estén listos**

```bash
curl http://localhost:8001/health
curl http://localhost:8002/health
curl http://localhost:8003/health
```

Cada uno debe responder `{"status": "ok"}`. Si alguno falla, esperar unos segundos y reintentar.

**Paso 3 — Ejecutar los experimentos**

```bash
python3 run_experiments.py
```

El código corre las 8 configuraciones en secuencia. Cada una:
1. Aplica la política de caché y límite de memoria vía API
2. Reinicia métricas y vacía Redis
3. Lanza un contenedor `traffic_generator`
4. Recolecta estadísticas al finalizar

Los resultados se guardan en `resultados_experimentos.json`.


---

## Uso manual

### Enviar una consulta individual

```bash
curl -X POST http://localhost:8001/query \
  -H "Content-Type: application/json" \
  -d '{"query_type": "Q1", "params": {"zone_id": "Z1", "confidence_min": 0.7}}'
```

### Ejecutar el generador de tráfico manualmente

```bash
docker compose run --rm traffic_generator python app.py \
  --distribution zipf \
  --queries 1000 \
  --rate 20
```

### Opciones disponibles:

| Flag | Valores | Default | Descripción |
|------|---------|---------|-------------|
| `--distribution` | `zipf`, `uniform`, `both` | `both` | Distribución de llegada de consultas |
| `--queries` | entero | `500` | Total de consultas a enviar |
| `--rate` | decimal | `10.0` | Consultas por segundo |

### Cambiar política de evicción en tiempo de ejecución

```bash
# Cambiar a LFU
curl -X POST http://localhost:8001/config \
  -H "Content-Type: application/json" \
  -d '{"policy": "allkeys-lfu", "maxmemory": "200mb", "ttl": 60}'

# Volver a LRU
curl -X POST http://localhost:8001/config \
  -H "Content-Type: application/json" \
  -d '{"policy": "allkeys-lru", "maxmemory": "200mb", "ttl": 60}'
```

### Reiniciar métricas entre ejecuciones

```bash
curl -X POST http://localhost:8003/reset
curl -X POST http://localhost:8001/flush
```

---

## Referencia de API

### Cache Service – `localhost:8001`

| Método   | Ruta        | Descripción                                      |
|----------|-------------|--------------------------------------------------|
| `POST`   | `/query`    | Ejecutar consulta (caché primero)               |
| `GET`    | `/stats`    | Contadores de hits/misses/evicción de Redis     |
| `POST`   | `/config`   | Actualizar TTL, maxmemory, política             |
| `POST`   | `/flush`    | Vaciar todas las claves en caché                |
| `GET`    | `/health`   | Verificación de disponibilidad                  |

Body de `POST /query`:
```json
{
  "query_type": "Q1",
  "params": {
    "zone_id": "Z1",
    "confidence_min": 0.7
  }
}
```

Body de `POST /config` (todos los campos son opcionales):
```json
{
  "ttl": 60,
  "maxmemory": "200mb",
  "policy": "allkeys-lru"
}
```

### Response Generator – `localhost:8002`

| Método | Ruta        | Descripción                        |
|--------|-------------|------------------------------------|
| `POST` | `/query`    | Computar resultado directamente (sin caché) |
| `GET`  | `/health`   | Verificación de disponibilidad     |

### Metrics Service – `localhost:8003`

| Método   | Ruta                | Descripción                                |
|----------|---------------------|--------------------------------------------|
| `GET`    | `/stats`            | Hit rate, percentiles de latencia, throughput |
| `GET`    | `/events?limit=N`   | Log de eventos crudos (últimos 200 por defecto) |
| `POST`   | `/record`           | Registrar evento (uso interno)             |
| `POST`   | `/reset`            | Limpiar métricas y reiniciar reloj         |
| `GET`    | `/health`           | Verificación de disponibilidad             |

---

### Tipos de consulta

| Query | Patrón de clave                          | Descripción                                |
|-------|------------------------------------------|--------------------------------------------|
| Q1    | `count:{zona}:conf={c}`                  | Conteo de edificios en zona con confianza ≥ c |
| Q2    | `area:{zona}:conf={c}`                   | Área promedio y total de edificios         |
| Q3    | `density:{zona}:conf={c}`                | Densidad de edificios (edificios / km²)    |
| Q4    | `compare:density:{za}:{zb}:conf={c}`     | Comparación de densidad entre dos zonas    |
| Q5    | `confidence_dist:{zona}:bins={b}`        | Histograma de distribución de confianza    |


## Configuraciones de experimentos

El script `run_experiments.py` prueba las siguientes 8 configuraciones:

| Etiqueta | Memoria | Política | TTL | Consultas | Distribución |
|---|---|---|---|---|---|
| LRU_200MB_TTL60_Zipf | 200 MB | LRU | 60 s | 500 | Zipf |
| LFU_200MB_TTL60_Zipf | 200 MB | LFU | 60 s | 500 | Zipf |
| LRU_50MB_TTL60_Zipf | 50 MB | LRU | 60 s | 500 | Zipf |
| LRU_500MB_TTL60_Zipf | 500 MB | LRU | 60 s | 500 | Zipf |
| LRU_200MB_TTL10_Zipf | 200 MB | LRU | 10 s | 500 | Zipf |
| LRU_200MB_TTL300_Zipf | 200 MB | LRU | 300 s | 500 | Zipf |
| LRU_200MB_TTL60_Uniform | 200 MB | LRU | 60 s | 500 | Uniforme |
| LFU_200MB_TTL60_Uniform | 200 MB | LFU | 60 s | 500 | Uniforme |

Los resultados se acumulan en `resultados_experimentos.json` al finalizar cada experimento.

---
