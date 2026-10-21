# geo-sleuth: что нужно знать про окружение

Скил геолокации фото. Исходник: https://github.com/Oldcircle/geo-sleuth (MIT),
вендорная копия в `.claude/skills/geo-sleuth/` — без правок, коммит `e01849f`
от 21.10.2026. Обновляется заменой папки целиком, локальных патчей в ней нет.

## Playwright: нужен пин 1.56.0

Реверс-поиск картинок поднимает браузер. В облачных сессиях Chromium
предустановлен (`PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers`), но это билд 1194
(Chromium 141), а `uv` по умолчанию тянет свежий playwright, который ищет билд
1248 — и падает с «Executable doesn't exist». Поэтому:

    uv run --with 'playwright==1.56.0' .claude/skills/geo-sleuth/scripts/doctor.py

`UV_CONSTRAINT` тут не помогает: для скриптов с PEP 723 `uv run` его не читает,
пин работает только флагом. Остальным скриптам пин не нужен — браузер трогает
только `intake.py` (реверс-поиск) и `doctor.py`.

## Сеть: хосты нужно открывать поимённо

Прямого DNS в контейнере нет, весь egress идёт через прокси, и он отдаёт `403`
на всё, чего нет в Allowed domains окружения (Network access → Edit).

Из коробки доступны и работают:

- `s3.amazonaws.com` — высотные тайлы (`terrain.py`)
- `maps.googleapis.com` — метаданные Street View

Базовый набор, который надо добавить вручную:

- `overpass-api.de` — запросы к OSM (`osm.py`), ядро поиска
- `nominatim.openstreetmap.org` — геокодинг (`gazetteer.py`)
- `huggingface.co` — веса моделей для `sat_scan.py` (CLIP) и `match.py` (DINOv2)
- `mt1.google.com` — спутниковые тайлы (`tiles.py`, `sat_scan.py`)
- `streetviewpixels-pa.googleapis.com` — снимки Street View (`gsv.py`)
- `yandex.com` — реверс-поиск картинок
- `en.wikipedia.org` — справочные запросы

Для китайских кейсов (网络迷踪) дополнительно: `graph.baidu.com`,
`image.baidu.com`, `map.baidu.com`, `mapsv0.bdimg.com`, `pic.sogou.com`,
`cn.bing.com`.

Без открытых хостов скил запускается, но из инструментов остаются только
высоты и метаданные Street View.

## Мелочи

- `GEO_PROXY` выставлять не надо: прямой egress на разрешённые хосты работает,
  а скил по умолчанию игнорирует системный прокси (`_net.py`, `--noproxy "*"`).
- Кэш (`.geo-cache/`) и доска кандидатов (`board.json`) создаются в текущем
  каталоге, а не рядом со скилом. Запускать лучше из отдельной папки.
