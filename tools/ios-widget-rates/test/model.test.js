/* Проверка слоя над арифметикой: слияние свежих данных с кэшем, сборка
 * модели, выбор нужных запросов под размер виджета, разбор параметра
 * и пороги тревог.
 *
 * Запуск: node --test tools/ios-widget-rates/test/model.test.js
 */
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const assert = require('node:assert');

function load() {
  const file = path.join(__dirname, '..', 'rates-widget.js');
  const source = fs.readFileSync(file, 'utf8');
  const holder = { exports: {} };
  new Function('module', source)(holder);
  return holder.exports;
}

const HOUR = 3600000;
const DAY = 86400000;
const agoIso = (ms) => new Date(Date.now() - ms).toISOString();

function ramp(length, from, step) {
  return Array.from({ length }, (_, i) => from + i * step);
}

function parts(overrides) {
  const now = new Date().toISOString();
  return Object.assign(
    {
      cbr: {
        at: now,
        data: { date: '2026-09-13T11:30:00+03:00', usd: 90, usdPrev: 89.5, eur: 100, cny: 12.5 }
      },
      spot: {
        at: now,
        data: {
          btcUsd: 68000,
          btcRub: NaN,
          btcChange24h: 2.5,
          btcVolume24h: 3e10,
          btcCap: 1.3e12,
          marketUsdRub: 94.5,
          marketChange24h: 0.4,
          source: 'CoinGecko'
        }
      },
      btcHistory: { at: now, data: { daily: ramp(60, 60000, 100), spark: ramp(30, 60000, 100) } },
      usdHistory: { at: now, data: { daily: ramp(60, 88, 0.05), spark: ramp(30, 88, 0.05) } },
      fng: { at: now, data: { value: 54, label: 'нейтрально', prev: 50 } }
    },
    overrides || {}
  );
}

test('свежее вытесняет кэш, кэш закрывает дыры, протухшее выбрасывается', () => {
  const W = load();
  const cached = {
    cbr: { at: agoIso(2 * HOUR), data: { usd: 1 } },
    spot: { at: agoIso(30 * HOUR), data: { btcUsd: 2 } },
    fng: { at: agoIso(3 * HOUR), data: { value: 3 } }
  };
  const merged = W.mergeParts({ cbr: { usd: 99 } }, cached);

  assert.strictEqual(merged.cbr.data.usd, 99, 'свежий ЦБ победил кэш');
  assert.strictEqual(merged.fng.data.value, 3, 'непришедший индекс взят из кэша');
  assert.ok(!merged.spot, 'кэш старше суток к показу не годится');
});

test('модель собирается из частей и добирает недостающее счётом', () => {
  const W = load();
  const model = W.buildModel(parts(), []);

  assert.strictEqual(model.usd.official, 90);
  assert.ok(Math.abs(model.usd.officialChange - 0.5586592) < 1e-5, 'изменение курса ЦБ ко вчера');
  assert.ok(Math.abs(model.usd.spread - 5) < 1e-9, 'рынок на 5% выше официального');
  assert.strictEqual(model.btc.usd, 68000);
  assert.strictEqual(model.btc.rub, 68000 * 94.5, 'цены в рублях не было — посчитана по рыночному курсу');
  assert.strictEqual(model.btc.stats.last, 68000, 'аналитика считается по живой цене');
  assert.strictEqual(model.fng.delta, 4);
  assert.strictEqual(
    model.verdict.label,
    'перекуплен',
    'ряд без единого отката — это RSI 100, и вывод обязан это назвать'
  );
  assert.ok(model.live, 'только что полученные данные считаются живыми');
});

test('цена в рублях берётся из источника, когда он её дал', () => {
  const W = load();
  const withRub = parts();
  withRub.spot.data.btcRub = 6000000;
  assert.strictEqual(W.buildModel(withRub, []).btc.rub, 6000000);
});

test('модель не разваливается, когда не пришло ничего', () => {
  const W = load();
  const model = W.buildModel({}, ['cbr', 'spot']);

  assert.ok(Number.isNaN(model.usd.official));
  assert.ok(Number.isNaN(model.btc.usd));
  assert.deepStrictEqual(model.btc.spark, []);
  assert.strictEqual(model.failed.length, 2);
  assert.strictEqual(model.live, false);
  assert.ok(model.verdict.label, 'вывод есть всегда, даже пустой');
});

test('устаревшие данные помечаются неживыми', () => {
  const W = load();
  const stale = parts({ spot: { at: agoIso(5 * HOUR), data: parts().spot.data } });
  assert.strictEqual(W.buildModel(stale, []).live, false);
});

test('размер виджета определяет набор запросов', () => {
  const W = load();
  assert.deepStrictEqual(W.needsFor('accessoryInline', 'both'), {
    btcHistory: false,
    usdHistory: false,
    fng: false
  });
  assert.strictEqual(W.needsFor('accessoryRectangular', 'both').btcHistory, true);
  assert.deepStrictEqual(W.needsFor('small', 'usd'), {
    btcHistory: false,
    usdHistory: true,
    fng: false
  });
  assert.deepStrictEqual(W.needsFor('small', 'btc'), {
    btcHistory: true,
    usdHistory: false,
    fng: true
  });
  assert.deepStrictEqual(W.needsFor('medium', 'both'), {
    btcHistory: true,
    usdHistory: true,
    fng: true
  });
});

test('параметр виджета понимает и слово, и пары ключ-значение', () => {
  let W = load();
  W.applyParameter('btc');
  assert.strictEqual(W.SETTINGS.asset, 'btc');

  W = load();
  W.applyParameter('  Доллар ');
  assert.strictEqual(W.SETTINGS.asset, 'usd');

  W = load();
  W.applyParameter('asset=usd;days=14;refresh=45;alerts=on');
  assert.strictEqual(W.SETTINGS.asset, 'usd');
  assert.strictEqual(W.SETTINGS.sparkDays, 14);
  assert.strictEqual(W.SETTINGS.refreshMinutes, 45);
  assert.strictEqual(W.SETTINGS.alerts.enabled, true);

  W = load();
  const before = JSON.stringify(W.SETTINGS);
  W.applyParameter('asset=золото;days=3;refresh=99999');
  assert.strictEqual(JSON.stringify(W.SETTINGS), before, 'бессмысленные значения игнорируются');

  W = load();
  W.applyParameter(null);
  assert.strictEqual(W.SETTINGS.asset, 'both', 'без параметра остаются настройки из файла');
});

test('глубина графика не превышает глубину истории', () => {
  const W = load();
  W.applyParameter('days=365');
  assert.strictEqual(W.SETTINGS.sparkDays, W.SETTINGS.historyDays);
});

test('тревоги срабатывают по порогам и молчат без них', () => {
  const W = load();
  const model = W.buildModel(parts(), []);

  const quiet = W.alertChecks(model);
  assert.ok(quiet.every((check) => !check.hit), 'пороги по умолчанию выключены');

  W.SETTINGS.alerts.btcAbove = 60000;
  W.SETTINGS.alerts.usdRubBelow = 95;
  W.SETTINGS.alerts.move24hPct = 2;
  const loud = W.alertChecks(model);
  const hit = loud.filter((check) => check.hit).map((check) => check.key);
  assert.deepStrictEqual(hit.sort(), ['btcAbove', 'move', 'usdBelow']);
  assert.match(loud.find((c) => c.key === 'btcAbove').body(), /68\s000/u);
});

test('история сворачивается в дневные закрытия и точки графика', () => {
  const W = load();
  const now = Date.now();
  const points = [];
  for (let i = 40 * 4; i >= 0; i--) points.push({ t: now - i * 6 * HOUR, v: 100 + i });

  const summary = W.summariseHistory(points);
  assert.ok(summary.daily.length >= 39 && summary.daily.length <= 42, 'по закрытию на день');
  assert.strictEqual(summary.spark.length, 64, 'график прорежен до фиксированной длины');
  assert.strictEqual(summary.spark[summary.spark.length - 1], 100, 'последняя точка — самая свежая');
  assert.ok(
    summary.spark[0] <= 100 + 31 * 4,
    'в график попадают только последние 30 дней, а не вся история'
  );
});

test('пары «время-цена» чистятся от мусора', () => {
  const W = load();
  const points = W.pointsFromPairs([[1000, 10], [2000, 'x'], null, [null, 5], [3000, 30]]);
  assert.deepStrictEqual(points, [{ t: 1000, v: 10 }, { t: 3000, v: 30 }]);
  assert.deepStrictEqual(W.pointsFromPairs(undefined), []);
});

test('возраст модели — по самой свежей части', () => {
  const W = load();
  const newest = W.newestAt({
    a: { at: agoIso(3 * DAY) },
    b: { at: agoIso(HOUR) },
    c: { at: null }
  });
  assert.ok(Date.now() - new Date(newest).getTime() < 2 * HOUR);
});
