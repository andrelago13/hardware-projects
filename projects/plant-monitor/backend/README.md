# Plant Monitor — Backend API (Google Cloud Functions + Neon PostgreSQL)

Serverless ingestion API for [the Plant Monitor project](../README.md). Receives periodic sensor readings over HTTPS, validates the `X-API-Key` header and JSON payload, and writes rows to a Neon PostgreSQL database for Grafana visualization and alerting.

---

## Architecture & Cost

- **Compute:** Google Cloud Functions (Gen 2) in `europe-west2` (`plant-monitor-ingest`, `256Mi`, `min-instances=0`, `max-instances=2`, runtime `python312`). Scales to zero when idle and fits comfortably within GCP's always-free tier.
- **Database:** Neon PostgreSQL (`eu-west-2`), using the pooled connection string (`DATABASE_URL_POOLED`) for serverless connections.
- **CI/CD:** Keyless GitHub Actions deployment via Workload Identity Federation (`.github/workflows/deploy-plant-monitor-backend.yml`).
- **Visualization & Alerts:** Grafana Cloud (or self-hosted Grafana) connected directly to Neon via the built-in PostgreSQL data source.

**Live endpoint:** `https://europe-west2-plant-monitor-514719.cloudfunctions.net/plant-monitor-ingest`

---

## Files

- `main.py` — Cloud Function entry point (`ingest_reading`) supporting `GET` health check and `POST` reading ingestion.
- `schema.sql` — `readings` table and `(device_id, ts DESC)` index.
- `requirements.txt` / `requirements-dev.txt` — runtime and test dependencies.
- `test_main.py` — `pytest` unit tests (mocked DB).
- `.env.example` — template for local environment variables (`DATABASE_URL`, `DATABASE_URL_POOLED`, `API_KEY`).
- `.gcloudignore` — excludes `.env`, tests, and local `.venv` from Cloud Functions uploads.

---

## API Contract

### Health Check
- `GET /` → `200 {"ok": true, "service": "plant-monitor-ingest"}`

### Ingest Reading
- **Method & Path:** `POST /`
- **Headers:**
  - `Content-Type: application/json`
  - `X-API-Key: <API_KEY>`
- **Body:**
  ```json
  {
    "deviceId": "AA:BB:CC:DD:EE:FF",
    "temperatureC": 23.4,
    "humidityPct": 54.2,
    "soilMoisturePct": 41,
    "uptimeSeconds": 908,
    "bootCount": 2
  }
  ```
  `uptimeSeconds` and `bootCount` default to `0` if omitted.
- **Responses:** `201 {"ok": true}`, `400` on invalid payload, `401` on invalid/missing `X-API-Key`.

---

## Local Development & Testing

```sh
cd projects/plant-monitor/backend
uv venv .venv --python 3.11
uv pip install -r requirements-dev.txt

# Run unit tests
.venv/bin/pytest -v

# Apply schema to Neon (if setting up a fresh DB)
set -a && source .env && set +a
psql "$DATABASE_URL" -f schema.sql

# Run local Cloud Functions emulator
.venv/bin/functions-framework --target=ingest_reading --port=8080
```

Test locally or against the deployed endpoint:
```sh
set -a && source projects/plant-monitor/backend/.env && set +a
curl -X POST "https://europe-west2-plant-monitor-514719.cloudfunctions.net/plant-monitor-ingest" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{"deviceId":"AA:BB:CC:DD:EE:FF","temperatureC":23.4,"humidityPct":54.2,"soilMoisturePct":41,"uptimeSeconds":908,"bootCount":2}'
```

---

## CI/CD (GitHub Actions)

Workflow: `.github/workflows/deploy-plant-monitor-backend.yml`

- Runs `pytest` on PRs and pushes affecting `projects/plant-monitor/backend/**`.
- On pushes to `main` (or manual `workflow_dispatch`), authenticates to `plant-monitor-514719` via Workload Identity Federation (`github-deployer@plant-monitor-514719.iam.gserviceaccount.com`) and deploys `plant-monitor-ingest` using GitHub Secrets:
  - `PLANT_MONITOR_DATABASE_URL`
  - `PLANT_MONITOR_API_KEY`

---

## Connecting Grafana to Neon

1. Add a **PostgreSQL** data source in Grafana using your Neon direct connection details (`ep-gentle-thunder-zaodhaad.c-2.eu-west-2.aws.neon.tech`, database `neondb`, TLS/SSL Mode: `require`).
2. Use this time-series query for panels:
   ```sql
   SELECT
     ts AS "time",
     device_id,
     soil_moisture_pct,
     temperature_c,
     humidity_pct,
     uptime_seconds,
     boot_count
   FROM readings
   WHERE $__timeFilter(ts)
   ORDER BY ts;
   ```
3. Configure an Alert Rule (e.g., `soil_moisture_pct < 25` sustained for `1h`) to notify via Email, Telegram, or Discord.
