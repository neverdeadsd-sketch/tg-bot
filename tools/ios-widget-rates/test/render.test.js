/* Проверка сборки самого виджета.
 *
 * Раскладку нельзя посмотреть глазами из командной строки, но можно
 * подменить объекты Scriptable заглушками и убедиться в главном:
 * ни один размер виджета не падает, нужные числа доходят до текста,
 * а пустая модель — когда не ответил вообще никто — рисуется так же
 * спокойно, как полная. Именно на этом обычно и ломаются виджеты:
 * опечатка в имени метода видна только на телефоне и только пустым
 * прямоугольником без объяснений.
 *
 * Запуск: node --test tools/ios-widget-rates/test/render.test.js
 */
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const assert = require('node:assert');

const FAMILIES = [
  'small',
  'medium',
  'large',
  'extraLarge',
  'accessoryInline',
  'accessoryCircular',
  'accessoryRectangular'
];

/* ── Заглушки Scriptable ── */

class MockText {
  constructor(value) {
    this.value = String(value);
  }
  centerAlignText() {}
  leftAlignText() {}
  rightAlignText() {}
}

class MockImage {
  constructor(image) {
    this.image = image;
  }
}

class MockStack {
  constructor() {
    this.children = [];
  }
  addStack() {
    const stack = new MockStack();
    this.children.push(stack);
    return stack;
  }
  addText(value) {
    const text = new MockText(value);
    this.children.push(text);
    return text;
  }
  addImage(image) {
    assert.ok(image, 'в виджет нельзя добавить пустую картинку');
    const widgetImage = new MockImage(image);
    this.children.push(widgetImage);
    return widgetImage;
  }
  addSpacer() {}
  layoutHorizontally() {}
  layoutVertically() {}
  centerAlignContent() {}
  topAlignContent() {}
  bottomAlignContent() {}
  setPadding() {}
}

class MockListWidget extends MockStack {
  presentLarge() {}
}

class MockColor {
  constructor(hex, alpha) {
    assert.match(String(hex), /^#[0-9A-Fa-f]{6}$/u, 'цвет задаётся шестизначным hex');
    this.hex = hex;
    this.alpha = alpha;
  }
  static dynamic(light, dark) {
    assert.ok(light && dark, 'у динамического цвета должны быть обе темы');
    return new MockColor(light.hex, light.alpha);
  }
  static white() {
    return new MockColor('#FFFFFF');
  }
  static gray() {
    return new MockColor('#808080');
  }
}

class MockPath {
  constructor() {
    this.points = [];
  }
  move(point) {
    this.points.push(point);
  }
  addLine(point) {
    this.points.push(point);
  }
  addLines(points) {
    assert.ok(Array.isArray(points), 'addLines принимает массив точек');
    this.points.push(...points);
  }
  addRoundedRect() {}
  closeSubpath() {}
}

class MockDrawContext {
  constructor() {
    this.calls = [];
    this.size = null;
  }
  setFillColor(color) {
    assert.ok(color, 'цвет заливки не задан');
  }
  setStrokeColor(color) {
    assert.ok(color, 'цвет линии не задан');
  }
  setLineWidth() {}
  addPath(path) {
    assert.ok(path instanceof MockPath);
    this.calls.push('addPath');
  }
  fillPath() {
    this.calls.push('fillPath');
  }
  strokePath() {
    this.calls.push('strokePath');
  }
  fillRect() {
    this.calls.push('fillRect');
  }
  fillEllipse() {
    this.calls.push('fillEllipse');
  }
  getImage() {
    assert.ok(this.size, 'у холста должен быть размер');
    return { drawn: this.calls.slice() };
  }
}

function installStubs() {
  const g = globalThis;
  g.ListWidget = MockListWidget;
  g.Color = MockColor;
  g.Path = MockPath;
  g.DrawContext = MockDrawContext;
  g.Font = new Proxy({}, { get: (_, name) => (size) => ({ name, size }) });
  g.LinearGradient = class {};
  g.Point = class {
    constructor(x, y) {
      assert.ok(Number.isFinite(x) && Number.isFinite(y), 'точка с нечисловой координатой');
      this.x = x;
      this.y = y;
    }
  };
  g.Size = class {
    constructor(width, height) {
      assert.ok(Number.isFinite(width) && Number.isFinite(height), 'размер должен быть числом');
      this.width = width;
      this.height = height;
    }
  };
  g.Rect = class {
    constructor(x, y, width, height) {
      assert.ok([x, y, width, height].every(Number.isFinite), 'прямоугольник с нечисловой стороной');
    }
  };
  g.Device = { screenSize: () => ({ width: 393, height: 852 }) };
  g.Script = { name: () => 'Курсы', setWidget() {}, complete() {} };
}

/* Файл загружается до установки заглушек: пока глобалей Scriptable нет,
 * он считает себя обычным модулем и не пытается сам себя запустить. */
function load() {
  const source = fs.readFileSync(path.join(__dirname, '..', 'rates-widget.js'), 'utf8');
  const holder = { exports: {} };
  new Function('module', source)(holder);
  return holder.exports;
}

const W = load();
installStubs();

const ramp = (length, from, step) => Array.from({ length }, (_, i) => from + i * step);

function fullModel() {
  const now = new Date().toISOString();
  return W.buildModel(
    {
      cbr: { at: now, data: { date: '2026-09-13T11:30:00+03:00', usd: 90, usdPrev: 89.5, eur: 100, cny: 12.5 } },
      spot: {
        at: now,
        data: {
          btcUsd: 68000,
          btcRub: 6426000,
          btcChange24h: 2.5,
          btcVolume24h: 3e10,
          btcCap: 1.3e12,
          marketUsdRub: 94.5,
          marketChange24h: 0.4,
          source: 'CoinGecko'
        }
      },
      btcHistory: { at: now, data: { daily: ramp(60, 60000, 140), spark: ramp(120, 62000, 50) } },
      usdHistory: { at: now, data: { daily: ramp(60, 88, 0.05), spark: ramp(120, 88, 0.05) } },
      fng: { at: now, data: { value: 54, label: 'нейтрально', prev: 50 } }
    },
    []
  );
}

function texts(node, out) {
  const found = out || [];
  if (node instanceof MockText) found.push(node.value);
  if (node && node.children) node.children.forEach((child) => texts(child, found));
  return found;
}

test('все размеры виджета собираются и показывают свои числа', () => {
  const model = fullModel();
  for (const family of FAMILIES) {
    const widget = W.buildWidget(model, family);
    const shown = texts(widget).join(' | ');
    assert.ok(shown.length > 0, `${family}: виджет остался пустым`);
    assert.ok(!shown.includes('undefined'), `${family}: в текст пролезло undefined — ${shown}`);
    assert.ok(!shown.includes('NaN'), `${family}: в текст пролезло NaN — ${shown}`);
    assert.ok(widget.refreshAfterDate > new Date(), `${family}: не назначено обновление`);
    assert.match(widget.url, /^scriptable:\/\/\/run/u, `${family}: нажатие никуда не ведёт`);
  }
});

test('в больших размерах видны и курс, и аналитика', () => {
  const shown = texts(W.buildWidget(fullModel(), 'large')).join(' | ');
  assert.match(shown, /90,00 ₽/u, 'курс ЦБ');
  assert.match(shown, /68\s000/u, 'цена биткойна');
  assert.match(shown, /RSI 14/u);
  assert.match(shown, /тренд/u);
  assert.match(shown, /страх и жадность 54, нейтрально/u);
  assert.match(shown, /ЦБ на 13\.09/u, 'дата официального курса');
  assert.match(shown, /CoinGecko/u, 'источник назван');
});

test('средний виджет показывает оба актива и вывод', () => {
  const shown = texts(W.buildWidget(fullModel(), 'medium')).join(' | ');
  assert.match(shown, /ДОЛЛАР/u);
  assert.match(shown, /БИТКОЙН/u);
  assert.match(shown, /рынок 94,50/u, 'рыночный курс не потерялся');
  assert.match(shown, /6,43 млн ₽/u, 'цена биткойна в рублях помещается в узкую колонку');
});

test('на экране блокировки помещается главное', () => {
  const model = fullModel();
  const inline = texts(W.buildWidget(model, 'accessoryInline')).join(' ');
  assert.match(inline, /₽/u);
  assert.match(inline, /₿/u);
  const circular = texts(W.buildWidget(model, 'accessoryCircular')).join(' ');
  assert.match(circular, /68,0K/u);
});

test('маленький виджет слушается параметра', () => {
  const model = fullModel();
  const settings = W.SETTINGS;
  const before = settings.asset;
  try {
    settings.asset = 'btc';
    const btc = texts(W.buildWidget(model, 'small')).join(' | ');
    assert.match(btc, /БИТКОЙН/u);
    assert.ok(!btc.includes('ДОЛЛАР'), 'при asset=btc доллару в малом виджете места нет');

    settings.asset = 'usd';
    const usd = texts(W.buildWidget(model, 'small')).join(' | ');
    assert.match(usd, /ДОЛЛАР/u);
    assert.ok(!usd.includes('БИТКОЙН'));

    settings.asset = 'both';
    const both = texts(W.buildWidget(model, 'small')).join(' | ');
    assert.match(both, /ДОЛЛАР/u);
    assert.match(both, /БИТКОЙН/u);
  } finally {
    settings.asset = before;
  }
});

test('пустая модель рисуется без падений и без выдуманных чисел', () => {
  const empty = W.buildModel({}, ['cbr', 'spot', 'btcHistory', 'usdHistory', 'fng']);
  for (const family of FAMILIES) {
    const widget = W.buildWidget(empty, family);
    const shown = texts(widget).join(' | ');
    assert.ok(!shown.includes('NaN'), `${family}: NaN вместо прочерка — ${shown}`);
    assert.ok(!shown.includes('undefined'), `${family}: undefined в тексте — ${shown}`);
  }
  const shown = texts(W.buildWidget(empty, 'large')).join(' | ');
  assert.match(shown, /—/u, 'неизвестное число показано прочерком');
});

test('график рисуется по точкам, а короткий ряд честно не рисуется', () => {
  const image = W.sparkline(ramp(120, 100, 1), {
    width: 300,
    height: 40,
    color: new MockColor('#F7931A'),
    fill: new MockColor('#F7931A', 0.2)
  });
  assert.ok(image && image.drawn.includes('strokePath'), 'линия не прочерчена');
  assert.ok(image.drawn.includes('fillPath'), 'заливка под линией не нарисована');
  assert.ok(image.drawn.includes('fillEllipse'), 'точка «сейчас» не поставлена');

  const flat = W.sparkline([5, 5, 5, 5], {
    width: 100,
    height: 20,
    color: new MockColor('#0A84FF'),
    fill: new MockColor('#0A84FF', 0.2)
  });
  assert.ok(flat, 'плоский ряд — не повод падать с делением на ноль');
  assert.strictEqual(
    W.sparkline([], { width: 100, height: 20, color: new MockColor('#0A84FF'), fill: new MockColor('#0A84FF') }),
    null,
    'из пустого ряда график не выдумывается'
  );
});

test('отказ всего сразу показывает объяснение, а не пустой прямоугольник', () => {
  const widget = W.buildFailure(new Error('нет сети'));
  const shown = texts(widget).join(' | ');
  assert.match(shown, /Курсы недоступны/u);
  assert.match(shown, /нет сети/u);
  assert.ok(widget.refreshAfterDate > new Date());
});
