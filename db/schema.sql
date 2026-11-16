-- Власник: Ілля. Контракт: docs/contract.md (розділ 3 PLAN.md).
CREATE TABLE IF NOT EXISTS regions (
  id TEXT PRIMARY KEY,          -- 'lviv', 'kyiv_city'
  name_uk TEXT NOT NULL,        -- 'Львівська область'
  short_uk TEXT NOT NULL,       -- 'Львівщина'
  name_en TEXT,                 -- назва з GeoJSON
  iso TEXT, koatuu2 TEXT,
  playable INTEGER NOT NULL,    -- 0 для Криму/Севастополя (і, можливо, Луганської)
  lat REAL, lon REAL,           -- центроїд
  population INTEGER, area_km2 REAL
);
CREATE TABLE IF NOT EXISTS region_aliases (
  alias TEXT PRIMARY KEY,
  region_id TEXT REFERENCES regions(id)
);
CREATE TABLE IF NOT EXISTS metrics (
  id TEXT PRIMARY KEY,          -- 'alerts_hours', 'cars_top_brand'
  title_uk TEXT, unit TEXT,
  kind TEXT,                    -- 'numeric' | 'categorical'
  category TEXT,                -- 'war' | 'demography' | 'cars' | 'education'
  source_name TEXT, source_url TEXT, year INTEGER,
  higher_is TEXT                -- 'better' | 'worse' | NULL
);
CREATE TABLE IF NOT EXISTS region_metrics (
  region_id TEXT, metric_id TEXT,
  value REAL, value_text TEXT,  -- value_text для categorical
  year INTEGER,
  rank INTEGER, n_ranked INTEGER,
  PRIMARY KEY (region_id, metric_id)
);
CREATE TABLE IF NOT EXISTS series (
  region_id TEXT, metric_id TEXT, period TEXT, value REAL  -- period: '2024-03'
);
CREATE TABLE IF NOT EXISTS facts (
  id INTEGER PRIMARY KEY,
  region_id TEXT, metric_id TEXT,
  kind TEXT,                    -- 'rank' | 'relative' | 'raw' | 'categorical'
  text_uk TEXT,
  consistent TEXT,              -- JSON-список регіонів, для яких твердження теж істинне
  info REAL,                    -- log2(25 / len(consistent))
  riddle_uk TEXT                -- Stretch
);
CREATE TABLE IF NOT EXISTS scores (
  id INTEGER PRIMARY KEY, nickname TEXT, mode TEXT, points INTEGER,
  daily_date TEXT, created_at TEXT
);
