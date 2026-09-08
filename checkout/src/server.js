/* HTTP-слой чекаута: четыре маршрута на встроенном node:http.
 *
 * Правило, вокруг которого всё построено: клиенту нельзя верить ни в чём,
 * что касается денег. Он присылает только число дней; сумму берём из
 * тарифов на сервере. Тело вебхука тоже приходит из сети, поэтому статус
 * платежа перечитываем из API ЮKassa и верим только ему.
 */
'use strict';

const http = require('node:http');
const crypto = require('node:crypto');

const { rubles } = require('./config');
const yookassa = require('./yookassa');
const net = require('./net');
const { deliver } = require('./fulfil');

const TELEGRAM_RE = /^@?[A-Za-z0-9_]{5,32}$/;
const EMAIL_RE = /^[^@\s]+@[^@\s.]+\.[^@\s]{2,}$/;
const MAX_BODY = 64 * 1024;

/* Настоящий адрес клиента. Заголовку X-Real-IP верим только когда прокси
 * объявлен своим: иначе любой сможет назваться адресом ЮKassa. */
function clientIp(req, cfg) {
  if (cfg.trustProxy) {
    const h = req.headers['x-real-ip'] || req.headers['x-forwarded-for'];
    if (h) return String(h).split(',')[0].trim();
  }
  return (req.socket && req.socket.remoteAddress) || '';
}

function log(...args) {
  console.log(new Date().toISOString(), ...args);
}

/* Простой лимит на создание заказов: без него один скрипт способен
 * наплодить тысячи платежей в ЮKassa. */
function rateLimiter({ limit, windowMs }) {
  const hits = new Map();
  return function allow(key) {
    const now = Date.now();
    const fresh = (hits.get(key) || []).filter((t) => now - t < windowMs);
    if (fresh.length >= limit) { hits.set(key, fresh); return false; }
    fresh.push(now);
    hits.set(key, fresh);
    if (hits.size > 10000) hits.clear();      // грубая защита от роста памяти
    return true;
  };
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on('data', (c) => {
      size += c.length;
      if (size > MAX_BODY) { reject(new Error('тело запроса слишком большое')); req.destroy(); return; }
      chunks.push(c);
    });
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    req.on('error', reject);
  });
}

function send(res, status, payload, extraHeaders) {
  const body = JSON.stringify(payload);
  res.writeHead(status, Object.assign({
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff'
  }, extraHeaders || {}));
  res.end(body);
}

function create(cfg, store) {
  const allowCheckout = rateLimiter({ limit: 10, windowMs: 60 * 60 * 1000 });

  function cors(req, res) {
    const origin = req.headers.origin;
    if (origin && origin === cfg.publicUrl) {
      res.setHeader('Access-Control-Allow-Origin', origin);
      res.setHeader('Vary', 'Origin');
    }
    res.setHeader('Access-Control-Allow-Methods', 'POST, GET, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  }

  async function handleCheckout(req, res, ip) {
    if (!allowCheckout(ip)) {
      return send(res, 429, { error: 'Слишком много попыток. Попробуйте через час.' });
    }

    let body;
    try { body = JSON.parse(await readBody(req) || '{}'); }
    catch (e) { return send(res, 400, { error: 'Некорректный JSON' }); }

    const term = cfg.terms[Number(body.days)];
    if (!term) {
      return send(res, 400, { error: 'Неизвестный срок подписки' });
    }

    const telegram = String(body.telegram || '').trim();
    if (!TELEGRAM_RE.test(telegram)) {
      return send(res, 400, {
        error: 'Укажите имя пользователя Telegram: латиница, цифры и подчёркивание, от 5 до 32 символов'
      });
    }

    const email = String(body.email || '').trim();
    if (email && !EMAIL_RE.test(email)) {
      return send(res, 400, { error: 'Некорректный адрес электронной почты' });
    }
    if (cfg.sendReceipt && cfg.receiptEmailRequired && !email) {
      return send(res, 400, { error: 'Для чека нужен адрес электронной почты' });
    }

    const order = store.create({
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
      return send(res, 502, { error: 'Платёжный сервис недоступен. Попробуйте позже или оплатите в боте.' });
    }

    const attached = store.attachPayment(order.id, payment.id);
    if (attached !== true) {
      // Платёж создан, ссылку отдаём — иначе клиент потеряет оплату из-за
      // сбоя записи. Вебхук найдёт заказ по metadata.order_id.
      log(`ВНИМАНИЕ: заказ ${order.id}: платёж ${payment.id} создан, ` +
          `но не записан в базу — ${attached.message}`);
    }
    const url = payment.confirmation && payment.confirmation.confirmation_url;
    if (!url) {
      log(`заказ ${order.id}: ЮKassa не вернула ссылку подтверждения`);
      return send(res, 502, { error: 'Платёжный сервис вернул неожиданный ответ' });
    }

    log(`заказ ${order.id}: платёж ${payment.id} создан на ${rubles(order.kopecks)} ₽`);
    return send(res, 200, { order_id: order.id, confirmation_url: url });
  }

  /* Уведомление об оплате. Тело используем только чтобы узнать id платежа —
   * всё остальное берём из ответа API, который подписан нашим ключом. */
  async function handleWebhook(req, res, ip) {
    if (cfg.verifyWebhookIp && !net.isAllowed(ip)) {
      log(`вебхук с постороннего адреса ${ip} отклонён`);
      return send(res, 403, { error: 'forbidden' });
    }

    let body;
    try { body = JSON.parse(await readBody(req) || '{}'); }
    catch (e) { return send(res, 400, { error: 'bad json' }); }

    const paymentId = body && body.object && body.object.id;
    if (!paymentId || typeof paymentId !== 'string') {
      return send(res, 400, { error: 'no payment id' });
    }

    let payment;
    try {
      payment = await yookassa.getPayment(cfg, paymentId);
    } catch (e) {
      log(`вебхук ${paymentId}: не удалось перечитать платёж — ${e.message}`);
      // 500 — ЮKassa повторит уведомление позже, и это правильно.
      return send(res, 500, { error: 'cannot verify' });
    }

    const orderId = payment.metadata && payment.metadata.order_id;
    const order = orderId ? store.byId(orderId) : store.byPayment(paymentId);
    if (!order) {
      log(`вебхук ${paymentId}: заказ не найден, игнорируем`);
      return send(res, 200, { ok: true });
    }

    // Сумма из API должна совпадать с той, на которую мы выставляли счёт.
    const expected = rubles(order.kopecks);
    const actual = payment.amount && payment.amount.value;
    if (actual !== expected || (payment.amount && payment.amount.currency) !== 'RUB') {
      log(`ВНИМАНИЕ: заказ ${order.id}: сумма не совпала (ждали ${expected}, пришло ${actual})`);
      return send(res, 200, { ok: true });
    }

    if (payment.status === 'canceled') {
      store.setStatus(order.id, 'canceled');
      return send(res, 200, { ok: true });
    }
    if (payment.status !== 'succeeded' || !payment.paid) {
      return send(res, 200, { ok: true });
    }

    if (order.fulfilled_at) {
      // Повторное уведомление о том же платеже — выдавать второй раз нельзя.
      return send(res, 200, { ok: true, already: true });
    }

    store.setStatus(order.id, 'succeeded');
    // Отвечаем сразу: ЮKassa ждёт ответ, а выдача может занять время.
    send(res, 200, { ok: true });
    deliver(cfg, store, store.byId(order.id), log).catch((e) =>
      log(`заказ ${order.id}: выдача упала — ${e.message}`));
  }

  function handleStatus(res, orderId) {
    const order = store.byId(orderId);
    if (!order) return send(res, 404, { error: 'Заказ не найден' });
    return send(res, 200, {
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
    });
  }

  const server = http.createServer(async (req, res) => {
    const ip = clientIp(req, cfg);
    const url = new URL(req.url, 'http://localhost');
    cors(req, res);

    if (req.method === 'OPTIONS') { res.writeHead(204); return res.end(); }

    try {
      if (req.method === 'GET' && url.pathname === '/health') {
        const stranded = store.stranded();
        return send(res, stranded.length ? 503 : 200, {
          status: stranded.length ? 'attention' : 'ok',
          stranded_orders: stranded.length
        });
      }
      if (req.method === 'POST' && url.pathname === '/api/checkout') {
        return await handleCheckout(req, res, ip);
      }
      if (req.method === 'POST' && url.pathname === '/api/yookassa/webhook') {
        return await handleWebhook(req, res, ip);
      }
      if (req.method === 'GET' && url.pathname.startsWith('/api/payment/')) {
        return handleStatus(res, decodeURIComponent(url.pathname.slice('/api/payment/'.length)));
      }
      return send(res, 404, { error: 'not found' });
    } catch (e) {
      log('необработанная ошибка:', e && e.message);
      return send(res, 500, { error: 'internal error' });
    }
  });

  return server;
}

module.exports = { create, rateLimiter, TELEGRAM_RE, EMAIL_RE };
