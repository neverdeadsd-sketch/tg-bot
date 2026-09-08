/* Проверяем не «работает ли счастливый путь», а то, чем в платежах ломают:
 * подменённая сумма, повторный вебхук, чужой источник уведомления, залив
 * заказами и попытка принимать деньги без способа их выдать.
 *
 * D1 подменяется настоящим SQLite (node:sqlite) с той же схемой, что уедет
 * в Cloudflare, — то есть SQL здесь выполняется по-настоящему, а не
 * имитируется.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import worker from '../src/index.js';
import { throttleKey } from '../src/store.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const SCHEMA = readFileSync(join(HERE, '..', 'schema.sql'), 'utf8');

const REAL_FETCH = globalThis.fetch;

const YOOKASSA_IP = '185.71.76.1';      // из разрешённого диапазона
const STRANGER_IP = '203.0.113.7';

/* Подмена D1 на node:sqlite: тот же диалект, те же ограничения таблиц. */
function fakeD1() {
  const db = new DatabaseSync(':memory:');
  db.exec(SCHEMA);
  return {
    _db: db,
    prepare(sql) {
      return {
        _args: [],
        bind(...args) { this._args = args; return this; },
        async first() {
          const r = db.prepare(sql).get(...this._args);
          return r === undefined ? null : r;
        },
        async run() { db.prepare(sql).run(...this._args); return { success: true }; },
        async all() { return { results: db.prepare(sql).all(...this._args) }; }
      };
    }
  };
}

const BASE_ENV = {
  YOOKASSA_SHOP_ID: '139865',
  YOOKASSA_SECRET_KEY: 'test-secret',
  PUBLIC_URL: 'https://hollvpn.ru',
  FULFILMENT_URL: 'https://bot.example/fulfil',
  VERIFY_WEBHOOK_IP: 'false',
  FULFIL_RETRY_MS: '0,10,20',
  YOOKASSA_API: 'https://api.test/v3',
  TELEGRAM_API: 'https://tg.test'
};

/* Сеть подменяем целиком: тесты не ходят ни в ЮKassa, ни в выдачу. */
function stubFetch({ payments = {}, onFulfil = () => ({ ok: true }),
                     onTelegram = () => ({ ok: true }) } = {}) {
  const calls = { created: [], fulfilled: [], telegram: [] };
  globalThis.fetch = async (url, opts = {}) => {
    const u = String(url);
    const body = opts.body ? JSON.parse(opts.body) : null;

    if (u.includes('/v3/payments') && opts.method === 'POST') {
      calls.created.push({ body, idempotenceKey: opts.headers['Idempotence-Key'] });
      const id = 'pay_' + calls.created.length;
      payments[id] = { id, status: 'pending', paid: false, amount: body.amount, metadata: body.metadata };
      return new Response(JSON.stringify({
        id, status: 'pending',
        confirmation: { confirmation_url: 'https://yoomoney.ru/confirm/' + id }
      }), { status: 200 });
    }
    if (u.includes('/v3/payments/')) {
      const id = u.split('/v3/payments/')[1];
      const p = payments[id];
      if (!p) return new Response('{"code":"not_found"}', { status: 404 });
      return new Response(JSON.stringify(p), { status: 200 });
    }
    if (u === BASE_ENV.FULFILMENT_URL) {
      calls.fulfilled.push(body);
      return new Response('{}', { status: onFulfil(body).ok ? 200 : 500 });
    }
    if (u.includes('/sendMessage')) {
      calls.telegram.push(body);
      const r = onTelegram(body);
      return new Response(r.ok ? '{"ok":true}' : '{"ok":false}', { status: r.ok ? 200 : 400 });
    }
    throw new Error('неожиданный запрос в тесте: ' + u);
  };
  return { calls, payments, restore() { globalThis.fetch = REAL_FETCH; } };
}

/* Один прогон запроса через Worker. Работу, отложенную на waitUntil,
 * собираем, чтобы тест мог её дождаться. */
function makeCtx() {
  const pending = [];
  return { ctx: { waitUntil: (p) => pending.push(p) }, settle: () => Promise.all(pending) };
}

function req(path, { method = 'GET', body, ip = STRANGER_IP, origin } = {}) {
  const headers = { 'CF-Connecting-IP': ip };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (origin) headers['Origin'] = origin;
  return new Request('https://hollvpn.ru' + path, {
    method, headers, body: body === undefined ? undefined : JSON.stringify(body)
  });
}

async function call(env, db, request) {
  const { ctx, settle } = makeCtx();
  const res = await worker.fetch(request, { ...env, DB: db }, ctx);
  return { res, json: await res.clone().json(), settle };
}

/* ------------------------------------------------------------ создание -- */

test('заказ создаётся, сумма берётся с сервера, ключ идемпотентности — id заказа', async () => {
  const net = stubFetch();
  const db = fakeD1();
  try {
    const { res, json } = await call(BASE_ENV, db, req('/api/checkout', {
      method: 'POST', body: { days: 90, telegram: 'someuser' }
    }));
    assert.equal(res.status, 200);
    assert.match(json.confirmation_url, /^https:\/\/yoomoney\.ru\/confirm\//);

    const sent = net.calls.created[0];
    assert.equal(sent.body.amount.value, '499.00');
    assert.equal(sent.body.amount.currency, 'RUB');
    assert.equal(sent.idempotenceKey, json.order_id);
    assert.equal(sent.body.metadata.order_id, json.order_id);
    assert.match(sent.body.confirmation.return_url, /hollvpn\.ru\/checkout\.html\?order=/);
  } finally { net.restore(); }
});

test('сумму из тела запроса подменить нельзя — её оттуда просто не берут', async () => {
  const net = stubFetch();
  const db = fakeD1();
  try {
    const { json } = await call(BASE_ENV, db, req('/api/checkout', {
      method: 'POST', body: { days: 365, telegram: 'someuser', amount: 1, kopecks: 1 }
    }));
    assert.ok(json.order_id);
    assert.equal(net.calls.created[0].body.amount.value, '1499.00');
  } finally { net.restore(); }
});

test('неизвестный срок отклоняется', async () => {
  const net = stubFetch();
  const db = fakeD1();
  try {
    const { res, json } = await call(BASE_ENV, db, req('/api/checkout', {
      method: 'POST', body: { days: 7, telegram: 'someuser' }
    }));
    assert.equal(res.status, 400);
    assert.match(json.error, /срок/i);
    assert.equal(net.calls.created.length, 0);
  } finally { net.restore(); }
});

test('некорректное имя в Telegram отклоняется', async () => {
  const net = stubFetch();
  const db = fakeD1();
  try {
    for (const telegram of ['ab', 'с кириллицей', 'a'.repeat(40), '']) {
      const { res } = await call(BASE_ENV, db, req('/api/checkout', {
        method: 'POST', body: { days: 30, telegram } }));
      assert.equal(res.status, 400, `прошло: ${telegram}`);
    }
    assert.equal(net.calls.created.length, 0);
  } finally { net.restore(); }
});

test('заливать заказами не даёт ограничитель', async () => {
  const net = stubFetch();
  const db = fakeD1();
  try {
    let last;
    for (let i = 0; i < 11; i++) {
      last = await call(BASE_ENV, db, req('/api/checkout', {
        method: 'POST', body: { days: 30, telegram: 'someuser' }, ip: '198.51.100.5' }));
    }
    assert.equal(last.res.status, 429);
    assert.equal(net.calls.created.length, 10);

    // Другому адресу это не мешает.
    const other = await call(BASE_ENV, db, req('/api/checkout', {
      method: 'POST', body: { days: 30, telegram: 'someuser' }, ip: '198.51.100.6' }));
    assert.equal(other.res.status, 200);
  } finally { net.restore(); }
});

test('в ограничителе хранится хеш адреса, а не адрес', async () => {
  const db = fakeD1();
  const net = stubFetch();
  try {
    await call(BASE_ENV, db, req('/api/checkout', {
      method: 'POST', body: { days: 30, telegram: 'someuser' }, ip: '198.51.100.9' }));
    const rows = db._db.prepare('SELECT key FROM throttle').all();
    assert.equal(rows.length, 1);
    assert.ok(!rows[0].key.includes('198.51.100.9'));
    assert.equal(rows[0].key, await throttleKey('198.51.100.9', BASE_ENV.YOOKASSA_SECRET_KEY));
  } finally { net.restore(); }
});

/* -------------------------------------------------------------- вебхук -- */

test('вебхук с постороннего адреса отклоняется', async () => {
  const net = stubFetch();
  const db = fakeD1();
  const env = { ...BASE_ENV, VERIFY_WEBHOOK_IP: 'true' };
  try {
    const { res } = await call(env, db, req('/api/yookassa/webhook', {
      method: 'POST', body: { object: { id: 'pay_1' } }, ip: STRANGER_IP }));
    assert.equal(res.status, 403);
  } finally { net.restore(); }
});

test('вебхук с адреса ЮKassa проходит проверку источника', async () => {
  const net = stubFetch();
  const db = fakeD1();
  const env = { ...BASE_ENV, VERIFY_WEBHOOK_IP: 'true' };
  try {
    const { res } = await call(env, db, req('/api/yookassa/webhook', {
      method: 'POST', body: { object: { id: 'нет-такого' } }, ip: YOOKASSA_IP }));
    assert.notEqual(res.status, 403);
  } finally { net.restore(); }
});

test('оплата подтверждается по API, а не по телу уведомления, и приводит к выдаче', async () => {
  const net = stubFetch();
  const db = fakeD1();
  try {
    const made = await call(BASE_ENV, db, req('/api/checkout', {
      method: 'POST', body: { days: 30, telegram: 'someuser' } }));
    const orderId = made.json.order_id;

    net.payments.pay_1.status = 'succeeded';
    net.payments.pay_1.paid = true;

    const hook = await call(BASE_ENV, db, req('/api/yookassa/webhook', {
      method: 'POST', body: { object: { id: 'pay_1', status: 'succeeded' } } }));
    assert.equal(hook.res.status, 200);
    await hook.settle();

    assert.equal(net.calls.fulfilled.length, 1);
    assert.equal(net.calls.fulfilled[0].order_id, orderId);
    assert.equal(net.calls.fulfilled[0].days, 30);
    assert.equal(net.calls.fulfilled[0].amount_kopecks, 19900);

    const st = await call(BASE_ENV, db, req('/api/payment/' + orderId));
    assert.equal(st.json.status, 'succeeded');
    assert.equal(st.json.delivered, true);
    assert.equal(st.json.needs_attention, false);
  } finally { net.restore(); }
});

test('уведомление о статусе succeeded, которого нет в API, к выдаче не приводит', async () => {
  const net = stubFetch();
  const db = fakeD1();
  try {
    await call(BASE_ENV, db, req('/api/checkout', {
      method: 'POST', body: { days: 30, telegram: 'someuser' } }));
    // Платёж в API так и остался pending — врёт именно тело уведомления.
    const hook = await call(BASE_ENV, db, req('/api/yookassa/webhook', {
      method: 'POST', body: { object: { id: 'pay_1', status: 'succeeded', paid: true } } }));
    await hook.settle();
    assert.equal(net.calls.fulfilled.length, 0);
  } finally { net.restore(); }
});

test('подменённая сумма не проходит', async () => {
  const net = stubFetch();
  const db = fakeD1();
  try {
    await call(BASE_ENV, db, req('/api/checkout', {
      method: 'POST', body: { days: 365, telegram: 'someuser' } }));
    Object.assign(net.payments.pay_1, {
      status: 'succeeded', paid: true, amount: { value: '1.00', currency: 'RUB' }
    });
    const hook = await call(BASE_ENV, db, req('/api/yookassa/webhook', {
      method: 'POST', body: { object: { id: 'pay_1' } } }));
    await hook.settle();
    assert.equal(net.calls.fulfilled.length, 0);
  } finally { net.restore(); }
});

test('повторное уведомление о том же платеже не выдаёт подписку второй раз', async () => {
  const net = stubFetch();
  const db = fakeD1();
  try {
    await call(BASE_ENV, db, req('/api/checkout', {
      method: 'POST', body: { days: 30, telegram: 'someuser' } }));
    Object.assign(net.payments.pay_1, { status: 'succeeded', paid: true });

    const first = await call(BASE_ENV, db, req('/api/yookassa/webhook', {
      method: 'POST', body: { object: { id: 'pay_1' } } }));
    await first.settle();

    const again = await call(BASE_ENV, db, req('/api/yookassa/webhook', {
      method: 'POST', body: { object: { id: 'pay_1' } } }));
    await again.settle();

    assert.equal(again.json.already, true);
    assert.equal(net.calls.fulfilled.length, 1);
  } finally { net.restore(); }
});

test('отменённый платёж помечается отменённым и не выдаётся', async () => {
  const net = stubFetch();
  const db = fakeD1();
  try {
    const made = await call(BASE_ENV, db, req('/api/checkout', {
      method: 'POST', body: { days: 30, telegram: 'someuser' } }));
    net.payments.pay_1.status = 'canceled';
    const hook = await call(BASE_ENV, db, req('/api/yookassa/webhook', {
      method: 'POST', body: { object: { id: 'pay_1' } } }));
    await hook.settle();
    const st = await call(BASE_ENV, db, req('/api/payment/' + made.json.order_id));
    assert.equal(st.json.status, 'canceled');
    assert.equal(net.calls.fulfilled.length, 0);
  } finally { net.restore(); }
});

/* -------------------------------------------------------- выдача и вид -- */

test('сорванная выдача видна в /api/health и в статусе заказа', async () => {
  const net = stubFetch({ onFulfil: () => ({ ok: false }) });
  const db = fakeD1();
  try {
    const made = await call(BASE_ENV, db, req('/api/checkout', {
      method: 'POST', body: { days: 30, telegram: 'someuser' } }));
    Object.assign(net.payments.pay_1, { status: 'succeeded', paid: true });
    const hook = await call(BASE_ENV, db, req('/api/yookassa/webhook', {
      method: 'POST', body: { object: { id: 'pay_1' } } }));
    await hook.settle();

    const st = await call(BASE_ENV, db, req('/api/payment/' + made.json.order_id));
    assert.equal(st.json.status, 'succeeded');
    assert.equal(st.json.delivered, false);
    assert.equal(st.json.needs_attention, true);

    const health = await call(BASE_ENV, db, req('/api/health'));
    assert.equal(health.res.status, 503);
    assert.equal(health.json.stranded_orders, 1);
  } finally { net.restore(); }
});

test('в ручном режиме доставка — это сообщение в Telegram', async () => {
  const net = stubFetch();
  const db = fakeD1();
  const env = { ...BASE_ENV, FULFILMENT_URL: '',
                TELEGRAM_BOT_TOKEN: 'tok', TELEGRAM_ADMIN_CHAT_ID: '42' };
  try {
    const made = await call(env, db, req('/api/checkout', {
      method: 'POST', body: { days: 180, telegram: 'someuser' } }));
    Object.assign(net.payments.pay_1, { status: 'succeeded', paid: true });
    const hook = await call(env, db, req('/api/yookassa/webhook', {
      method: 'POST', body: { object: { id: 'pay_1' } } }));
    await hook.settle();

    assert.equal(net.calls.telegram.length, 1);
    assert.equal(net.calls.telegram[0].chat_id, '42');
    assert.match(net.calls.telegram[0].text, /someuser/);

    const st = await call(env, db, req('/api/payment/' + made.json.order_id));
    assert.equal(st.json.delivery_mode, 'manual');
    assert.equal(st.json.delivered, true);
  } finally { net.restore(); }
});

/* ------------------------------------------------------------ отказы -- */

test('без способа сообщить об оплате деньги не принимаются', async () => {
  const net = stubFetch();
  const db = fakeD1();
  const env = { ...BASE_ENV, FULFILMENT_URL: '' };   // и Telegram не задан
  try {
    const { res, json } = await call(env, db, req('/api/checkout', {
      method: 'POST', body: { days: 30, telegram: 'someuser' } }));
    assert.equal(res.status, 503);
    assert.match(json.error, /боте/);
    assert.equal(net.calls.created.length, 0);
  } finally { net.restore(); }
});

test('без привязанной базы деньги не принимаются', async () => {
  const net = stubFetch();
  try {
    const { ctx } = makeCtx();
    const res = await worker.fetch(req('/api/checkout', {
      method: 'POST', body: { days: 30, telegram: 'someuser' } }), { ...BASE_ENV }, ctx);
    assert.equal(res.status, 503);
    assert.equal(net.calls.created.length, 0);
  } finally { net.restore(); }
});

test('статус несуществующего заказа — 404, а не выдумка', async () => {
  const net = stubFetch();
  const db = fakeD1();
  try {
    const { res } = await call(BASE_ENV, db, req('/api/payment/нет-такого'));
    assert.equal(res.status, 404);
  } finally { net.restore(); }
});

test('CORS открыт только для адреса сайта', async () => {
  const net = stubFetch();
  const db = fakeD1();
  try {
    const own = await call(BASE_ENV, db, req('/api/health', { origin: 'https://hollvpn.ru' }));
    assert.equal(own.res.headers.get('Access-Control-Allow-Origin'), 'https://hollvpn.ru');

    const alien = await call(BASE_ENV, db, req('/api/health', { origin: 'https://evil.example' }));
    assert.equal(alien.res.headers.get('Access-Control-Allow-Origin'), null);
  } finally { net.restore(); }
});
