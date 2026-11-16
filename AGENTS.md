# Правила для людей і AI-асистентів

Над репо паралельно працюють 5 людей, і кожен зі своїм AI. Щоб ніхто нікому не ламав код:

## 1. Пиши лише у свої файли

| Хто | Файли |
|---|---|
| **Слава** (контракт, бекенд) | `app/{main,config,deps,domain,errors,schemas,repository,qr}.py`, `app/api/*`, `app/game/{solo,rooms,scoring}.py`, `docs/*`, `scripts/*`, `static/js/types.js`, `static/mock/*` (лише через `scripts/export_mocks.py`), `requirements.txt`, `pytest.ini`, `tests/{conftest,test_api,test_contract,test_scoring}.py`, `AGENTS.md` |
| **Ілля** (ETL) | `db/*`, `etl/{base,regions,load_alerts,load_drats,load_cars,load_nmt,load_parsed,check,run_all}.py`, `tests/test_etl.py` |
| **Матвій** (факти, картка) | `etl/{metrics_catalog,build_facts,gen_riddles}.py`, `app/game/{hints,card}.py`, `static/js/card.js`, `tests/test_hints.py` |
| **Андрій** (фронт) | `static/{index,host}.html`, `static/css/*`, `static/js/{api,map,solo,host}.js` |
| **Вадім** (гео, телефон) | `etl/{build_geo,load_population}.py`, `static/play.html`, `static/js/player.js`, `README.md` |

Треба змінити чужий файл? Попроси власника в чаті. AI-асистент у такому разі **зупиняється і питає**, а не редагує сам.

## 2. Інтерфейси — це контракт

* Абстрактні класи (`Repository`, `HintPicker`, `CardBuilder`, `SoloService`, `RoomManager`, `Step`,
  `FactGenerator`, `Check`) і їхні docstring-и **не змінюються** без Слави. Реалізація ховається за інтерфейсом.
* Підставити нову реалізацію можна лише в `app/deps.py` (через Славу) або `etl/run_all.py` (через Іллю).
* HTTP-форма описана в `app/schemas.py`, поведінка — в `docs/contract.md`. Фронт на неї спирається, тож поля не перейменовуй.
* Нереалізоване кидає `NotImplementedError`: API поверне 501, а тест стане xfail. Коли реалізуєш, тест сам стане зеленим.
* Ігрова логіка не пише SQL і не читає CSV, лише ходить через `Repository`.
* Доменні помилки беруться з `app/errors.py` (не `HTTPException`).

## 3. Запуск

```bash
uv venv && uv pip install -r requirements.txt     # або python -m venv .venv && pip install -r requirements.txt
python -m etl.run_all                             # db/game.sqlite + static/ua.geojson з data/parsed
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
pytest                                            # має бути зелено (xfail = ще не реалізовано)
```

Фронт без бекенда: відкрий `/static/index.html?mock=1`. Режими моків описані в `docs/contract.md` §9.

## 4. Перед «готово до мерджу»

1. `pytest` зелений, і нових падінь у чужих тестах нема.
2. Змінено `app/schemas.py`? Тоді `python -m scripts.export_mocks && python -m scripts.export_openapi`
   і онови `static/js/types.js` (`test_contract.py` це перевіряє).
3. `git diff --stat` містить лише твої файли (§1).
4. Нових залежностей нема: їх додає лише Слава.

## 5. Мова і стиль

* Тексти для гравця пишемо українською. Код, ідентифікатори і коміти — англійською.
* Python 3.11+, type hints, `from __future__ import annotations` у нових модулях.
* Фронт без збирача: ES-модулі, бібліотеки з CDN з фіксованою версією.
