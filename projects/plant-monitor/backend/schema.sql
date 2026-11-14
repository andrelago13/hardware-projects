CREATE TABLE IF NOT EXISTS readings (
  id BIGSERIAL PRIMARY KEY,
  ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  device_id TEXT NOT NULL,
  temperature_c DOUBLE PRECISION NOT NULL,
  humidity_pct DOUBLE PRECISION NOT NULL,
  soil_moisture_pct INTEGER NOT NULL,
  uptime_seconds BIGINT NOT NULL DEFAULT 0,
  boot_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_readings_device_ts
  ON readings (device_id, ts DESC);
