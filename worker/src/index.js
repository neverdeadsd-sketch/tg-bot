/* Оплата подписки HollVPN на Cloudflare Workers.
 *
 * Тот же чекаут, что и серверный, но без сервера: сайт лежит на статическом
 * хостинге, а этот Worker отвечает на hollvpn.ru/api/*. Логика работы
 * с деньгами общая — модули из checkout/src/ импортируются как есть, здесь
 * только слой запроса и хранилище на D1.
 *
 * Правило то же, вокруг которого всё построено: клиенту нельзя верить ни
 * в чём, что касается денег. Он присылает только число дней; сумму берём
 * из тарифов. Тело вебхука приходит из сети, поэтому статус платежа
 * перечитываем из API ЮKassa и верим только ему.
 */
import { load } from './config.js';
import { open, throttleKey } from './store.js';

import sharedConfig from '../../checkout/src/config.js';
import yookassa from '../../checkout/src/yookassa.js';
import net from '../../checkout/src/net.js';
import fulfil from '../../checkout/src/fulfil.js';

const { rubles } = sharedConfig;
const { deliver } = fulfil;

const TELEGRAM_RE = /^@?[A-Za-z0-9_]{5,32}$/;
const EMAIL_RE = /^[^@\s]+@[^@\s.]+\.[^@\s]{2,}$/;
const MAX_BODY = 64 * 1024;

const CHECKOUT_LIMIT = 10;
const CHECKOUT_WINDOW_MS = 60 * 60 * 1000;

function log(...args) {
  console.log(new Date().toISOString(), ...args);
}

/* Настоящий адрес клиента. CF-Connecting-IP проставляет сама Cloudflare
 * и затирает то, что прислал клиент, — подделать его нельзя. Поэтому
 * серверная возня с TRUST_PROXY здесь не нужна. */
function clientIp(request) {
  return request.headers.get('CF-Connecting-IP') || '';
}

function json(status, payload, headers) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'no-store',
      'X-Content-Type-Options': 'nosniff',
      ...(headers || {})
    }
  });
}

function corsHeaders(request, cfg) {
  const h = {
    'Access-Control-Allow-Methods': 'POST, GET, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type'
  };
  const origin = request.headers.get('Origin');
  if (origin && origin === cfg.publicUrl) {
    h['Access-Control-Allow-Origin'] = origin;
    h['Vary'] = 'Origin';
  }
  return h;
}

async function readJson(request) {
  const len = Number(request.headers.get('Content-Length') || 0);
  if (len > MAX_BODY) throw new Error('тело запроса слишком большое');
  const text = await request.text();
  if (text.length > MAX_BODY) throw new Error('тело запроса слишком большое');
  return text ? JSON.parse(text) : {};
}

/* ------------------------------------------------------------- маршруты -- */

async function handleCheckout(request, cfg, store, ip, cors) {
  const key = await throttleKey(ip, cfg.throttleSalt);
  if (!await store.allowCheckout(key, CHECKOUT_LIMIT, CHECKOUT_WINDOW_MS)) {
    return json(429, { error: 'Слишком много попыток. Попробуйте через час.' }, cors);
  }

  let body;
  try { body = await readJson(request); }
  catch (e) { return json(400, { error: 'Некорректный JSON' }, cors); }

  const term = cfg.terms[Number(body.days)];
  if (!term) return json(400, { error: 'Неизвестный срок подписки' }, cors);

  const telegram = String(body.telegram || '').trim();
  if (!TELEGRAM_RE.test(telegram)) {
    return json(400, {
      error: 'Укажите имя пользователя Telegram: латиница, цифры и подчёркивание, от 5 до 32 символов'
    }, cors);
  }

  const email = String(body.email || '').trim();
  if (email && !EMAIL_RE.test(email)) {
    return json(400, { error: 'Некорректный адрес электронной почты' }, cors);
  }
  if (cfg.sendReceipt && cfg.receiptEmailRequired && !email) {
    return json(400, { error: 'Для чека нужен адрес электронной почты' }, cors);
  }

  const order = await store.create({
    id: crypto.randomUUID(),
    days: term.days,
    kopecks: term.kopecks,
    telegram: telegram.startsWith('@') ? telegram : '@' + telegram,
    email: email || null
  });

  let payment;
  try {
    payment = await yookassa.createPayment(cfg, order);
  } catch (e) {
    log(`заказ ${order.id}: не удалось создать платёж — ${e.message}`);
    return json(502, {
      error: 'Платёжный сервис недоступен. Попробуйте позже или оплатите в боте.'
    }, cors);
  }

  const attached = await store.attachPayment(order.id, payment.id);
  if (attached !== true) {
    // Платёж создан, ссылку отдаём — иначе клиент потеряет оплату из-за
    // сбоя записи. Вебхук найдёт заказ по metadata.order_id.
    log(`ВНИМАНИЕ: заказ ${order.id}: платёж ${payment.id} создан, ` +
        `но не записан в базу — ${attached.message}`);
  }

  const url = payment.confirmation && payment.confirmation.confirmation_url;
  if (!url) {
    log(`заказ ${order.id}: ЮKassa не вернула ссылку подтверждения`);
    return json(502, { error: 'Платёжный сервис вернул неожиданный ответ' }, cors);
  }

  log(`заказ ${order.id}: платёж ${payment.id} создан на ${rubles(order.kopecks)} ₽`);
  return json(200, { order_id: order.id, confirmation_url: url }, cors);
}

/* Уведомление об оплате. Тело используем только чтобы узнать id платежа —
 * всё остальное берём из ответа API, который подписан нашим ключом. */
async function handleWebhook(request, cfg, store, ip, ctx, cors) {
  if (cfg.verifyWebhookIp && !net.isAllowed(ip)) {
    log(`вебхук с постороннего адреса ${ip} отклонён`);
    return json(403, { error: 'forbidden' }, cors);
  }

  let body;
  try { body = await readJson(request); }
  catch (e) { return json(400, { error: 'bad json' }, cors); }

  const paymentId = body && body.object && body.object.id;
  if (!paymentId || typeof paymentId !== 'string') {
    return json(400, { error: 'no payment id' }, cors);
  }

  let payment;
  try {
    payment = await yookassa.getPayment(cfg, paymentId);
  } catch (e) {
    log(`вебхук ${paymentId}: не удалось перечитать платёж — ${e.message}`);
    // 500 — ЮKassa повторит уведомление позже, и это правильно.
    return json(500, { error: 'cannot verify' }, cors);
  }

  const orderId = payment.metadata && payment.metadata.order_id;
  const order = orderId ? await store.byId(orderId) : await store.byPayment(paymentId);
  if (!order) {
    log(`вебхук ${paymentId}: заказ не найден, игнорируем`);
    return json(200, { ok: true }, cors);
  }

  // Сумма из API должна совпадать с той, на которую мы выставляли счёт.
  const expected = rubles(order.kopecks);
  const actual = payment.amount && payment.amount.value;
  if (actual !== expected || (payment.amount && payment.amount.currency) !== 'RUB') {
    log(`ВНИМАНИЕ: заказ ${order.id}: сумма не совпала (ждали ${expected}, пришло ${actual})`);
    return json(200, { ok: true }, cors);
  }

  if (payment.status === 'canceled') {
    await store.setStatus(order.id, 'canceled');
    return json(200, { ok: true }, cors);
  }
  if (payment.status !== 'succeeded' || !payment.paid) {
    return json(200, { ok: true }, cors);
  }
  if (order.fulfilled_at) {
    // Повторное уведомление о том же платеже — выдавать второй раз нельзя.
    return json(200, { ok: true, already: true }, cors);
  }

  await store.setStatus(order.id, 'succeeded');

  /* Отвечаем сразу, выдачу доводим после ответа: ЮKassa ждёт ответ,
   * а выдача может занять время. waitUntil держит Worker живым до конца
   * этой работы — без него она оборвалась бы вместе с ответом. */
  const fresh = await store.byId(order.id);
  ctx.waitUntil(
    deliver(cfg, store, fresh, log)
      .catch((e) => log(`заказ ${order.id}: выдача упала — ${e.message}`))
  );
  return json(200, { ok: true }, cors);
}

async function handleStatus(cfg, store, orderId, cors) {
  const order = await store.byId(orderId);
  if (!order) return json(404, { error: 'Заказ не найден' }, cors);
  return json(200, {
    order_id: order.id,
    status: order.status,
    days: order.days,
    amount: rubles(order.kopecks),
    telegram: order.telegram,
    delivered: Boolean(order.fulfilled_at),
    // auto — бот уже выдал; manual — заявка ушла, выдаёт человек.
    delivery_mode: cfg.deliveryMode,
    // Оплачено, но не выдано — фронтенд должен показать это честно.
    needs_attention: order.status === 'succeeded' && !order.fulfilled_at
  }, cors);
}

/* ---------------------------------------------------------------- точка -- */

export default {
  async fetch(request, env, ctx) {
    let cfg;
    try {
      cfg = load(env);
    } catch (e) {
      /* Настройка неполная — принимать деньги нельзя. Серверный вариант
       * в этом случае не поднимается; Worker поднять невозможно «наполовину»,
       * поэтому он честно отвечает, что оплата недоступна. */
      log('конфигурация не принята:', e.message);
      return json(503, { error: 'Оплата на сайте временно недоступна. Оплатите в боте.' });
    }

    const cors = corsHeaders(request, cfg);
    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors });

    if (!env.DB) {
      log('не привязана база D1');
      return json(503, { error: 'Оплата на сайте временно недоступна. Оплатите в боте.' }, cors);
    }

    const store = open(env.DB);
    const url = new URL(request.url);
    const ip = clientIp(request);

    try {
      if (request.method === 'GET' && url.pathname === '/api/health') {
        const stranded = await store.stranded();
        return json(stranded.length ? 503 : 200, {
          status: stranded.length ? 'attention' : 'ok',
          stranded_orders: stranded.length
        }, cors);
      }
      if (request.method === 'POST' && url.pathname === '/api/checkout') {
        return await handleCheckout(request, cfg, store, ip, cors);
      }
      if (request.method === 'POST' && url.pathname === '/api/yookassa/webhook') {
        return await handleWebhook(request, cfg, store, ip, ctx, cors);
      }
      if (request.method === 'GET' && url.pathname.startsWith('/api/payment/')) {
        const id = decodeURIComponent(url.pathname.slice('/api/payment/'.length));
        return await handleStatus(cfg, store, id, cors);
      }
      return json(404, { error: 'not found' }, cors);
    } catch (e) {
      log('необработанная ошибка:', e && e.message);
      return json(500, { error: 'internal error' }, cors);
    }
  }
};

export { TELEGRAM_RE, EMAIL_RE, CHECKOUT_LIMIT, CHECKOUT_WINDOW_MS };
