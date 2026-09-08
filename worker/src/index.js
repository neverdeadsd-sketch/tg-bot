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

/* Именованных экспортов у этого модуля быть не должно: среда Workers
 * считает каждый из них обработчиком и отказывается запускать Worker,
 * если экспорт — не функция («Incorrect type for map entry»). Сборка
 * такое пропускает, падает только запуск. Поэтому здесь только
 * export default. */
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

/* Текст ошибки уходит в разметку — экранируем, хотя он и наш собственный:
 * в него подставляются имена переменных окружения. */
function escapeHtml(v) {
  return String(v == null ? '' : v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function wantsHtml(request) {
  return (request.headers.get('Accept') || '').includes('text/html');
}

/* Страница проверки. Ничего чувствительного: состояние, число оплаченных
 * но невыданных заказов и способ выдачи. Ни ключей, ни адресов. */
function healthPage(status, body, cors) {
  const ok = body.status === 'ok';
  const noSchema = body.status === 'no_schema';
  const notConfigured = body.status === 'not_configured';
  const html = `<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Оплата HollVPN — состояние</title>
<style>
  :root { color-scheme: light dark; }
  body { margin:0; min-height:100dvh; display:grid; place-items:center;
         font:16px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
         background:#0b1220; color:#dde7f3; padding:24px; }
  .card { max-width:32rem; width:100%; background:#131e2e; border:1px solid #223047;
          border-radius:14px; padding:24px 22px; }
  h1 { margin:0 0 4px; font-size:1.5rem; letter-spacing:-.02em;
       color:${ok ? '#4ade80' : '#fbbf24'}; }
  p { margin:0 0 18px; color:#8ba0b8; font-size:.95rem; }
  dl { display:grid; grid-template-columns:auto 1fr; gap:8px 16px; margin:0;
       font-variant-numeric:tabular-nums; }
  dt { color:#8ba0b8; font-size:.9rem; }
  dd { margin:0; font-weight:600; }
</style>
<div class="card">
  <h1>${notConfigured ? 'Не хватает настройки'
      : noSchema ? 'Не хватает таблиц'
      : ok ? 'Оплата работает' : 'Нужно вмешательство'}</h1>
  <p>${notConfigured
      ? escapeHtml(body.error)
      : noSchema
      ? 'База привязана, но схема в ней не выполнена. Откройте базу D1 в панели Cloudflare, вкладка Console, и выполните содержимое worker/schema.sql.'
      : ok
      ? 'Сервис оплаты поднят, база на месте, способ сообщить об оплате настроен.'
      : 'Есть оплаченные заказы, по которым подписка не выдана. Деньги получены, услуга — нет.'}</p>
  ${noSchema || notConfigured ? '' : `<dl>
    <dt>Состояние</dt><dd>${body.status}</dd>
    <dt>Оплачено, но не выдано</dt><dd>${body.stranded_orders}</dd>
    <dt>Выдача</dt><dd>${body.delivery_mode === 'auto'
      ? 'автоматическая, через бота' : 'вручную, с уведомлением в Telegram'}</dd>
  </dl>`}
</div>`;
  return new Response(html, {
    status,
    headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store', ...cors }
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
    const url = new URL(request.url);

    let cfg;
    try {
      cfg = load(env);
    } catch (e) {
      /* Настройка неполная — принимать деньги нельзя. Серверный вариант
       * в этом случае не поднимается; Worker поднять невозможно «наполовину»,
       * поэтому он честно отвечает, что оплата недоступна.
       *
       * Причину называем только на странице состояния: это имена
       * ненастроенных переменных, не их значения. Знать их полезно тому,
       * кто настраивает, и бесполезно тому, кто ищет чем поживиться, —
       * а без этого приходится гадать и разворачивать заново по кругу. */
      log('конфигурация не принята:', e.message);
      const generic = 'Оплата на сайте временно недоступна. Оплатите в боте.';
      if (url.pathname !== '/api/health') return json(503, { error: generic });

      const body = { status: 'not_configured', error: e.message };
      return wantsHtml(request) ? healthPage(503, body, {}) : json(503, body, {});
    }

    const cors = corsHeaders(request, cfg);
    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors });

    if (!env.DB) {
      log('не привязана база D1');
      return json(503, { error: 'Оплата на сайте временно недоступна. Оплатите в боте.' }, cors);
    }

    const store = open(env.DB);
    const ip = clientIp(request);

    try {
      if (request.method === 'GET' && url.pathname === '/api/health') {
        let stranded;
        try {
          stranded = await store.stranded();
        } catch (e) {
          /* Самая частая беда при установке: база привязана, а схему в ней
           * не выполнили. Без этой ветки ответом было бы «internal error»,
           * по которому не догадаться, что делать. */
          const noSchema = /no such table/i.test(e && e.message);
          if (!noSchema) throw e;
          log('в базе нет таблиц — не выполнена schema.sql');
          const body = {
            status: 'no_schema',
            error: 'В базе нет таблиц. Выполните worker/schema.sql в консоли базы D1.'
          };
          return wantsHtml(request) ? healthPage(503, body, cors) : json(503, body, cors);
        }

        const status = stranded.length ? 503 : 200;
        const body = {
          status: stranded.length ? 'attention' : 'ok',
          stranded_orders: stranded.length,
          delivery_mode: cfg.deliveryMode
        };
        /* Эту страницу открывают браузером с телефона, а json браузер
         * с nosniff охотно скачивает файлом вместо показа. Человеку —
         * страницу, программам — прежний json. */
        return wantsHtml(request)
          ? healthPage(status, body, cors)
          : json(status, body, cors);
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
