# API-контракт «ДеЦе? Live»

> Копія розділу 3 з PLAN.md. Змінює лише Слава (разом з `app/schemas.py`), про зміни пише в чат.


### Схема SQLite (`db/schema.sql`)
```sql
CREATE TABLE regions (
  id TEXT PRIMARY KEY,          -- 'lviv', 'kyiv_city'
  name_uk TEXT NOT NULL,        -- 'Львівська область'
  short_uk TEXT NOT NULL,       -- 'Львівщина'
  iso TEXT, koatuu2 TEXT,
  playable INTEGER NOT NULL,    -- 0 для Криму/Севастополя (і, можливо, Луганської)
  lat REAL, lon REAL,           -- центроїд
  population INTEGER, area_km2 REAL
);
CREATE TABLE region_aliases (alias TEXT PRIMARY KEY, region_id TEXT REFERENCES regions(id));
CREATE TABLE metrics (
  id TEXT PRIMARY KEY,          -- 'alerts_hours', 'cars_top_brand'
  title_uk TEXT, unit TEXT,     -- 'годин тривоги', 'на 1000 мешканців'
  kind TEXT,                    -- 'numeric' | 'categorical'
  category TEXT,                -- 'war' | 'demography' | 'cars' | 'education'
  source_name TEXT, source_url TEXT, year INTEGER
);
CREATE TABLE region_metrics (
  region_id TEXT, metric_id TEXT,
  value REAL, value_text TEXT,  -- value_text для categorical ('Renault')
  rank INTEGER, n_ranked INTEGER,
  PRIMARY KEY (region_id, metric_id)
);
CREATE TABLE series (region_id TEXT, metric_id TEXT, period TEXT, value REAL); -- '2024-03'
CREATE TABLE facts (
  id INTEGER PRIMARY KEY,
  region_id TEXT, metric_id TEXT,
  kind TEXT,                    -- 'rank' | 'relative' | 'raw' | 'categorical'
  text_uk TEXT,                 -- 'У топ-3 областей за годинами тривоги'
  consistent TEXT,              -- JSON-список регіонів, для яких це твердження теж істинне
  info REAL,                    -- log2(25 / len(consistent)), тобто наскільки факт видає відповідь
  riddle_uk TEXT                -- Stretch: LLM-перефразування
);
CREATE TABLE scores (id INTEGER PRIMARY KEY, nickname TEXT, mode TEXT, points INTEGER,
                     daily_date TEXT, created_at TEXT); -- Stretch
```

### Генерація фактів і підбір підказок (ключова логіка)
- Для кожної пари (регіон, numeric-метрика) створюємо факти трьох видів: **rank** (топ-1/топ-3/останні-3), **relative** («на 23% нижче за середнє по Україні», бакети ±10%), **raw** («412 годин тривоги за 2024»). Для categorical-метрик: «найпопулярніша марка нових авто — Renault».
- `consistent` — множина регіонів, для яких це твердження теж істинне (для relative: регіони з того ж бакета; для categorical: ті, де значення таке саме).
- `pick_hints(region_id, n=5)`: жадібно беремо факти з **різних категорій**, сортуємо за зростанням `info` (спочатку найважчий) і перевіряємо, що перетин `consistent` усіх 5 фактів дорівнює `{region_id}`. Так раунд гарантовано має одну відповідь.

### Бали
- `HINT_MULT = [1.0, 0.8, 0.6, 0.45, 0.3]` за індексом останньої відкритої підказки.
- Правильна відповідь: `1000 * mult`. Неправильна: `500 * mult * max(0, 1 - d_km/500)`. Соло: до 3 спроб, кожна наступна ×0.5.
- Мультиплеєр: +до 100 балів швидкості пропорційно часу, що лишився.
- «Гаряче/холодно» (haversine між центроїдами): `<150 км` червоний `hot`, `<300` помаранчевий `warm`, `<500` жовтий `cool`, далі синій `cold`.

### REST API (`app/schemas.py`, pydantic; копія в `docs/contract.md`)
```
GET  /api/regions                    -> [{id, name_uk, short_uk, playable, lat, lon}]
GET  /static/ua.geojson              -> FeatureCollection, properties.region_id = наш slug
POST /api/solo/rounds                -> {round_id, total_hints: 5, hints: [Hint]}       # перша підказка
POST /api/solo/rounds/{id}/hint      -> {hints: [Hint]}                                   # усі відкриті
POST /api/solo/rounds/{id}/guess     body {region_id}
                                     -> {correct, attempt, attempts_left, distance_km,
                                         heat: "hot|warm|cool|cold", points,
                                         answer_region_id: str|null}   # null, поки є спроби і не вгадано
GET  /api/regions/{id}/card          -> Card
POST /api/rooms                      -> {code: "K7QF", host_key, join_url, qr_svg}
```
```json
Hint = {"index": 0, "text": "Тут найпопулярніший колір нових авто — сірий", "metric_id": "cars_top_color", "category": "cars"}
Card = {
  "region": {"id": "lviv", "name_uk": "Львівська область"},
  "metrics": [{"metric_id":"births_per_1000","title_uk":"Народжуваність","unit":"на 1000",
               "value":6.1,"ukraine_avg":5.0,"rank":2,"n_ranked":23,
               "source_name":"Мін'юст, ДРАЦС","source_url":"https://data.gov.ua/..."}],
  "highlights": ["У топ-3 за народжуваністю", "..."],
  "series": {"alerts_count": [{"period":"2024-01","value":31}, ...]}
}
```

### Кімнати: REST + polling
Host і гравці опитують `GET .../state` раз на 1 с, дії йдуть звичайними `POST`.
```
POST /api/rooms/{code}/players       body {name}                -> {player_id}
POST /api/rooms/{code}/start         body {host_key}            -> RoomState
POST /api/rooms/{code}/next          body {host_key}            -> RoomState   # наступний раунд
POST /api/rooms/{code}/guess         body {player_id, region_id} -> {region_id}
GET  /api/rooms/{code}/state?player_id=...                      -> RoomState
```
```
RoomState = {code, status: "lobby|round|reveal|finished",
             players: [{id, name, score}],
             round_no, total_rounds, ends_at,      # null у lobby
             hints: [Hint],                        # усі відкриті на зараз
             answered: 4, total: 6,
             my_guess: str|null,                   # якщо передано player_id
             reveal: {answer_region_id, guesses:[{player_id,name,region_id,distance_km,heat,points}],
                      distribution:{"lviv":3,"volyn":1}, card: Card} | null,
             leaderboard: [{name, score}]}
```
`RoomManager` у `app/game/rooms.py` — чистий Python без залежностей від транспорту. Фонового таймера нема: відкриті підказки й кінець раунду рахуються з `started_at` при кожному запиті (`ROUND_SECONDS/5` с на підказку; раунд закінчується, коли всі відповіли або минув час).

**Моки:** `static/mock/*.json` (по одному файлу на кожну відповідь вище). У `static/js/api.js` є прапорець `const USE_MOCK = true`, тож фронт працює з першої хвилини.
