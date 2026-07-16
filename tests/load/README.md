# Load Test Harness

Validates the Gw2Analytics stack under realistic load: **100+ concurrent users** browsing the read-heavy endpoints + **concurrent 100 MiB `.zevtc` uploads** to the upload endpoint.

## Tooling

- **k6** — HTTP-level load, used for end-to-end throughput / latency / error-rate metrics.
- **Locust** — Python-native, used to share types with the FastAPI backend (no manual HTTP client boilerplate).

## Run

### k6 (needs k6 installed: `brew install k6` or per [docs](https://k6.io/docs/getting-started/installation/))

```bash
# Browse smoke: 100 concurrent users on /api/v1/fights
k6 run tests/load/k6/browse-fights.ts

# Upload smoke: 1 MB sample upload, 5-50 concurrent users
k6 run tests/load/k6/upload-zevtc.ts
```

### Locust (needs locust installed: `pip install locust` (uses HttpUser, NOT FastHttpUser -- no geventhttpclient dep needed))

```bash
# 100 users, spawn rate 5/s, runs until Ctrl+C or 300s
locust -f tests/load/locust/locustfile.py --host=http://localhost:8000
# Web UI at http://localhost:8089
```

### Generate a sample .zevtc fixture (5-50 KB)

```bash
python3 tests/load/scripts/generate_sample_zevtc.py
# Produces tests/load/fixtures/sample.zevtc (~1 KB minimal valid EVTC)
```

For larger fixtures, copy from `libs/gw2_evtc_parser/tests/fixtures/` if available:
```bash
cp libs/gw2_evtc_parser/tests/fixtures/*.zevtc tests/load/fixtures/
```

## Output metrics

| Metric | Threshold |
|---|---|
| HTTP RPS (GET /api/v1/fights) | ≥ 50 RPS sustained at 100 users |
| p95 latency (browse) | < 500 ms |
| p95 latency (upload) | < 30 s for 1 MB; < 60 s for 100 MiB |
| Error rate | < 1% (browse); < 5% (upload) |
| OOM detection | k6 must not see ConnectionReset or 5xx spikes |
| Arq enqueue time | < 200 ms p95 |

## Iterations

| Stage | Users | Duration | Goal |
|---|---|---|---|
| 1. Smoke | 10 | 30 s | Validate baseline |
| 2. Ramp | 100 | 60 s ramp + 120 s hold | Validate "real" load |
| 3. Stress | 500 | 30 s ramp + 60 s hold | Find breaking point |
| 4. Soak | 50 | 600 s | Memory leak detection |

## CI integration

Add to the project's CI pipeline (`.github/workflows/`) as a separate `load-tests` job that runs **only on `main`** (not every PR — too expensive). Fail the build if any threshold breach.

