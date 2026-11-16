# Контракт «ДеЦе? Live»

> **Хто змінює:** лише Слава, разом з `app/schemas.py`. Після зміни він перегенеровує
> `docs/openapi.json` і `static/mock/*.json` (див. §9) і пише в чат.
>
> **Джерело правди:** `app/schemas.py` (HTTP) та `app/domain.py` (Python усередині).
> Цей документ пояснює *поведінку*, а форму полів дивись у `docs/openapi.json` або `static/js/types.js`.
> `tests/test_contract.py` падає, якщо мок, OpenAPI або перелік ендпоінтів розійшлися зі схемами.

---

## 1. Загальні правила

| | |
|---|---|
| База | той самий origin, що й сторінка (`/api/...`, `/static/...`). CORS не потрібен |
| Формат | JSON, UTF-8, `snake_case` |
| ID регіонів | slug: `lviv`, `kyiv_city`, `kyiv_obl`, `ivano_frankivsk`… (повний список: `GET /api/regions`) |
| Час | unix-секунди, `float`, UTC. **Таймери рахуються від `server_now`**, а не від годинника телефона |
| Відстані | км, між центроїдами регіонів (haversine) |
| Невідомі поля | сервер відхиляє (`extra="forbid"`) → 422 `validation_error` |
| Регістр коду кімнати | будь-який; сервер приводить до верхнього |

Ігрових регіонів 25 (24 області + м. Київ). Крим і Севастополь повертаються з `playable: false`:
їх видно на карті сірими, але клік ігнорується, а guess дає 422 `region_not_playable`.

## 2. Помилки

Будь-яка не-2xx відповідь має однакове тіло:

```json
{"error": {"code": "room_not_found", "message": "unknown room 'ZZZZ'"}}
```

Фронт розгалужується **лише за `code`**. `message` призначене для консолі, гравцеві його не показуємо.

| HTTP | code | Коли | Що робить фронт |
|---|---|---|---|
| 403 | `bad_host_key` | `start`/`next` з чужим ключем | host: «Сесію ведучого втрачено» |
| 404 | `region_not_found` | невідомий `region_id` | баг фронту → `console.error` |
| 404 | `round_not_found` | соло-раунд зник (рестарт сервера) | почати новий раунд |
| 404 | `room_not_found` | невідомий код кімнати | play: «Кімнату не знайдено», повернути до вводу коду |
| 404 | `player_not_found` | `guess` з невідомим `player_id` | play: стерти `player_id` з localStorage, перепід'єднатися |
| 409 | `invalid_state` | дія не в тому статусі (guess у lobby, start двічі) | ігнорувати, наступний poll виправить екран |
| 409 | `round_finished` | соло: hint/guess після кінця раунду | показати результат |
| 409 | `no_more_hints` | соло: шоста підказка | сховати кнопку |
| 409 | `already_guessed` | друга відповідь у раунді | ігнорувати |
| 409 | `name_taken` | ім'я вже є в кімнаті (без регістру) | «Це ім'я зайняте» |
| 422 | `region_not_playable` | guess у Крим/Севастополь | не має статися: карта не дає клікнути |
| 422 | `invalid_name` | порожнє ім'я або > 20 символів після `strip` | підсвітити поле |
| 422 | `validation_error` | тіло не за схемою | баг → `console.error` |
| 501 | `not_implemented` | реалізацію ще не змерджено | на моках не трапляється |
| 503 | `data_unavailable` | нема `db/game.sqlite` і `data/parsed` | `python -m etl.run_all` |

## 3. Ендпоінти

| Метод | Шлях | Тіло | Відповідь | Помилки |
|---|---|---|---|---|
| GET | `/health` | | `{"status":"ok"}` | |
| GET | `/api/config` | | `AppConfig` | |
| GET | `/api/regions` | | `Region[]` (27, за укр. алфавітом) | 503 |
| GET | `/api/regions/{id}/card` | | `Card` | 404 `region_not_found` |
| GET | `/static/ua.geojson` | | FeatureCollection (§6) | |
| POST | `/api/solo/rounds` | | `SoloRound` | 503 |
| POST | `/api/solo/rounds/{round_id}/hint` | | `{hints: Hint[]}` | 404, 409 `round_finished` / `no_more_hints` |
| POST | `/api/solo/rounds/{round_id}/guess` | `{region_id}` | `SoloGuessResponse` | 404, 409 `round_finished`, 422 |
| POST | `/api/rooms` | | `RoomCreated` | |
| POST | `/api/rooms/{code}/players` | `{name}` | `{player_id}` | 404, 409 `name_taken` / `invalid_state`, 422 `invalid_name` |
| POST | `/api/rooms/{code}/start` | `{host_key}` | `RoomState` | 403, 404, 409 |
| POST | `/api/rooms/{code}/next` | `{host_key}` | `RoomState` | 403, 404, 409 |
| POST | `/api/rooms/{code}/guess` | `{player_id, region_id}` | `{region_id}` | 404, 409, 422 |
| GET | `/api/rooms/{code}/state?player_id=` | | `RoomState` | 404 |

Приклад кожної відповіді лежить у `static/mock/` (§9).

## 4. Соло

```
soloStart() ──► SoloRound{hints:[h0]} ──► [soloHint() ≤ 4 рази] ──► soloGuess() ≤ 3 рази ──► finished
```

* Раунд стартує з 1 відкритою підказкою. `hint` відкриває наступну і повертає **усі** відкриті.
* `guess` можна робити будь-коли. Раунд стає `finished`, коли `correct` або коли вичерпано `max_attempts` (3).
  Лише тоді `answer_region_id != null`.
* Неправильна відповідь не закриває раунд: можна відкрити ще підказку і спробувати знову.
* Бали за спробу: `scoring.points(correct, distance_km, hint_index = кількість_відкритих - 1, attempt)`:
  * правильна: `1000 × HINT_MULT[hint_index] × 0.5^(attempt-1)`;
  * неправильна: `500 × HINT_MULT[hint_index] × max(0, 1 - d/500) × 0.5^(attempt-1)`;
  * `HINT_MULT = [1.0, 0.8, 0.6, 0.45, 0.3]` (є в `/api/config`).
* Підсвітка спроби на карті: `HEAT_COLORS[heat]` з `api.js`. Межі: `<150` км hot, `<300` warm, `<500` cool, далі cold.
* Після `finished` фронт показує картку: `getCard(answer_region_id)`.
* Стан соло живе в пам'яті сервера. Після рестарту прийде 404 `round_not_found`, тоді просто починаємо новий раунд.

## 5. Кімнати

### 5.1 State machine

```
             start              автоматично або next              next (ще є раунди)
  lobby ───────────────► round ─────────────────────► reveal ──────────────────────► round (n+1)
                                                         │
                                                         └── next (останній раунд) ──► finished
```

| Статус | Перехід | Тригер |
|---|---|---|
| `lobby` → `round` | `POST start` | хост |
| `round` → `reveal` | **автоматично**, коли `server_now ≥ ends_at` або всі гравці відповіли; або `POST next` (достроково) | сервер / хост |
| `reveal` → `round` | `POST next`, якщо `round_no < total_rounds` | хост |
| `reveal` → `finished` | `POST next` після останнього раунду | хост |

Фонового таймера нема: сервер перераховує статус при кожному запиті. Тому host **мусить** опитувати
`state`, щоб кімната перейшла в `reveal`.

### 5.2 Таймінг підказок

Раунд триває `round_seconds` (35 за замовчуванням, у демо задається через `DEMO_ROUND_SECONDS`).
Підказка `i` (0-based) відкривається в момент `started_at + i × round_seconds / 5`:
підказка 0 відкрита одразу, а наступна приходить у `next_hint_at`. Відповідь можна дати будь-коли до `ends_at`.

Лічильники на екрані:
* до кінця раунду: `ends_at - server_now`;
* до наступної підказки: `next_hint_at - server_now`.

Між poll-ами відлік можна вести локально (`performance.now()`), а кожна нова відповідь `state` його синхронізує.

### 5.3 Polling

* `pollRoom(code, playerId, onState)` з `api.js`: 1 запит на секунду, без паралельних запитів.
* host опитує **без** `player_id`, play опитує **з** `player_id`.
* `player_id` і `room` гравця зберігаються в `localStorage`. Після перезавантаження сторінки
  гравець продовжує гру без повторного join; якщо прийшла 404 `player_not_found`, він приєднується знову.
* `host_key` зберігається лише в `sessionStorage` хоста.

### 5.4 Поля `RoomState` за статусами

| Поле | lobby | round | reveal | finished |
|---|---|---|---|---|
| `round_no` | 0 | 1..N | 1..N | N |
| `started_at`, `ends_at` | null | ✓ | ✓ | null |
| `next_hint_at` | null | ✓ / null, коли всі 5 відкриті | null | null |
| `hints` | `[]` | відкриті | усі 5 | усі 5 останнього раунду |
| `answered` / `total` | 0 / N | ✓ | ✓ | ✓ |
| `my_guess` | null | ✓ / null | ✓ / null | null |
| `reveal` | null | null | ✓ | ✓ (останній раунд) |
| `leaderboard[].delta` | 0 | з попереднього раунду | за цей раунд | за останній |

`me` є, лише якщо передано відомий `player_id`. `players` ідуть у порядку приєднання,
`leaderboard` відсортовано за `score` спадно.

### 5.5 Бали в кімнаті

На reveal для кожного, хто відповів: `scoring.points(correct, d, hint_index_в_момент_відповіді)` плюс,
лише за правильну відповідь, `speed_bonus = round(100 × (ends_at - answered_at) / round_seconds)`.
Хто не відповів, отримує 0. Дозволено приєднатися посеред гри: гравець стартує з 0 балів і може відповідати в поточному раунді.

### 5.6 Що малює кожен екран

| Статус | `host.html` (проєктор) | `play.html` (телефон) |
|---|---|---|
| lobby | великий `qr_svg`, `join_url`, список `players`, кнопка «Старт» | «Чекаємо на старт», своє ім'я |
| round | карта (не інтерактивна), `hints`, таймер, `answered/total` | `hints`, міні-карта, «Відповісти» → `my_guess`; після відповіді «Чекаємо» |
| reveal | `map.choropleth(distribution)`, `drawLine(guess → answer)`, лідерборд, `renderCard(reveal.card)`, кнопка «Далі» | правильна відповідь, свої бали з `reveal.guesses`, місце в `leaderboard` |
| finished | фінальний лідерборд, підсумковий футер | своє місце і бали |

## 6. Геодані (`/static/ua.geojson`)

`FeatureCollection` з 27 features (`Polygon`/`MultiPolygon`, WGS84). Кожна має

```json
"properties": {"region_id": "lviv", "name_uk": "Львівська область", "short_uk": "Львівщина", "playable": 1}
```

`region_id` збігається з `Region.id`. Центроїди беремо з `GET /api/regions` (`lat`, `lon`), з GeoJSON їх не рахуємо.
Файл генерує `etl/build_geo.py`, поки що туди копіюється `data/parsed/ua.geojson`.

## 7. JS-модулі (інтерфейси між фронтендерами)

| Модуль | Експортує | Власник | Хто використовує |
|---|---|---|---|
| `js/types.js` | JSDoc-типи всіх відповідей | Слава | усі |
| `js/api.js` | `getConfig, getRegions, getCard, getGeo, solo*, room*, pollRoom, secondsUntil, HEAT_COLORS, ApiError` | Андрій | усі екрани |
| `js/map.js` | `createMap(el, geo, opts) → MapView` | Андрій | solo, host, player |
| `js/card.js` | `renderCard(el, card, opts) → {destroy}` | Матвій | solo, host |
| `js/solo.js`, `js/host.js`, `js/player.js` | нічого (точки входу сторінок) | Андрій / Андрій / Вадім | |

Повні сигнатури з JSDoc описані в самих файлах. Екрани не викликають `fetch` напряму: лише через `api.js`.

## 8. Python-інтерфейси (бекенд і ETL)

| Інтерфейс | Файл | Реалізація | Власник реалізації |
|---|---|---|---|
| `Repository` | `app/repository.py` | `SqliteRepository`, `CsvRepository`, `InMemoryRepository` | Слава (готово) |
| `HintPicker.pick(region_id, n, rng) → Hint[]` | `app/game/hints.py` | `FactHintPicker` (`RandomHintPicker` тимчасовий) | Матвій |
| `CardBuilder.build(region_id) → Card` | `app/game/card.py` | `DefaultCardBuilder` | Матвій |
| `SoloService` | `app/game/solo.py` | `InMemorySoloService` | Слава |
| `RoomManager` | `app/game/rooms.py` | `InMemoryRoomManager` | Слава |
| `Step.run(ctx) → EtlTables` | `etl/base.py` | `AlertsStep`, `DratsStep`, `CarsStep`, `NmtStep` (`ParsedCsvStep` тимчасовий) | Ілля |
| `FactGenerator.generate(...) → Fact[]` | `etl/build_facts.py` | `DefaultFactGenerator` | Матвій |
| `Check.run(repo) → CheckResult` | `etl/check.py` | `NanMatrix` тощо | Ілля |
| `build_geo`, `load_population` | `etl/*.py` | функції | Вадім |

Детальні контракти записані в docstring кожного абстрактного класу. Яка реалізація підключена, вирішує `app/deps.py`
(`HINT_PICKER=facts` вмикає `FactHintPicker`).

Дані в БД (`db/schema.sql`):
* `region_metrics.rank`: 1 = найбільше значення, рахується серед ігрових регіонів;
  рівні значення ділять одне місце (1, 2, 2, 4). Для categorical `rank = null`.
* `facts.consistent`: JSON-масив `region_id`, який завжди містить сам регіон.
* `facts.info = log2(N_ігрових / len(consistent))`.

## 9. Моки і синхронізація

| Файл | Відповідь |
|---|---|
| `config.json` | `GET /api/config` |
| `regions.json` | `GET /api/regions` |
| `card.json` | `GET /api/regions/lviv/card` |
| `solo_round.json`, `solo_hint.json` | старт і друга підказка |
| `solo_guess_wrong.json`, `solo_guess_correct.json`, `solo_guess_failed.json` | `?guess=wrong\|correct\|failed` |
| `room_created.json`, `room_join.json`, `room_guess.json` | |
| `room_state_{lobby,round,reveal,finished}.json` | `?state=…` |
| `error.json` | приклад помилки |

Як перемикати режими (працює на кожній сторінці):
* `?mock=1` вмикає моки, `?mock=0` — справжній API;
* `?state=reveal` задає статус кімнати в моках;
* `?guess=correct` задає результат соло-відповіді в моках.

Команди для перегенерації:

```bash
python -m scripts.export_mocks     # static/mock/*.json
python -m scripts.export_openapi   # docs/openapi.json
pytest tests/test_contract.py      # перевірка синхронізації
```
