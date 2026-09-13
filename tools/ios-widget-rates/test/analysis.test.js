/* Проверка арифметики виджета.
 *
 * Виджет живёт на телефоне, и ошибиться в нём легко незаметно: RSI 45
 * вместо 62 выглядит так же убедительно. Поэтому всё, что считается,
 * проверяется здесь — на эталонном ряду Уайлдера и на рядах, у которых
 * ответ известен заранее.
 *
 * Запуск: node --test tools/ios-widget-rates/test/
 */
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const assert = require('node:assert');

/* Файл рассчитан на Scriptable, поэтому не подключается через require:
 * его исполняют в пустой области видимости, и он отдаёт внутренности
 * через module.exports. Глобалей Scriptable здесь нет, а значит и
 * основной код не запускается — только объявления. */
function load() {
  const file = path.join(__dirname, '..', 'rates-widget.js');
  const source = fs.readFileSync(file, 'utf8');
  const holder = { exports: {} };
  new Function('module', source)(holder);
  return holder.exports;
}

const W = load();

/* Эталонный ряд из «New Concepts in Technical Trading Systems» Уайлдера,
 * тот самый, что разобран в учебниках: первые 15 закрытий дают RSI 70,53,
 * все 33 — 37,77. */
const WILDER = [
  44.3389, 44.0902, 44.1497, 43.6124, 44.3278, 44.8264, 45.0955, 45.4245,
  45.8433, 46.0826, 45.8931, 46.0328, 45.614, 46.282, 46.282, 46.0028,
  46.0328, 46.4116, 46.2222, 45.6439, 46.2122, 46.2521, 45.7137, 46.4515,
  45.7835, 45.3548, 44.0288, 44.1783, 44.2181, 44.5672, 43.4205, 42.6628,
  43.1314
];

test('числа форматируются по-русски: неразрывные разряды и запятая', () => {
  assert.strictEqual(W.fmt(1234567.891, 2), '1 234 567,89');
  assert.strictEqual(W.fmt(92.4, 2), '92,40');
  assert.strictEqual(W.fmt(67240, 0), '67 240');
  assert.strictEqual(W.fmt(-5.5, 1), '−5,5');
  assert.strictEqual(W.fmt(NaN), '—');
  assert.strictEqual(W.fmt(undefined), '—');
});

test('изменение показывается со знаком', () => {
  assert.strictEqual(W.fmtSigned(2.41, 1), '+2,4%');
  assert.strictEqual(W.fmtSigned(-2.41, 1), '−2,4%');
  assert.strictEqual(W.fmtSigned(0, 1), '0,0%');
  assert.strictEqual(W.fmtSigned(NaN), '—');
});

test('короткая запись для тесных мест', () => {
  assert.strictEqual(W.fmtCompact(67240), '67,2K');
  assert.strictEqual(W.fmtCompact(1.32e12), '1,3T');
  assert.strictEqual(W.fmtCompact(950), '950');
  assert.strictEqual(W.fmtCompact(9.5), '9,50');
});

test('стрелка отражает знак и нечувствительна к нулевому шуму', () => {
  assert.strictEqual(W.arrow(1), '↑');
  assert.strictEqual(W.arrow(-1), '↓');
  assert.strictEqual(W.arrow(0.001), '→');
  assert.strictEqual(W.arrow(NaN), '→');
});

test('склонение числительных', () => {
  assert.strictEqual(W.plural(1, 'час', 'часа', 'часов'), 'час');
  assert.strictEqual(W.plural(3, 'час', 'часа', 'часов'), 'часа');
  assert.strictEqual(W.plural(5, 'час', 'часа', 'часов'), 'часов');
  assert.strictEqual(W.plural(11, 'час', 'часа', 'часов'), 'часов');
  assert.strictEqual(W.plural(21, 'час', 'часа', 'часов'), 'час');
});

test('возраст данных называется словами', () => {
  const minutesAgo = (n) => new Date(Date.now() - n * 60000).toISOString();
  assert.strictEqual(W.ago(minutesAgo(0)), 'только что');
  assert.strictEqual(W.ago(minutesAgo(3)), '3 минуты назад');
  assert.strictEqual(W.ago(minutesAgo(120)), '2 часа назад');
  assert.strictEqual(W.ago(minutesAgo(60 * 24 * 3)), '3 дня назад');
  assert.strictEqual(W.ago(null), 'неизвестно когда');
});

test('RSI совпадает с эталоном Уайлдера', () => {
  assert.ok(Math.abs(W.rsi(WILDER.slice(0, 15), 14) - 70.53) < 0.02, 'первое значение 70,53');
  assert.ok(Math.abs(W.rsi(WILDER, 14) - 37.77) < 0.02, 'последнее значение 37,77');
});

test('RSI на краях: рост без откатов, падение без отскоков, короткий ряд', () => {
  const up = Array.from({ length: 30 }, (_, i) => 100 + i);
  const down = Array.from({ length: 30 }, (_, i) => 100 - i);
  const flat = Array.from({ length: 30 }, () => 100);
  assert.strictEqual(W.rsi(up, 14), 100);
  assert.strictEqual(W.rsi(down, 14), 0);
  assert.strictEqual(W.rsi(flat, 14), 50);
  assert.ok(Number.isNaN(W.rsi([1, 2, 3], 14)), 'на коротком ряду RSI не выдумывается');
});

test('скользящая средняя берёт хвост ряда', () => {
  assert.strictEqual(W.sma([1, 2, 3, 4, 5], 5), 3);
  assert.strictEqual(W.sma([1, 2, 3, 4, 10], 2), 7);
  assert.ok(Number.isNaN(W.sma([1, 2], 5)));
});

test('волатильность ровного роста — ноль, скачки её поднимают', () => {
  const steady = Array.from({ length: 60 }, (_, i) => 100 * Math.pow(1.01, i));
  assert.ok(W.annualVolatility(steady) < 1e-9, 'постоянный темп роста не создаёт волатильности');
  const jumpy = Array.from({ length: 60 }, (_, i) => 100 * (i % 2 ? 1.1 : 0.9));
  assert.ok(W.annualVolatility(jumpy) > 100);
  assert.ok(Number.isNaN(W.annualVolatility([1, 2])));
});

test('словесная оценка волатильности', () => {
  assert.strictEqual(W.volatilityLabel(20, [35, 60, 90]), 'спокойно');
  assert.strictEqual(W.volatilityLabel(45, [35, 60, 90]), 'обычно');
  assert.strictEqual(W.volatilityLabel(70, [35, 60, 90]), 'нервно');
  assert.strictEqual(W.volatilityLabel(120, [35, 60, 90]), 'шторм');
});

test('положение в диапазоне', () => {
  const info = W.rangeInfo([10, 20, 30, 25]);
  assert.strictEqual(info.min, 10);
  assert.strictEqual(info.max, 30);
  assert.strictEqual(info.pos, 0.75);
  assert.strictEqual(W.rangeInfo([7, 7, 7]).pos, 0.5, 'плоский ряд — середина, а не деление на ноль');
});

test('тренд определяется разрывом средних и своим порогом', () => {
  const rising = Array.from({ length: 40 }, (_, i) => 100 + i * 2);
  const falling = Array.from({ length: 40 }, (_, i) => 200 - i * 2);
  const noise = Array.from({ length: 40 }, (_, i) => 100 + (i % 2));
  assert.strictEqual(W.trendOf(rising, 1.5).label, 'рост');
  assert.strictEqual(W.trendOf(falling, 1.5).label, 'спад');
  assert.strictEqual(W.trendOf(noise, 1.5).label, 'боком');
  const weak = Array.from({ length: 40 }, (_, i) => 100 + i * 0.1);
  assert.strictEqual(W.trendOf(weak, 1.5).label, 'боком', 'для биткойна это шум');
  assert.strictEqual(W.trendOf(weak, 0.5).label, 'рост', 'для рубля — уже движение');
});

test('часовой ряд сворачивается в дневные закрытия', () => {
  const day = 86400000;
  const points = [
    { t: day * 10 + 3600000, v: 1 },
    { t: day * 10 + 7200000, v: 2 },
    { t: day * 11 + 1000, v: 3 },
    { t: day * 12 + 500, v: 4 },
    { t: day * 12 + 86000000, v: 5 }
  ];
  assert.deepStrictEqual(W.resampleDaily(points), [2, 3, 5]);
  assert.deepStrictEqual(W.resampleDaily([]), []);
  assert.deepStrictEqual(W.resampleDaily([{ t: NaN, v: 1 }]), [], 'мусор отбрасывается');
});

test('прореживание сохраняет длину и последнюю точку', () => {
  const values = Array.from({ length: 500 }, (_, i) => i);
  const thin = W.downsample(values, 64);
  assert.strictEqual(thin.length, 64);
  assert.strictEqual(thin[thin.length - 1], 499, 'последняя цена не теряется');
  assert.deepStrictEqual(W.downsample([1, 2, 3], 64), [1, 2, 3], 'короткий ряд не трогаем');
});

test('сводка считает изменения за сутки, неделю и месяц', () => {
  const closes = Array.from({ length: 40 }, (_, i) => 100 + i);
  const stats = W.analyse(closes, { trendThreshold: 1.5 });
  assert.strictEqual(stats.last, 139);
  assert.ok(Math.abs(stats.d1 - (1 / 138) * 100) < 1e-9);
  assert.ok(Math.abs(stats.d7 - (7 / 132) * 100) < 1e-9);
  assert.ok(Math.abs(stats.d30 - (30 / 109) * 100) < 1e-9);
  const short = W.analyse([100, 101], {});
  assert.ok(Number.isNaN(short.d30), 'месячного изменения на двух точках не бывает');
});

test('живая цена подменяет последнее дневное закрытие', () => {
  assert.deepStrictEqual(W.withLive([1, 2, 3], 9), [1, 2, 9]);
  assert.deepStrictEqual(W.withLive([1, 2, 3], NaN), [1, 2, 3]);
  assert.deepStrictEqual(W.withLive([], 9), [9]);
  assert.deepStrictEqual(W.withLive(null, NaN), []);
});

test('вывод складывается из RSI, тренда и настроения', () => {
  assert.strictEqual(W.verdictFor({ rsiValue: 78, trend: { dir: 1 }, fng: 80 }).label, 'перегрев: жадность и перекупленность');
  assert.strictEqual(W.verdictFor({ rsiValue: 75, trend: { dir: 1 }, fng: 50 }).label, 'перекуплен');
  assert.strictEqual(W.verdictFor({ rsiValue: 22, trend: { dir: -1 }, fng: 12 }).label, 'паника: перепродан на страхе');
  assert.strictEqual(W.verdictFor({ rsiValue: 60, trend: { dir: 1 }, fng: 50 }).label, 'уверенный рост');
  assert.strictEqual(W.verdictFor({ rsiValue: 50, trend: { dir: 0 }, fng: 50 }).label, 'равновесие');
  assert.strictEqual(W.verdictFor({ rsiValue: NaN, trend: { dir: -1 }, fng: NaN }).label, 'тренд вниз');
});

test('индекс страха переводится на русский', () => {
  assert.strictEqual(W.fngLabel('Extreme Greed'), 'крайняя жадность');
  assert.strictEqual(W.fngLabel('Fear'), 'страх');
  assert.strictEqual(W.fngLabel('Unknown mood'), 'Unknown mood');
  assert.strictEqual(W.fngLabel(null), '');
});

test('отрыв рынка от официального курса', () => {
  assert.ok(Math.abs(W.spreadPct(90, 94.5) - 5) < 1e-9);
  assert.ok(Number.isNaN(W.spreadPct(0, 94.5)));
});
