/* Курс доллара и биткойна — виджет для iPhone (Scriptable).
 *
 * Показывает не только цену, но и то, что с ней происходит: изменение за
 * сутки, неделю и месяц, график, RSI, направление скользящих средних,
 * волатильность, положение в месячном диапазоне, индекс страха и жадности.
 *
 * Два правила, вокруг которых всё построено:
 *
 * 1. Виджет никогда не показывает пустой экран. Любой источник может
 *    отвалиться — лимитом запросов, таймаутом, блокировкой. Поэтому каждый
 *    ответ кладётся в кэш, недостающее берётся оттуда, а возраст данных
 *    честно подписан. Ошибка сети означает «данные постарше», а не «—».
 *
 * 2. Числа названы своими именами. Курс ЦБ и курс рынка — разные числа,
 *    и виджет показывает оба и разницу между ними, вместо того чтобы
 *    выдавать одно за другое.
 *
 * Установка: Scriptable (App Store) → «+» → вставить этот файл → назвать
 * «Курсы» → на домашнем экране добавить виджет Scriptable → выбрать скрипт.
 * Подробнее и про параметр виджета — в README.md рядом.
 */

/* ─────────────────────────── Настройки ─────────────────────────── */

const SETTINGS = {
  // Что показывать в маленьком виджете: 'btc', 'usd' или 'both'.
  asset: 'both',
  // Глубина графика и аналитики в днях. 90 хватает на RSI(14) и SMA(30).
  historyDays: 90,
  sparkDays: 30,
  // Как часто iOS стоит обновлять виджет. Система вправе решить иначе.
  refreshMinutes: 20,
  // Сколько часов кэш ещё годится к показу, если сеть недоступна.
  cacheHours: 24,
  // Необязательный demo-ключ CoinGecko: без него тоже работает, с ним реже
  // упирается в лимит запросов. https://www.coingecko.com/en/api
  coingeckoKey: '',
  // Порог, после которого движение подсвечивается как заметное, в процентах.
  notableMovePct: 3,
  // Уведомления. Срабатывают, когда скрипт запускается — из приложения или
  // по автоматизации в «Командах». Из фонового обновления виджета iOS
  // уведомления отдаёт не всегда, поэтому это дополнение, а не сигнализация.
  alerts: {
    enabled: false,
    btcAbove: 0,          // 0 — порог выключен
    btcBelow: 0,
    usdRubAbove: 0,
    usdRubBelow: 0,
    move24hPct: 7,        // резкое движение биткойна за сутки
    cooldownMinutes: 180  // не повторять одну и ту же тревогу чаще
  }
};

const SOURCES = {
  cbr: 'https://www.cbr-xml-daily.ru/daily_json.js',
  coingecko: 'https://api.coingecko.com/api/v3',
  binance: 'https://api.binance.com/api/v3',
  erapi: 'https://open.er-api.com/v6/latest/USD',
  fng: 'https://api.alternative.me/fng/?limit=2'
};

const CACHE_FILE = 'rates-widget-cache.json';
const NBSP = '\u00A0';
const MINUS = '−';

/* Скрипт же используется и как обычный модуль — тестами. Признак среды:
 * глобальные объекты Scriptable. Без них исполняется только чистая
 * арифметика, экспортируемая в конце файла. */
const IS_SCRIPTABLE = typeof ListWidget !== 'undefined';

/* ─────────────────────────── Числа и текст ─────────────────────────── */

function isNum(v) {
  return typeof v === 'number' && Number.isFinite(v);
}

function num(v) {
  const n = typeof v === 'string' ? Number(v) : v;
  return isNum(n) ? n : NaN;
}

/* Пробел между разрядами — неразрывный: иначе число переносится по строкам
 * прямо посередине и виджет выглядит сломанным. */
function fmt(value, digits = 2) {
  if (!isNum(value)) return '—';
  const fixed = Math.abs(value).toFixed(digits);
  const dot = fixed.indexOf('.');
  const whole = dot === -1 ? fixed : fixed.slice(0, dot);
  const frac = dot === -1 ? '' : fixed.slice(dot + 1);
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, NBSP);
  return (value < 0 ? MINUS : '') + grouped + (frac ? ',' + frac : '');
}

function fmtSigned(value, digits = 1, suffix = '%') {
  if (!isNum(value)) return '—';
  const sign = value > 0 ? '+' : value < 0 ? MINUS : '';
  return sign + fmt(Math.abs(value), digits) + suffix;
}

/* Короткая запись для мест, где нет ширины: 67 240 → 67,2K. */
function fmtCompact(value, digits = 1) {
  if (!isNum(value)) return '—';
  const abs = Math.abs(value);
  const units = [[1e12, 'T'], [1e9, 'B'], [1e6, 'M'], [1e3, 'K']];
  for (const [scale, suffix] of units) {
    if (abs >= scale) return fmt(value / scale, digits) + suffix;
  }
  return fmt(value, abs < 10 ? 2 : 0);
}

function arrow(value) {
  if (!isNum(value) || Math.abs(value) < 0.005) return '→';
  return value > 0 ? '↑' : '↓';
}

function plural(n, one, few, many) {
  const a = Math.abs(n) % 100;
  const b = a % 10;
  if (a > 10 && a < 20) return many;
  if (b > 1 && b < 5) return few;
  if (b === 1) return one;
  return many;
}

function ago(iso) {
  if (!iso) return 'неизвестно когда';
  const minutes = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (minutes < 1) return 'только что';
  if (minutes < 60) return `${minutes}${NBSP}${plural(minutes, 'минуту', 'минуты', 'минут')} назад`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}${NBSP}${plural(hours, 'час', 'часа', 'часов')} назад`;
  const days = Math.round(hours / 24);
  return `${days}${NBSP}${plural(days, 'день', 'дня', 'дней')} назад`;
}

function clock(iso) {
  const d = iso ? new Date(iso) : new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function dmy(value) {
  if (!value) return '';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '';
  const pad = (n) => String(n).padStart(2, '0');
  return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}`;
}

/* ─────────────────────────── Аналитика ───────────────────────────
 *
 * Всё ниже — чистая арифметика над рядом дневных закрытий: ни сети,
 * ни Scriptable. Поэтому она проверяется тестами в test/analysis.test.js,
 * а не на глаз по телефону.
 */

function pctChange(from, to) {
  if (!isNum(from) || !isNum(to) || from === 0) return NaN;
  return ((to - from) / Math.abs(from)) * 100;
}

function mean(values) {
  if (!values.length) return NaN;
  let sum = 0;
  for (const v of values) sum += v;
  return sum / values.length;
}

/* Выборочное отклонение: ряд котировок — не вся генеральная совокупность. */
function stdev(values) {
  if (values.length < 2) return NaN;
  const m = mean(values);
  let acc = 0;
  for (const v of values) acc += (v - m) * (v - m);
  return Math.sqrt(acc / (values.length - 1));
}

function sma(values, period) {
  if (!Array.isArray(values) || values.length < period || period < 1) return NaN;
  return mean(values.slice(values.length - period));
}

/* RSI по Уайлдеру: первое значение — простое среднее за период, дальше
 * сглаживание с весом 1/period. Это тот RSI, который рисуют биржевые
 * терминалы; наивный вариант «среднее за последние 14» даёт другие числа. */
function rsi(values, period = 14) {
  if (!Array.isArray(values) || values.length < period + 1) return NaN;
  let gain = 0;
  let loss = 0;
  for (let i = 1; i <= period; i++) {
    const delta = values[i] - values[i - 1];
    if (delta >= 0) gain += delta;
    else loss -= delta;
  }
  gain /= period;
  loss /= period;
  for (let i = period + 1; i < values.length; i++) {
    const delta = values[i] - values[i - 1];
    gain = (gain * (period - 1) + Math.max(delta, 0)) / period;
    loss = (loss * (period - 1) + Math.max(-delta, 0)) / period;
  }
  if (loss === 0) return gain === 0 ? 50 : 100;
  return 100 - 100 / (1 + gain / loss);
}

/* Годовая волатильность: отклонение дневных логарифмических доходностей,
 * растянутое на год. Логарифм, а не проценты, чтобы падение на 50%
 * и рост на 100% весили одинаково. */
function annualVolatility(closes) {
  const returns = [];
  for (let i = 1; i < closes.length; i++) {
    const a = closes[i - 1];
    const b = closes[i];
    if (isNum(a) && isNum(b) && a > 0 && b > 0) returns.push(Math.log(b / a));
  }
  if (returns.length < 5) return NaN;
  return stdev(returns) * Math.sqrt(365) * 100;
}

function volatilityLabel(value, scale) {
  if (!isNum(value)) return '—';
  const [calm, normal, nervous] = scale;
  if (value < calm) return 'спокойно';
  if (value < normal) return 'обычно';
  if (value < nervous) return 'нервно';
  return 'шторм';
}

function rangeInfo(values) {
  const clean = (values || []).filter(isNum);
  if (!clean.length) return { min: NaN, max: NaN, pos: NaN };
  let min = clean[0];
  let max = clean[0];
  for (const v of clean) {
    if (v < min) min = v;
    if (v > max) max = v;
  }
  const last = clean[clean.length - 1];
  return { min, max, pos: max > min ? (last - min) / (max - min) : 0.5 };
}

/* Направление задаётся разрывом между быстрой и медленной средней.
 * Порог разный для разных рынков: 1,5% для биткойна — обычный шум,
 * для рубля — уже событие. */
function trendOf(closes, threshold = 1.5) {
  const fast = sma(closes, 7);
  const slow = sma(closes, 30);
  if (!isNum(fast) || !isNum(slow) || slow === 0) return { dir: 0, gap: NaN, label: '—' };
  const gap = ((fast - slow) / slow) * 100;
  if (gap > threshold) return { dir: 1, gap, label: 'рост' };
  if (gap < -threshold) return { dir: -1, gap, label: 'спад' };
  return { dir: 0, gap, label: 'боком' };
}

/* Ряд приходит почасовым; аналитика считается по дневным закрытиям —
 * иначе RSI(14) охватит полтора дня вместо двух недель. */
function resampleDaily(points) {
  if (!Array.isArray(points) || !points.length) return [];
  const byDay = new Map();
  for (const p of points) {
    if (!p || !isNum(p.t) || !isNum(p.v)) continue;
    const day = Math.floor(p.t / 86400000);
    const kept = byDay.get(day);
    if (!kept || p.t >= kept.t) byDay.set(day, p);
  }
  return [...byDay.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([, p]) => p.v);
}

/* Точек в ряду сотни, пикселей у графика — десятки. Прореживаем средним
 * по корзинам: так шум не выдаёт себя за форму. */
function downsample(values, count) {
  const clean = (values || []).filter(isNum);
  if (clean.length <= count || count < 2) return clean;
  const step = clean.length / count;
  const out = [];
  for (let i = 0; i < count; i++) {
    const from = Math.floor(i * step);
    const to = Math.max(from + 1, Math.floor((i + 1) * step));
    out.push(mean(clean.slice(from, to)));
  }
  out[out.length - 1] = clean[clean.length - 1];
  return out;
}

function analyse(closes, options = {}) {
  const series = (closes || []).filter(isNum);
  const n = series.length;
  const last = n ? series[n - 1] : NaN;
  const threshold = isNum(options.trendThreshold) ? options.trendThreshold : 1.5;
  const scale = options.volatilityScale || [35, 60, 90];
  const volatility = annualVolatility(series);
  return {
    points: n,
    last,
    rsi: rsi(series, 14),
    sma7: sma(series, 7),
    sma30: sma(series, 30),
    trend: trendOf(series, threshold),
    volatility,
    volatilityLabel: volatilityLabel(volatility, scale),
    range: rangeInfo(series.slice(-30)),
    d1: n >= 2 ? pctChange(series[n - 2], last) : NaN,
    d7: n >= 8 ? pctChange(series[n - 8], last) : NaN,
    d30: n >= 31 ? pctChange(series[n - 31], last) : NaN
  };
}

/* Короткий вывод. Это описание состояния рынка, а не совет: RSI выше 70
 * веками сопровождал и развороты, и продолжение роста. */
function verdictFor({ rsiValue, trend, fng }) {
  const hasRsi = isNum(rsiValue);
  const hasFng = isNum(fng);
  if (hasRsi && rsiValue >= 70) {
    if (hasFng && fng >= 75) return { label: 'перегрев: жадность и перекупленность', tone: 'down' };
    return { label: 'перекуплен', tone: 'down' };
  }
  if (hasRsi && rsiValue <= 30) {
    if (hasFng && fng <= 25) return { label: 'паника: перепродан на страхе', tone: 'up' };
    return { label: 'перепродан', tone: 'up' };
  }
  if (trend && trend.dir > 0) {
    return { label: hasRsi && rsiValue > 55 ? 'уверенный рост' : 'тренд вверх', tone: 'up' };
  }
  if (trend && trend.dir < 0) {
    return { label: hasRsi && rsiValue < 45 ? 'устойчивое снижение' : 'тренд вниз', tone: 'down' };
  }
  return { label: 'равновесие', tone: 'flat' };
}

const FNG_RU = {
  'extreme fear': 'крайний страх',
  fear: 'страх',
  neutral: 'нейтрально',
  greed: 'жадность',
  'extreme greed': 'крайняя жадность'
};

function fngLabel(classification) {
  if (!classification) return '';
  return FNG_RU[String(classification).toLowerCase()] || String(classification);
}

/* Разница между курсом ЦБ и рыночным: ЦБ ставит курс на завтра по итогам
 * вчерашних торгов, рынок живёт сейчас. Спред показывает, насколько
 * официальное число отстало. */
function spreadPct(official, market) {
  return pctChange(official, market);
}

/* ─────────────────────── Источники данных ───────────────────────
 *
 * У каждого числа есть запасной источник, а у всего вместе — кэш на диске.
 * Ни один отказ не должен превращать виджет в набор прочерков.
 */

async function fetchJSON(url, timeout = 12) {
  const request = new Request(url);
  request.timeoutInterval = timeout;
  request.headers = { Accept: 'application/json' };
  const data = await request.loadJSON();
  if (data == null) throw new Error('пустой ответ: ' + url);
  return data;
}

async function coingecko(path) {
  const request = new Request(SOURCES.coingecko + path);
  request.timeoutInterval = 14;
  request.headers = SETTINGS.coingeckoKey
    ? { Accept: 'application/json', 'x-cg-demo-api-key': SETTINGS.coingeckoKey }
    : { Accept: 'application/json' };
  const data = await request.loadJSON();
  if (!data || data.status) throw new Error('CoinGecko отказал: ' + path);
  return data;
}

/* Официальный курс. Номинал делим: у ЦБ иена и им подобные котируются
 * за сотню, и без деления получится курс в сто раз мимо. */
async function fetchCbr() {
  const data = await fetchJSON(SOURCES.cbr);
  const valute = data && data.Valute;
  if (!valute || !valute.USD) throw new Error('ЦБ: в ответе нет доллара');
  const rate = (code) => {
    const item = valute[code];
    if (!item) return { value: NaN, prev: NaN };
    const nominal = num(item.Nominal) || 1;
    return { value: num(item.Value) / nominal, prev: num(item.Previous) / nominal };
  };
  const usd = rate('USD');
  return {
    date: data.Date || null,
    usd: usd.value,
    usdPrev: usd.prev,
    eur: rate('EUR').value,
    cny: rate('CNY').value
  };
}

/* Цены «сейчас». Тезер в рублях здесь — это рыночный доллар: на бирже
 * за него дают ровно столько, сколько стоит доллар на крипторынке. */
async function fetchSpot() {
  try {
    const data = await coingecko(
      '/simple/price?ids=bitcoin,tether&vs_currencies=usd,rub' +
        '&include_24hr_change=true&include_24hr_vol=true&include_market_cap=true'
    );
    const btc = data.bitcoin;
    const usdt = data.tether;
    if (!btc || !isNum(num(btc.usd))) throw new Error('CoinGecko: нет цены биткойна');
    return {
      btcUsd: num(btc.usd),
      btcRub: num(btc.rub),
      btcChange24h: num(btc.usd_24h_change),
      btcVolume24h: num(btc.usd_24h_vol),
      btcCap: num(btc.usd_market_cap),
      marketUsdRub: usdt ? num(usdt.rub) : NaN,
      marketChange24h: usdt ? num(usdt.rub_24h_change) : NaN,
      source: 'CoinGecko'
    };
  } catch (error) {
    return await fetchSpotFallback(error);
  }
}

async function fetchSpotFallback(reason) {
  const [ticker, fx] = await Promise.allSettled([
    fetchJSON(SOURCES.binance + '/ticker/24hr?symbol=BTCUSDT'),
    fetchJSON(SOURCES.erapi)
  ]);
  const t = ticker.status === 'fulfilled' ? ticker.value : null;
  const f = fx.status === 'fulfilled' ? fx.value : null;
  const btcUsd = t ? num(t.lastPrice) : NaN;
  // Молчат оба запасных — пусть отвечает кэш, а не выдуманные числа.
  if (!isNum(btcUsd)) throw reason;
  const marketUsdRub = f && f.rates ? num(f.rates.RUB) : NaN;
  return {
    btcUsd,
    btcRub: isNum(marketUsdRub) ? btcUsd * marketUsdRub : NaN,
    btcChange24h: t ? num(t.priceChangePercent) : NaN,
    btcVolume24h: t ? num(t.quoteVolume) : NaN,
    btcCap: NaN,
    marketUsdRub,
    marketChange24h: NaN,
    source: 'Binance + open.er-api'
  };
}

function pointsFromPairs(pairs) {
  if (!Array.isArray(pairs)) return [];
  return pairs
    .map((pair) => ({ t: num(pair && pair[0]), v: num(pair && pair[1]) }))
    .filter((p) => isNum(p.t) && isNum(p.v));
}

/* Ряд сразу сворачивается в то, что нужно показать и посчитать: дневные
 * закрытия для аналитики и десятки точек для графика. Хранить в кэше
 * сырые сотни точек незачем. */
function summariseHistory(points) {
  const from = Date.now() - SETTINGS.sparkDays * 86400000;
  const recent = points.filter((p) => p.t >= from).map((p) => p.v);
  return {
    daily: resampleDaily(points),
    spark: downsample(recent.length >= 2 ? recent : points.map((p) => p.v), 64)
  };
}

async function fetchBtcHistory() {
  const days = SETTINGS.historyDays;
  try {
    const data = await coingecko(`/coins/bitcoin/market_chart?vs_currency=usd&days=${days}`);
    const points = pointsFromPairs(data.prices);
    if (points.length < 20) throw new Error('CoinGecko: слишком короткий ряд');
    return summariseHistory(points);
  } catch (error) {
    const raw = await fetchJSON(`${SOURCES.binance}/klines?symbol=BTCUSDT&interval=1d&limit=${days}`);
    if (!Array.isArray(raw) || raw.length < 20) throw error;
    const points = raw
      .map((k) => ({ t: num(k && k[0]), v: num(k && k[4]) }))
      .filter((p) => isNum(p.t) && isNum(p.v));
    return summariseHistory(points);
  }
}

async function fetchUsdHistory() {
  const data = await coingecko(
    `/coins/tether/market_chart?vs_currency=rub&days=${SETTINGS.historyDays}`
  );
  const points = pointsFromPairs(data.prices);
  if (points.length < 20) throw new Error('CoinGecko: слишком короткий ряд по рублю');
  return summariseHistory(points);
}

async function fetchFng() {
  const data = await fetchJSON(SOURCES.fng);
  const rows = data && Array.isArray(data.data) ? data.data : [];
  if (!rows.length) throw new Error('индекс страха: пустой ответ');
  return {
    value: num(rows[0].value),
    label: fngLabel(rows[0].value_classification),
    prev: rows[1] ? num(rows[1].value) : NaN
  };
}

/* ─────────────────────────── Кэш ─────────────────────────── */

function cachePath() {
  const fm = FileManager.local();
  return fm.joinPath(fm.documentsDirectory(), CACHE_FILE);
}

function readCache() {
  try {
    const fm = FileManager.local();
    const path = cachePath();
    if (!fm.fileExists(path)) return {};
    const parsed = JSON.parse(fm.readString(path));
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch (error) {
    return {};
  }
}

function writeCache(cache) {
  try {
    FileManager.local().writeString(cachePath(), JSON.stringify(cache));
  } catch (error) {
    // Диск недоступен — не повод ронять виджет: он уже всё показал.
  }
}

function fresherThan(at, hours) {
  if (!at) return false;
  const ts = new Date(at).getTime();
  return Number.isFinite(ts) && Date.now() - ts < hours * 3600000;
}

/* Свежее вытесняет старое, старое закрывает дыры от неудачных запросов,
 * протухшее выбрасывается. Возраст каждой части остаётся при ней. */
function mergeParts(fresh, cached) {
  const now = new Date().toISOString();
  const parts = {};
  const keys = new Set([...Object.keys(fresh), ...Object.keys(cached || {})]);
  for (const key of keys) {
    if (fresh[key] !== undefined) parts[key] = { at: now, data: fresh[key] };
    else if (cached[key] && fresherThan(cached[key].at, SETTINGS.cacheHours)) parts[key] = cached[key];
  }
  return parts;
}

/* ─────────────────────── Сборка картины мира ─────────────────────── */

/* Последнее дневное закрытие — это «сегодня, но час назад». Заменяем его
 * живой ценой, иначе изменение за сутки спорит с крупной цифрой рядом. */
function withLive(daily, live) {
  const series = Array.isArray(daily) ? daily.filter(isNum) : [];
  if (!isNum(live)) return series;
  if (!series.length) return [live];
  const out = series.slice();
  out[out.length - 1] = live;
  return out;
}

function newestAt(parts) {
  let newest = null;
  for (const key of Object.keys(parts)) {
    const at = parts[key] && parts[key].at;
    if (!at) continue;
    if (!newest || new Date(at) > new Date(newest)) newest = at;
  }
  return newest;
}

function buildModel(parts, failed) {
  const cbr = parts.cbr ? parts.cbr.data : null;
  const spot = parts.spot ? parts.spot.data : null;
  const btcHistory = parts.btcHistory ? parts.btcHistory.data : null;
  const usdHistory = parts.usdHistory ? parts.usdHistory.data : null;
  const fng = parts.fng ? parts.fng.data : null;

  const official = cbr ? cbr.usd : NaN;
  const market = spot ? spot.marketUsdRub : NaN;
  const btcUsd = spot ? spot.btcUsd : NaN;

  const btcStats = analyse(withLive(btcHistory && btcHistory.daily, btcUsd), {
    trendThreshold: 1.5,
    volatilityScale: [35, 60, 90]
  });
  // Рубль на порядок спокойнее биткойна, пороги у него свои.
  const usdStats = analyse(withLive(usdHistory && usdHistory.daily, market), {
    trendThreshold: 0.5,
    volatilityScale: [6, 12, 20]
  });

  return {
    at: newestAt(parts),
    spotAt: parts.spot ? parts.spot.at : null,
    live: fresherThan(parts.spot ? parts.spot.at : null, 1),
    failed: failed || [],
    usd: {
      official,
      officialPrev: cbr ? cbr.usdPrev : NaN,
      officialDate: cbr ? cbr.date : null,
      officialChange: cbr ? pctChange(cbr.usdPrev, cbr.usd) : NaN,
      market,
      marketChange24h: spot ? spot.marketChange24h : NaN,
      spread: spreadPct(official, market),
      stats: usdStats,
      spark: usdHistory ? usdHistory.spark : [],
      eur: cbr ? cbr.eur : NaN,
      cny: cbr ? cbr.cny : NaN
    },
    btc: {
      usd: btcUsd,
      rub: spot && isNum(spot.btcRub)
        ? spot.btcRub
        : isNum(btcUsd) && isNum(market)
          ? btcUsd * market
          : NaN,
      change24h: spot ? spot.btcChange24h : NaN,
      volume24h: spot ? spot.btcVolume24h : NaN,
      cap: spot ? spot.btcCap : NaN,
      stats: btcStats,
      spark: btcHistory ? btcHistory.spark : [],
      source: spot ? spot.source : null
    },
    fng: fng
      ? { value: fng.value, label: fng.label, prev: fng.prev, delta: fng.value - fng.prev }
      : null,
    verdict: verdictFor({
      rsiValue: btcStats.rsi,
      trend: btcStats.trend,
      fng: fng ? fng.value : NaN
    })
  };
}

/* Маленькому виджету незачем тянуть историю обоих активов, а виджету
 * на экране блокировки — вообще никакой: лишний запрос это лишняя
 * секунда и лишний шанс упереться в лимит. */
function needsFor(family, asset) {
  const accessory = String(family).indexOf('accessory') === 0;
  if (accessory) {
    return { btcHistory: family === 'accessoryRectangular', usdHistory: false, fng: false };
  }
  if (family === 'small') {
    return { btcHistory: asset !== 'usd', usdHistory: asset === 'usd', fng: asset !== 'usd' };
  }
  return { btcHistory: true, usdHistory: true, fng: true };
}

async function loadModel(need) {
  const cache = readCache();
  const jobs = [];
  const start = (key, promise) =>
    jobs.push(promise.then((data) => ({ key, data }), (error) => ({ key, error })));

  start('cbr', fetchCbr());
  start('spot', fetchSpot());
  if (need.btcHistory) start('btcHistory', fetchBtcHistory());
  if (need.usdHistory) start('usdHistory', fetchUsdHistory());
  if (need.fng) start('fng', fetchFng());

  const results = await Promise.all(jobs);
  const fresh = {};
  const failed = [];
  for (const result of results) {
    if (result.error) failed.push(result.key);
    else fresh[result.key] = result.data;
  }

  const parts = mergeParts(fresh, cache.parts || {});
  const model = buildModel(parts, failed);
  const state = await maybeNotify(model, cache.alerts || {});
  writeCache({ parts, alerts: state });
  return model;
}

/* ─────────────────────────── Тревоги ───────────────────────────
 *
 * iOS не обещает выполнить код виджета в заданную минуту, поэтому это
 * не сигнализация, а напоминание: срабатывает, когда скрипт запускается
 * руками или автоматизацией «Команд». Повтор одной и той же тревоги
 * придержан выдержкой — иначе каждое обновление приносило бы push.
 */

function alertChecks(model) {
  const a = SETTINGS.alerts;
  const btc = model.btc.usd;
  const usd = isNum(model.usd.market) ? model.usd.market : model.usd.official;
  const move = model.btc.change24h;
  return [
    {
      key: 'btcAbove',
      hit: a.btcAbove > 0 && isNum(btc) && btc >= a.btcAbove,
      title: 'Биткойн выше порога',
      body: () => `$${fmt(btc, 0)} — выше ${fmt(a.btcAbove, 0)}`
    },
    {
      key: 'btcBelow',
      hit: a.btcBelow > 0 && isNum(btc) && btc <= a.btcBelow,
      title: 'Биткойн ниже порога',
      body: () => `$${fmt(btc, 0)} — ниже ${fmt(a.btcBelow, 0)}`
    },
    {
      key: 'usdAbove',
      hit: a.usdRubAbove > 0 && isNum(usd) && usd >= a.usdRubAbove,
      title: 'Доллар выше порога',
      body: () => `${fmt(usd, 2)} ₽ — выше ${fmt(a.usdRubAbove, 2)}`
    },
    {
      key: 'usdBelow',
      hit: a.usdRubBelow > 0 && isNum(usd) && usd <= a.usdRubBelow,
      title: 'Доллар ниже порога',
      body: () => `${fmt(usd, 2)} ₽ — ниже ${fmt(a.usdRubBelow, 2)}`
    },
    {
      key: 'move',
      hit: a.move24hPct > 0 && isNum(move) && Math.abs(move) >= a.move24hPct,
      title: move > 0 ? 'Биткойн резко вверх' : 'Биткойн резко вниз',
      body: () => `${fmtSigned(move, 1)} за сутки, сейчас $${fmt(btc, 0)}`
    }
  ];
}

async function maybeNotify(model, state) {
  const fired = Object.assign({}, state.firedAt);
  if (!SETTINGS.alerts.enabled) return { firedAt: fired };
  const now = Date.now();
  const cooldown = SETTINGS.alerts.cooldownMinutes * 60000;
  for (const check of alertChecks(model)) {
    if (!check.hit) {
      // Условие отпустило — следующий раз можно сообщить сразу.
      delete fired[check.key];
      continue;
    }
    if (fired[check.key] && now - fired[check.key] < cooldown) continue;
    try {
      const notification = new Notification();
      notification.title = check.title;
      notification.body = check.body();
      notification.sound = 'default';
      await notification.schedule();
      fired[check.key] = now;
    } catch (error) {
      // Из фонового обновления уведомление может не уйти. Это не ошибка
      // виджета: он всё равно покажет те же числа на экране.
    }
  }
  return { firedAt: fired };
}

/* ─────────────────────────── Оформление ───────────────────────────
 *
 * Цвета заданы парами «светлая/тёмная тема»: iOS перерисовывает виджет
 * при смене оформления, и подбирать оттенки под что-то одно значит
 * получить нечитаемый виджет во втором.
 */

let themeCache = null;

function theme() {
  if (themeCache) return themeCache;
  const pair = (light, dark) => Color.dynamic(new Color(light), new Color(dark));
  themeCache = {
    bgTop: pair('#FFFFFF', '#1A1D24'),
    bgBottom: pair('#ECEEF3', '#0A0B0F'),
    text: pair('#14161A', '#F3F5F9'),
    dim: pair('#646C7A', '#8F97A5'),
    faint: pair('#9AA1AD', '#5E6672'),
    line: Color.dynamic(new Color('#000000', 0.08), new Color('#FFFFFF', 0.12)),
    track: Color.dynamic(new Color('#000000', 0.07), new Color('#FFFFFF', 0.1)),
    up: pair('#0E9F6E', '#30D158'),
    down: pair('#D14343', '#FF453A'),
    flat: pair('#8A8F98', '#9AA1AC'),
    btc: new Color('#F7931A'),
    btcFill: new Color('#F7931A', 0.16),
    rub: pair('#0A6BE1', '#0A84FF'),
    rubFill: Color.dynamic(new Color('#0A6BE1', 0.14), new Color('#0A84FF', 0.18))
  };
  return themeCache;
}

function toneColor(value) {
  const t = theme();
  if (value === 'up' || (isNum(value) && value > 0.005)) return t.up;
  if (value === 'down' || (isNum(value) && value < -0.005)) return t.down;
  return t.flat;
}

function clamp(value, min, max) {
  if (!isNum(value)) return min;
  return Math.min(max, Math.max(min, value));
}

/* ─────────────────────────── Графика ─────────────────────────── */

function sparkline(values, options) {
  const width = options.width;
  const height = options.height;
  const points = downsample(values, clamp(Math.round(width / 2.5), 8, 64));
  if (points.length < 2) return null;

  let min = points[0];
  let max = points[0];
  for (const v of points) {
    if (v < min) min = v;
    if (v > max) max = v;
  }
  // Плоский ряд без этого превратился бы в деление на ноль.
  if (max - min < 1e-9) {
    max += 1;
    min -= 1;
  }

  const pad = 3;
  const dc = new DrawContext();
  dc.size = new Size(width, height);
  dc.opaque = false;
  dc.respectScreenScale = true;

  const at = (i, v) =>
    new Point(
      (i / (points.length - 1)) * (width - 2) + 1,
      height - pad - ((v - min) / (max - min)) * (height - pad * 2)
    );
  const line = points.map((v, i) => at(i, v));

  const area = new Path();
  area.move(new Point(line[0].x, height));
  area.addLines(line);
  area.addLine(new Point(line[line.length - 1].x, height));
  area.closeSubpath();
  dc.setFillColor(options.fill);
  dc.addPath(area);
  dc.fillPath();

  const stroke = new Path();
  stroke.move(line[0]);
  stroke.addLines(line.slice(1));
  dc.setStrokeColor(options.color);
  dc.setLineWidth(options.lineWidth || 2);
  dc.addPath(stroke);
  dc.strokePath();

  // Точка «сейчас»: без неё непонятно, с какого края свежие данные.
  const last = line[line.length - 1];
  dc.setFillColor(options.color);
  dc.fillEllipse(new Rect(last.x - 2.5, last.y - 2.5, 5, 5));

  return dc.getImage();
}

function barImage(ratio, options) {
  const width = options.width;
  const height = options.height;
  const dc = new DrawContext();
  dc.size = new Size(width, height);
  dc.opaque = false;
  dc.respectScreenScale = true;
  const radius = height / 2;

  const track = new Path();
  track.addRoundedRect(new Rect(0, 0, width, height), radius, radius);
  dc.setFillColor(options.track);
  dc.addPath(track);
  dc.fillPath();

  if (isNum(ratio)) {
    const filled = Math.max(height, width * clamp(ratio, 0, 1));
    const value = new Path();
    value.addRoundedRect(new Rect(0, 0, filled, height), radius, radius);
    dc.setFillColor(options.fill);
    dc.addPath(value);
    dc.fillPath();
  }
  return dc.getImage();
}

/* Где цена внутри месячного диапазона: полоса от минимума до максимума
 * и метка на ней. Одно число «позиция 0,78» ничего не говорит, а
 * картинка — говорит. */
function markerBar(ratio, options) {
  const width = options.width;
  const height = options.height;
  const dc = new DrawContext();
  dc.size = new Size(width, height);
  dc.opaque = false;
  dc.respectScreenScale = true;

  const radius = height / 2;
  const track = new Path();
  track.addRoundedRect(new Rect(0, (height - 4) / 2, width, 4), 2, 2);
  dc.setFillColor(options.track);
  dc.addPath(track);
  dc.fillPath();

  if (isNum(ratio)) {
    const x = clamp(ratio, 0, 1) * (width - height) + height / 2;
    dc.setFillColor(options.fill);
    dc.fillEllipse(new Rect(x - radius, 0, height, height));
  }
  return dc.getImage();
}

/* Шкала страха и жадности: пять зон и метка. Цвета зон — общепринятые
 * для этого индекса, от красного страха к зелёной жадности. */
function fngBar(value, options) {
  const width = options.width;
  const height = options.height;
  const zones = ['#E5484D', '#F0883E', '#C8B62E', '#8FCF6B', '#2FB673'];
  const dc = new DrawContext();
  dc.size = new Size(width, height);
  dc.opaque = false;
  dc.respectScreenScale = true;

  const step = width / zones.length;
  zones.forEach((hex, i) => {
    dc.setFillColor(new Color(hex, 0.85));
    dc.fillRect(new Rect(i * step, 0, step + 0.5, height));
  });

  if (isNum(value)) {
    const x = clamp(value / 100, 0, 1) * width;
    dc.setFillColor(new Color('#FFFFFF', 0.95));
    dc.fillRect(new Rect(clamp(x - 1.5, 0, width - 3), -1, 3, height + 2));
  }
  return dc.getImage();
}

/* ─────────────────────── Размеры и мелкие детали ───────────────────────
 *
 * Картинка графика рисуется в точках и сама не тянется, поэтому ширину
 * приходится знать заранее. Apple задаёт размеры виджетов таблицей от
 * ширины экрана; здесь её ходовая часть, а незнакомый экран получает
 * размеры «как у 6.1 дюйма», обрезанные по фактической ширине.
 */

const WIDGET_SIZES = {
  320: { small: 141, medium: 291 },
  360: { small: 155, medium: 329 },
  375: { small: 148, medium: 321 },
  390: { small: 158, medium: 338 },
  393: { small: 158, medium: 338 },
  402: { small: 162, medium: 348 },
  412: { small: 169, medium: 360 },
  414: { small: 169, medium: 360 },
  428: { small: 170, medium: 364 },
  430: { small: 170, medium: 364 },
  440: { small: 174, medium: 372 }
};

function widgetWidth(family) {
  let screen = 393;
  try {
    screen = Math.round(Math.min(Device.screenSize().width, Device.screenSize().height));
  } catch (error) {
    // Размер экрана недоступен — берём средний телефон.
  }
  const row = WIDGET_SIZES[screen] || WIDGET_SIZES[393];
  const width = family === 'small' ? row.small : row.medium;
  return Math.min(width, screen - 20);
}

function addText(stack, value, options) {
  const opts = options || {};
  const text = stack.addText(String(value));
  text.font = opts.font || Font.systemFont(12);
  text.textColor = opts.color || theme().text;
  text.lineLimit = opts.lineLimit || 1;
  if (opts.scale) text.minimumScaleFactor = opts.scale;
  if (opts.center) text.centerAlignText();
  if (opts.right) text.rightAlignText();
  return text;
}

function background(widget) {
  const t = theme();
  const gradient = new LinearGradient();
  gradient.colors = [t.bgTop, t.bgBottom];
  gradient.locations = [0, 1];
  gradient.startPoint = new Point(0, 0);
  gradient.endPoint = new Point(0.6, 1);
  widget.backgroundGradient = gradient;
}

function divider(container, width) {
  const line = container.addStack();
  line.size = new Size(width || 0, 1);
  line.backgroundColor = theme().line;
  return line;
}

/* Единый способ показать актив: подпись, значок, цена, изменение, график.
 * Ниже разные раскладки собираются из этого, а не переписывают заново. */
function assetSpec(model, kind) {
  const t = theme();
  if (kind === 'btc') {
    const btc = model.btc;
    return {
      kind: 'btc',
      title: 'БИТКОЙН',
      badge: '₿',
      digits: 0,
      color: t.btc,
      fill: t.btcFill,
      price: isNum(btc.usd) ? '$' + fmt(btc.usd, btc.usd >= 1000 ? 0 : 2) : '—',
      compact: isNum(btc.usd) ? '$' + fmtCompact(btc.usd) : '—',
      aside: isNum(btc.rub) ? fmt(btc.rub, 0) + ' ₽' : '',
      asideShort: isNum(btc.rub)
        ? btc.rub >= 1e6
          ? fmt(btc.rub / 1e6, 2) + ' млн ₽'
          : fmt(btc.rub, 0) + ' ₽'
        : '',
      change: isNum(btc.change24h) ? btc.change24h : btc.stats.d1,
      changeCaption: 'за сутки',
      spark: btc.spark,
      stats: btc.stats
    };
  }
  const usd = model.usd;
  const headline = isNum(usd.official) ? usd.official : usd.market;
  return {
    kind: 'usd',
    title: 'ДОЛЛАР',
    badge: '$',
    digits: 2,
    color: t.rub,
    fill: t.rubFill,
    price: isNum(headline) ? fmt(headline, 2) + ' ₽' : '—',
    compact: isNum(headline) ? fmt(headline, 2) + ' ₽' : '—',
    aside: isNum(usd.market) ? 'рынок ' + fmt(usd.market, 2) + ' ₽' : '',
    asideShort: isNum(usd.market) ? 'рынок ' + fmt(usd.market, 2) : '',
    change: isNum(usd.officialChange) ? usd.officialChange : usd.stats.d1,
    changeCaption: isNum(usd.officialChange) ? 'ЦБ ко вчера' : 'за сутки',
    spark: usd.spark,
    stats: usd.stats
  };
}

function headerRow(container, spec, rightText) {
  const row = container.addStack();
  row.centerAlignContent();
  addText(row, spec.badge, { font: Font.boldRoundedSystemFont(11), color: spec.color });
  row.addSpacer(4);
  addText(row, spec.title, { font: Font.semiboldSystemFont(10), color: theme().dim });
  row.addSpacer();
  if (rightText) addText(row, rightText, { font: Font.systemFont(9), color: theme().faint });
  return row;
}

function changeRow(container, value, caption, size) {
  const row = container.addStack();
  row.centerAlignContent();
  const color = toneColor(value);
  addText(row, arrow(value) + NBSP + fmtSigned(value, isNum(value) && Math.abs(value) < 1 ? 2 : 1), {
    font: Font.semiboldRoundedSystemFont(size || 12),
    color
  });
  if (caption) {
    row.addSpacer(5);
    addText(row, caption, { font: Font.systemFont((size || 12) - 2), color: theme().faint });
  }
  return row;
}

function statsLine(stats, extra) {
  const parts = [];
  if (isNum(stats.rsi)) parts.push('RSI ' + fmt(stats.rsi, 0));
  if (stats.trend && stats.trend.label !== '—') parts.push(stats.trend.label);
  if (extra) parts.push(extra);
  else if (isNum(stats.d30)) parts.push('30д ' + fmtSigned(stats.d30, 1));
  return parts.length ? parts.join(' · ') : 'данных для аналитики мало';
}

/* ─────────────────────────── Раскладки ─────────────────────────── */

function statusText(model) {
  if (!model.at) return 'нет данных';
  return model.live ? clock(model.at) : ago(model.at);
}

function rsiColor(value) {
  const t = theme();
  if (!isNum(value)) return t.dim;
  if (value >= 70) return t.down;
  if (value <= 30) return t.up;
  return t.text;
}

function metric(parent, caption, value, color) {
  const cell = parent.addStack();
  cell.layoutVertically();
  addText(cell, caption, { font: Font.systemFont(8), color: theme().faint });
  addText(cell, value, { font: Font.semiboldRoundedSystemFont(12), color: color || theme().text });
  return cell;
}

function sparkImage(container, spec, width, height) {
  const image = sparkline(spec.spark, {
    width,
    height,
    color: spec.color,
    fill: spec.fill
  });
  if (!image) {
    // График не из чего построить — место под него не пустует зря.
    addText(container, 'график появится, когда придёт история', {
      font: Font.systemFont(9),
      color: theme().faint
    });
    return null;
  }
  const widgetImage = container.addImage(image);
  widgetImage.imageSize = new Size(width, height);
  return widgetImage;
}

function rangeRow(container, spec, width) {
  const range = spec.stats.range;
  if (!isNum(range.min) || !isNum(range.max)) return;
  const row = container.addStack();
  row.centerAlignContent();
  const caption = { font: Font.systemFont(9), color: theme().faint };
  addText(row, '30д', caption);
  row.addSpacer(5);
  addText(row, fmt(range.min, spec.digits), caption);
  row.addSpacer(5);
  const barWidth = Math.max(60, width - 150);
  const image = markerBar(range.pos, {
    width: barWidth,
    height: 10,
    track: theme().track,
    fill: spec.color
  });
  const drawn = row.addImage(image);
  drawn.imageSize = new Size(barWidth, 10);
  row.addSpacer(5);
  addText(row, fmt(range.max, spec.digits), caption);
  row.addSpacer();
}

/* ── Маленький виджет ── */

function buildSmall(model) {
  const widget = new ListWidget();
  background(widget);
  widget.setPadding(13, 14, 12, 14);
  const width = widgetWidth('small') - 28;

  if (SETTINGS.asset === 'both') {
    const specs = [assetSpec(model, 'usd'), assetSpec(model, 'btc')];
    specs.forEach((spec, index) => {
      if (index) {
        widget.addSpacer(6);
        divider(widget, width);
        widget.addSpacer(6);
      }
      headerRow(widget, spec, index === 0 ? statusText(model) : '');
      const row = widget.addStack();
      row.centerAlignContent();
      addText(row, spec.compact, { font: Font.boldRoundedSystemFont(17), scale: 0.5 });
      row.addSpacer();
      addText(row, arrow(spec.change) + fmtSigned(spec.change, 1), {
        font: Font.semiboldRoundedSystemFont(11),
        color: toneColor(spec.change)
      });
      widget.addSpacer(3);
      sparkImage(widget, spec, width, 20);
    });
    return widget;
  }

  const spec = assetSpec(model, SETTINGS.asset === 'usd' ? 'usd' : 'btc');
  headerRow(widget, spec, statusText(model));
  widget.addSpacer(4);
  addText(widget, spec.price, { font: Font.boldRoundedSystemFont(24), scale: 0.4 });
  changeRow(widget, spec.change, spec.changeCaption, 12);
  widget.addSpacer(6);
  sparkImage(widget, spec, width, 38);
  widget.addSpacer(5);
  addText(widget, statsLine(spec.stats), {
    font: Font.systemFont(9),
    color: theme().dim,
    scale: 0.6
  });
  return widget;
}

/* ── Средний виджет: два актива рядом ── */

function buildMedium(model) {
  const widget = new ListWidget();
  background(widget);
  widget.setPadding(12, 14, 12, 14);
  const total = widgetWidth('medium') - 28;
  const column = Math.floor((total - 13) / 2);

  const top = widget.addStack();
  top.centerAlignContent();
  addText(top, 'КУРСЫ И АНАЛИТИКА', { font: Font.semiboldSystemFont(9), color: theme().faint });
  top.addSpacer();
  addText(top, statusText(model), { font: Font.systemFont(9), color: theme().faint });
  widget.addSpacer(7);

  const body = widget.addStack();
  body.layoutHorizontally();
  ['usd', 'btc'].forEach((kind, index) => {
    if (index) {
      body.addSpacer(6);
      const rule = body.addStack();
      rule.size = new Size(1, 92);
      rule.backgroundColor = theme().line;
      body.addSpacer(6);
    }
    const spec = assetSpec(model, kind);
    const cell = body.addStack();
    cell.layoutVertically();
    cell.size = new Size(column, 0);
    headerRow(cell, spec, '');
    cell.addSpacer(2);
    addText(cell, spec.price, { font: Font.boldRoundedSystemFont(19), scale: 0.4 });
    changeRow(cell, spec.change, spec.changeCaption, 11);
    cell.addSpacer(5);
    sparkImage(cell, spec, column, 26);
    cell.addSpacer(4);
    addText(cell, statsLine(spec.stats, spec.asideShort), {
      font: Font.systemFont(9),
      color: theme().dim,
      scale: 0.6
    });
  });

  widget.addSpacer(7);
  divider(widget, total);
  widget.addSpacer(6);

  const foot = widget.addStack();
  foot.centerAlignContent();
  if (model.fng) {
    const bar = foot.addImage(fngBar(model.fng.value, { width: 42, height: 7 }));
    bar.imageSize = new Size(42, 7);
    bar.cornerRadius = 3;
    foot.addSpacer(5);
    addText(foot, `${fmt(model.fng.value, 0)} ${model.fng.label}`, {
      font: Font.systemFont(9),
      color: theme().dim
    });
  }
  foot.addSpacer();
  addText(foot, '₿ ' + model.verdict.label, {
    font: Font.semiboldSystemFont(9),
    color: toneColor(model.verdict.tone)
  });
  return widget;
}

/* ── Большой виджет: всё сразу ── */

function assetSection(container, spec, width) {
  const stats = spec.stats;
  headerRow(container, spec, spec.aside);
  container.addSpacer(2);

  const price = container.addStack();
  price.centerAlignContent();
  addText(price, spec.price, { font: Font.boldRoundedSystemFont(26), scale: 0.4 });
  price.addSpacer(8);
  changeRow(price, spec.change, spec.changeCaption, 12);
  price.addSpacer();

  container.addSpacer(6);
  sparkImage(container, spec, width, 36);
  container.addSpacer(7);

  const row = container.addStack();
  row.layoutHorizontally();
  metric(row, 'RSI 14', isNum(stats.rsi) ? fmt(stats.rsi, 0) : '—', rsiColor(stats.rsi));
  row.addSpacer();
  metric(row, 'тренд', stats.trend.label, toneColor(stats.trend.dir));
  row.addSpacer();
  metric(
    row,
    'волат., ' + stats.volatilityLabel,
    isNum(stats.volatility) ? fmt(stats.volatility, 0) + '%' : '—'
  );
  row.addSpacer();
  metric(row, '7 дней', fmtSigned(stats.d7, 1), toneColor(stats.d7));
  row.addSpacer();
  metric(row, '30 дней', fmtSigned(stats.d30, 1), toneColor(stats.d30));

  container.addSpacer(7);
  rangeRow(container, spec, width);
}

function sourcesLine(model) {
  const bits = [];
  if (model.at) bits.push(model.live ? 'обновлено в ' + clock(model.at) : 'обновлено ' + ago(model.at));
  if (model.usd.officialDate) bits.push('ЦБ на ' + dmy(model.usd.officialDate));
  if (model.btc.source) bits.push(model.btc.source);
  if (model.failed.length) bits.push('часть данных из кэша');
  return bits.join(' · ');
}

function buildLarge(model) {
  const widget = new ListWidget();
  background(widget);
  widget.setPadding(16, 16, 13, 16);
  const width = widgetWidth('medium') - 32;

  const top = widget.addStack();
  top.centerAlignContent();
  addText(top, 'КУРСЫ И АНАЛИТИКА', { font: Font.semiboldSystemFont(10), color: theme().faint });
  top.addSpacer();
  addText(top, statusText(model), { font: Font.systemFont(10), color: theme().faint });
  widget.addSpacer(9);

  assetSection(widget, assetSpec(model, 'usd'), width);
  widget.addSpacer(9);
  divider(widget, width);
  widget.addSpacer(9);
  assetSection(widget, assetSpec(model, 'btc'), width);
  widget.addSpacer();

  const foot = widget.addStack();
  foot.centerAlignContent();
  if (model.fng) {
    const bar = foot.addImage(fngBar(model.fng.value, { width: 54, height: 8 }));
    bar.imageSize = new Size(54, 8);
    bar.cornerRadius = 4;
    foot.addSpacer(6);
    addText(foot, `страх и жадность ${fmt(model.fng.value, 0)}, ${model.fng.label}`, {
      font: Font.systemFont(9),
      color: theme().dim
    });
  }
  foot.addSpacer();
  addText(foot, '₿ ' + model.verdict.label, {
    font: Font.semiboldSystemFont(10),
    color: toneColor(model.verdict.tone)
  });

  widget.addSpacer(5);
  addText(widget, sourcesLine(model), { font: Font.systemFont(8), color: theme().faint, scale: 0.7 });
  return widget;
}

/* ── Экран блокировки ──
 *
 * Здесь iOS сама красит содержимое в цвет обоев, поэтому свои цвета не
 * назначаются: любой заданный оттенок стал бы грязным пятном.
 */

function accessoryBackground(widget) {
  try {
    widget.addAccessoryWidgetBackground = true;
  } catch (error) {
    // Старая версия Scriptable — обойдёмся без подложки.
  }
}

function buildAccessoryInline(model) {
  const widget = new ListWidget();
  const usd = isNum(model.usd.official) ? model.usd.official : model.usd.market;
  const btc = model.btc.usd;
  widget.addText(
    `$${fmt(usd, 2)} ₽ · ₿${fmtCompact(btc)} ${fmtSigned(model.btc.change24h, 1)}`
  );
  return widget;
}

function buildAccessoryCircular(model) {
  const widget = new ListWidget();
  accessoryBackground(widget);
  widget.setPadding(2, 2, 2, 2);
  const stack = widget.addStack();
  stack.layoutVertically();
  stack.centerAlignContent();
  const line = (value, size, weight) => {
    const text = stack.addText(value);
    text.font = weight ? Font.boldRoundedSystemFont(size) : Font.systemFont(size);
    text.centerAlignText();
    text.minimumScaleFactor = 0.5;
    text.lineLimit = 1;
  };
  line('₿', 9, false);
  line(fmtCompact(model.btc.usd), 14, true);
  line(arrow(model.btc.change24h) + fmtSigned(model.btc.change24h, 1, ''), 9, false);
  return widget;
}

function buildAccessoryRectangular(model) {
  const widget = new ListWidget();
  accessoryBackground(widget);
  widget.setPadding(2, 4, 2, 4);
  const usd = isNum(model.usd.official) ? model.usd.official : model.usd.market;

  const first = widget.addStack();
  first.centerAlignContent();
  const btcText = first.addText(`₿ $${fmt(model.btc.usd, 0)}`);
  btcText.font = Font.semiboldRoundedSystemFont(13);
  first.addSpacer(5);
  const btcDelta = first.addText(arrow(model.btc.change24h) + fmtSigned(model.btc.change24h, 1));
  btcDelta.font = Font.systemFont(11);
  first.addSpacer();

  const second = widget.addStack();
  second.centerAlignContent();
  const usdText = second.addText(`$ ${fmt(usd, 2)} ₽`);
  usdText.font = Font.semiboldRoundedSystemFont(13);
  second.addSpacer(5);
  const usdDelta = second.addText(arrow(model.usd.officialChange) + fmtSigned(model.usd.officialChange, 1));
  usdDelta.font = Font.systemFont(11);
  second.addSpacer();

  const spark = sparkline(model.btc.spark, {
    width: 140,
    height: 14,
    color: Color.white(),
    fill: new Color('#FFFFFF', 0.25),
    lineWidth: 1.5
  });
  if (spark) {
    const image = widget.addImage(spark);
    image.imageSize = new Size(140, 14);
  }
  return widget;
}

function buildWidget(model, family) {
  let widget;
  if (family === 'accessoryInline') widget = buildAccessoryInline(model);
  else if (family === 'accessoryCircular') widget = buildAccessoryCircular(model);
  else if (family === 'accessoryRectangular') widget = buildAccessoryRectangular(model);
  else if (family === 'small') widget = buildSmall(model);
  else if (family === 'large' || family === 'extraLarge') widget = buildLarge(model);
  else widget = buildMedium(model);

  widget.refreshAfterDate = new Date(Date.now() + SETTINGS.refreshMinutes * 60000);
  try {
    // Нажатие открывает подробный разбор в самом Scriptable.
    widget.url = 'scriptable:///run?scriptName=' + encodeURIComponent(Script.name());
  } catch (error) {
    // Имя скрипта недоступно — обойдёмся без перехода по нажатию.
  }
  return widget;
}

function buildFailure(error) {
  const widget = new ListWidget();
  background(widget);
  widget.setPadding(16, 16, 16, 16);
  addText(widget, 'Курсы недоступны', { font: Font.boldSystemFont(15) });
  widget.addSpacer(6);
  const text = addText(widget, String(error && error.message ? error.message : error), {
    font: Font.systemFont(11),
    color: theme().dim
  });
  text.lineLimit = 4;
  widget.addSpacer(6);
  addText(widget, 'Виджет попробует снова при следующем обновлении', {
    font: Font.systemFont(9),
    color: theme().faint
  });
  widget.refreshAfterDate = new Date(Date.now() + 5 * 60000);
  return widget;
}

/* ─────────────────── Подробный разбор в приложении ───────────────────
 *
 * То, что не влезло в виджет: точные числа, вчерашние значения, объёмы,
 * источники. Открывается нажатием на виджет.
 */

function tableSection(table, title) {
  const row = new UITableRow();
  row.isHeader = true;
  const cell = row.addText(title);
  cell.titleFont = Font.semiboldSystemFont(15);
  table.addRow(row);
}

function tableLine(table, label, value, hint) {
  const row = new UITableRow();
  row.height = hint ? 54 : 44;
  const left = row.addText(label, hint || '');
  left.titleFont = Font.systemFont(14);
  left.subtitleFont = Font.systemFont(11);
  left.subtitleColor = Color.gray();
  left.widthWeight = 58;
  const right = row.addText(value);
  right.titleFont = Font.semiboldRoundedSystemFont(15);
  right.widthWeight = 42;
  right.rightAligned();
  table.addRow(row);
}

function describeTrend(stats) {
  if (!stats.trend || !isNum(stats.trend.gap)) return '';
  return `средняя за 7 дней ${stats.trend.gap >= 0 ? 'выше' : 'ниже'} средней за 30 на ${fmt(
    Math.abs(stats.trend.gap),
    1
  )}%`;
}

function describeRange(stats, digits, unit) {
  const range = stats.range;
  if (!isNum(range.min) || !isNum(range.max)) return '';
  return `${fmt(range.min, digits)} — ${fmt(range.max, digits)} ${unit}`;
}

async function showDetail(model, widget) {
  const table = new UITable();
  table.showSeparators = true;

  const head = new UITableRow();
  head.height = 62;
  head.dismissOnSelect = false;
  const headCell = head.addText('Курсы и аналитика', 'нажмите, чтобы посмотреть сам виджет');
  headCell.titleFont = Font.boldSystemFont(22);
  headCell.subtitleFont = Font.systemFont(12);
  head.onSelect = () => {
    widget.presentLarge();
  };
  table.addRow(head);

  const usd = model.usd;
  const usdStats = usd.stats;
  tableSection(table, 'Доллар');
  tableLine(
    table,
    'Курс ЦБ',
    isNum(usd.official) ? fmt(usd.official, 4) + ' ₽' : '—',
    [usd.officialDate ? 'на ' + dmy(usd.officialDate) : '', isNum(usd.officialPrev) ? 'до этого ' + fmt(usd.officialPrev, 4) : '']
      .filter(Boolean)
      .join(', ')
  );
  tableLine(table, 'Изменение ЦБ', fmtSigned(usd.officialChange, 2), 'к предыдущему официальному курсу');
  tableLine(table, 'Рынок', isNum(usd.market) ? fmt(usd.market, 2) + ' ₽' : '—', 'цена USDT на крипторынке');
  tableLine(table, 'Отрыв рынка от ЦБ', fmtSigned(usd.spread, 2), 'насколько рынок дороже официального курса');
  tableLine(table, 'За неделю', fmtSigned(usdStats.d7, 2));
  tableLine(table, 'За месяц', fmtSigned(usdStats.d30, 2));
  tableLine(table, 'RSI (14 дней)', isNum(usdStats.rsi) ? fmt(usdStats.rsi, 1) : '—', 'выше 70 — перекуплен, ниже 30 — перепродан');
  tableLine(table, 'Тренд', usdStats.trend.label, describeTrend(usdStats));
  tableLine(
    table,
    'Волатильность',
    isNum(usdStats.volatility) ? fmt(usdStats.volatility, 1) + '%' : '—',
    'годовая, по дневным движениям: ' + usdStats.volatilityLabel
  );
  tableLine(table, 'Диапазон 30 дней', describeRange(usdStats, 2, '₽') || '—', isNum(usdStats.range.pos) ? `сейчас на ${fmt(usdStats.range.pos * 100, 0)}% от низа диапазона` : '');
  if (isNum(usd.eur)) tableLine(table, 'Евро ЦБ', fmt(usd.eur, 4) + ' ₽');
  if (isNum(usd.cny)) tableLine(table, 'Юань ЦБ', fmt(usd.cny, 4) + ' ₽');

  const btc = model.btc;
  const btcStats = btc.stats;
  tableSection(table, 'Биткойн');
  tableLine(table, 'Цена', isNum(btc.usd) ? '$' + fmt(btc.usd, 2) : '—', isNum(btc.rub) ? '≈ ' + fmt(btc.rub, 0) + ' ₽' : '');
  tableLine(table, 'За сутки', fmtSigned(btc.change24h, 2));
  tableLine(table, 'За неделю', fmtSigned(btcStats.d7, 2));
  tableLine(table, 'За месяц', fmtSigned(btcStats.d30, 2));
  tableLine(table, 'RSI (14 дней)', isNum(btcStats.rsi) ? fmt(btcStats.rsi, 1) : '—', 'выше 70 — перекуплен, ниже 30 — перепродан');
  tableLine(table, 'Тренд', btcStats.trend.label, describeTrend(btcStats));
  tableLine(
    table,
    'Волатильность',
    isNum(btcStats.volatility) ? fmt(btcStats.volatility, 1) + '%' : '—',
    'годовая, по дневным движениям: ' + btcStats.volatilityLabel
  );
  tableLine(table, 'Диапазон 30 дней', describeRange(btcStats, 0, '$') || '—', isNum(btcStats.range.pos) ? `сейчас на ${fmt(btcStats.range.pos * 100, 0)}% от низа диапазона` : '');
  if (isNum(btc.volume24h)) tableLine(table, 'Объём за сутки', '$' + fmtCompact(btc.volume24h));
  if (isNum(btc.cap)) tableLine(table, 'Капитализация', '$' + fmtCompact(btc.cap));

  tableSection(table, 'Настроение и вывод');
  if (model.fng) {
    tableLine(
      table,
      'Страх и жадность',
      `${fmt(model.fng.value, 0)} · ${model.fng.label}`,
      isNum(model.fng.prev) ? `вчера ${fmt(model.fng.prev, 0)}` : ''
    );
  }
  tableLine(
    table,
    'Вывод по биткойну',
    model.verdict.label,
    'описание состояния рынка, а не инвестиционная рекомендация'
  );

  tableSection(table, 'Данные');
  tableLine(table, 'Обновлено', model.at ? ago(model.at) : '—', model.at ? clock(model.at) : '');
  tableLine(table, 'Источники', 'ЦБ РФ · CoinGecko', 'запасные: Binance, open.er-api, alternative.me');
  if (model.failed.length) {
    tableLine(table, 'Не ответили', String(model.failed.length), model.failed.join(', ') + ' — показаны данные из кэша');
  }
  tableLine(table, 'Показывать в малом виджете', SETTINGS.asset, 'меняется параметром виджета: btc, usd, both');

  await table.present(false);
}

/* ─────────────────────── Параметр виджета ───────────────────────
 *
 * Один и тот же скрипт стоит на экране несколько раз в разных размерах,
 * поэтому настройка приходит параметром виджета, а не правкой файла:
 * «btc», «usd», «both» или «asset=btc;days=14;alerts=on».
 */

function applyParameter(raw) {
  if (typeof raw !== 'string') return;
  const text = raw.trim().toLowerCase();
  if (!text) return;

  const shortcuts = {
    btc: 'btc',
    биткойн: 'btc',
    биткоин: 'btc',
    usd: 'usd',
    доллар: 'usd',
    рубль: 'usd',
    both: 'both',
    оба: 'both',
    всё: 'both',
    все: 'both'
  };
  if (shortcuts[text]) {
    SETTINGS.asset = shortcuts[text];
    return;
  }

  for (const chunk of text.split(/[;,]/)) {
    const eq = chunk.indexOf('=');
    if (eq < 1) continue;
    const key = chunk.slice(0, eq).trim();
    const value = chunk.slice(eq + 1).trim();
    if (key === 'asset' && shortcuts[value]) SETTINGS.asset = shortcuts[value];
    if (key === 'days') {
      const days = Number(value);
      if (Number.isFinite(days) && days >= 7 && days <= 365) {
        SETTINGS.sparkDays = Math.min(days, SETTINGS.historyDays);
      }
    }
    if (key === 'refresh') {
      const minutes = Number(value);
      if (Number.isFinite(minutes) && minutes >= 5 && minutes <= 720) SETTINGS.refreshMinutes = minutes;
    }
    if (key === 'alerts') SETTINGS.alerts.enabled = value === 'on' || value === '1' || value === 'да';
  }
}

/* ─────────────────────────── Запуск ─────────────────────────── */

async function main() {
  applyParameter(typeof args === 'undefined' ? null : args.widgetParameter);
  const family = (typeof config !== 'undefined' && config.widgetFamily) || 'large';

  let model = null;
  let widget;
  try {
    model = await loadModel(needsFor(family, SETTINGS.asset));
    widget = buildWidget(model, family);
  } catch (error) {
    widget = buildFailure(error);
  }

  if (config.runsInWidget) Script.setWidget(widget);
  else if (model) await showDetail(model, widget);
  else await widget.presentLarge();

  Script.complete();
}

/* Тесты подключают файл как обычный модуль и проверяют арифметику;
 * в Scriptable этот экспорт никому не мешает. */
const INTERNALS = {
  SETTINGS,
  fmt,
  fmtSigned,
  fmtCompact,
  arrow,
  plural,
  ago,
  pctChange,
  mean,
  stdev,
  sma,
  rsi,
  annualVolatility,
  volatilityLabel,
  rangeInfo,
  trendOf,
  resampleDaily,
  downsample,
  analyse,
  verdictFor,
  fngLabel,
  spreadPct,
  withLive,
  newestAt,
  mergeParts,
  buildModel,
  needsFor,
  alertChecks,
  applyParameter,
  summariseHistory,
  pointsFromPairs,
  widgetWidth,
  assetSpec,
  statsLine,
  statusText,
  sourcesLine,
  sparkline,
  buildWidget,
  buildFailure
};

if (typeof module !== 'undefined' && module.exports) module.exports = INTERNALS;

if (IS_SCRIPTABLE) {
  (async () => {
    await main();
  })();
}
