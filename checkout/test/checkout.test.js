/* Проверяем не «работает ли счастливый путь», а то, чем в платежах ломают:
 * подменённая сумма, повторный вебхук, чужой источник уведомления и попытка
 * поднять сервис, который умеет брать деньги и не умеет выдавать доступ.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { once } = require('node:events');

const store = require('../src/store');
const { create } = require('../src/server');
const net = require('../src/net');
const { TERMS } = require('../src/config');

const CFG = {
  shopId: '139865',
  secretKey: 'test-secret',
  publicUrl: 'https://hollvpn.online',
  fulfilmentUrl: 'https://bot.example/fulfil',
  fulfilmentToken: '',
  port: 0,
  dbPath: ':memory:',
  sendReceipt: false,
  receiptEmailRequired: false,
  verifyWebhookIp: false,
  terms: TERMS
};

/* Подменяем сеть целиком: тесты не должны ходить ни в ЮKassa, ни в выдачу. */
function stubFetch({ payments = {}, onFulfil = () => ({ ok: true }) } = {}) {
  const calls = { created: [], fulfilled: [] };
  const real = globalThis.fetch;
  globalThis.fetch = async (url, opts = {}) => {
    // Запросы самого теста к поднятому серверу должны идти по-настоящему.
    if (String(url).startsWith('http://127.0.0.1:')) return real(url, opts);
    const body = opts.body ? JSON.parse(opts.body) : null;

    if (String(url).includes('/v3/payments') && opts.method === 'POST') {
      calls.created.push({ body, idempotenceKey: opts.headers['Idempotence-Key'] });
      const id = 'pay_' + calls.created.length;
      payments[id] = {
        id,
        status: 'pending',
        paid: false,
        amount: body.amount,
        metadata: body.metadata
      };
      return new Response(JSON.stringify({
        id, status: 'pending',
        confirmation: { confirmation_url: 'https://yoomoney.ru/confirm/' + id }
      }), { status: 200 });
    }

    if (String(url).includes('/v3/payments/')) {
      const id = String(url).split('/v3/payments/')[1];
      const p = payments[id];
      if (!p) return new Response('{"code":"not_found"}', { status: 404 });
      return new Response(JSON.stringify(p), { status: 200 });
    }

    if (String(url) === CFG.fulfilmentUrl) {
      calls.fulfilled.push(body);
      const r = onFulfil(body);
      return new Response('{}', { status: r.ok ? 200 : 500 });
    }
    throw new Error('неожиданный запрос: ' + url);
  };
  return { calls, payments };
}

async function withServer(fn, opts) {
  const db = store.open(':memory:');
  const stub = stubFetch(opts);
  const server = create(CFG, db);
  server.listen(0);
  await once(server, 'listening');
  const base = `http://127.0.0.1:${server.address().port}`;
  const real = globalThis.fetch;
  try { await fn({ base, db, stub }); }
  finally { globalThis.fetch = real; server.close(); db.close(); }
}

const post = (base, path, body) =>
  fetch(base + path, { method: 'POST', headers: { 'Content-Type': 'application/json' },
                       body: JSON.stringify(body) });

test('сумма берётся из тарифов на сервере, а не из запроса', async () => {
  await withServer(async ({ base, stub }) => {
    // Клиент пытается заплатить рубль за годовую подписку.
    const res = await post(base, '/api/checkout',
      { days: 365, telegram: 'anna_test', amount: '1.00', kopecks: 100, price: 1 });
    assert.equal(res.status, 200);
    assert.equal(stub.calls.created[0].body.amount.value, '1499.00');
    assert.equal(stub.calls.created[0].body.amount.currency, 'RUB');
  });
});

test('неизвестный срок отвергается', async () => {
  await withServer(async ({ base }) => {
    for (const days of [1, 7, 400, 0, -30, 'год', null]) {
      const res = await post(base, '/api/checkout', { days, telegram: 'anna_test' });
      assert.equal(res.status, 400, `срок ${days} должен быть отвергнут`);
    }
  });
});

test('некорректный Telegram отвергается', async () => {
  await withServer(async ({ base }) => {
    for (const tg of ['', 'ab', 'имя_кириллицей', 'with space', 'a'.repeat(33), '<script>']) {
      const res = await post(base, '/api/checkout', { days: 30, telegram: tg });
      assert.equal(res.status, 400, `«${tg}» должно быть отвергнуто`);
    }
    const ok = await post(base, '/api/checkout', { days: 30, telegram: 'anna_test' });
    assert.equal(ok.status, 200);
  });
});

test('ключ идемпотентности равен идентификатору заказа', async () => {
  await withServer(async ({ base, stub }) => {
    const res = await post(base, '/api/checkout', { days: 90, telegram: 'anna_test' });
    const { order_id } = await res.json();
    assert.equal(stub.calls.created[0].idempotenceKey, order_id);
  });
});

test('вебхук выдаёт подписку только после подтверждения статуса в API', async () => {
  await withServer(async ({ base, db, stub }) => {
    const { order_id } = await (await post(base, '/api/checkout',
      { days: 30, telegram: 'anna_test' })).json();
    const paymentId = db.byId(order_id).payment_id;

    // Уведомление приходит, но в API платёж всё ещё pending — выдачи нет.
    await post(base, '/api/yookassa/webhook', { object: { id: paymentId } });
    assert.equal(stub.calls.fulfilled.length, 0);
    assert.equal(db.byId(order_id).status, 'pending');

    // Теперь платёж действительно оплачен.
    Object.assign(stub.payments[paymentId], { status: 'succeeded', paid: true });
    await post(base, '/api/yookassa/webhook', { object: { id: paymentId } });
    await new Promise((r) => setTimeout(r, 120));

    assert.equal(stub.calls.fulfilled.length, 1);
    assert.equal(stub.calls.fulfilled[0].days, 30);
    assert.equal(stub.calls.fulfilled[0].telegram, '@anna_test');
    assert.equal(stub.calls.fulfilled[0].amount_kopecks, 19900);
    assert.ok(db.byId(order_id).fulfilled_at);
  });
});

test('повторный вебхук не выдаёт подписку дважды', async () => {
  await withServer(async ({ base, db, stub }) => {
    const { order_id } = await (await post(base, '/api/checkout',
      { days: 180, telegram: 'anna_test' })).json();
    const paymentId = db.byId(order_id).payment_id;
    Object.assign(stub.payments[paymentId], { status: 'succeeded', paid: true });

    for (let i = 0; i < 4; i++) {
      await post(base, '/api/yookassa/webhook', { object: { id: paymentId } });
      await new Promise((r) => setTimeout(r, 60));
    }
    assert.equal(stub.calls.fulfilled.length, 1, 'выдача должна произойти ровно один раз');
  });
});

test('вебхук с несовпадающей суммой не выдаёт подписку', async () => {
  await withServer(async ({ base, db, stub }) => {
    const { order_id } = await (await post(base, '/api/checkout',
      { days: 365, telegram: 'anna_test' })).json();
    const paymentId = db.byId(order_id).payment_id;
    // Кто-то оплатил 1 ₽ вместо 1499 ₽.
    Object.assign(stub.payments[paymentId], {
      status: 'succeeded', paid: true, amount: { value: '1.00', currency: 'RUB' }
    });

    await post(base, '/api/yookassa/webhook', { object: { id: paymentId } });
    await new Promise((r) => setTimeout(r, 120));
    assert.equal(stub.calls.fulfilled.length, 0);
    assert.notEqual(db.byId(order_id).status, 'succeeded');
  });
});

test('вебхук о неизвестном платеже не роняет сервис', async () => {
  await withServer(async ({ base, stub }) => {
    const res = await post(base, '/api/yookassa/webhook', { object: { id: 'pay_подделка' } });
    assert.equal(res.status, 500);          // не смогли проверить — пусть повторят
    assert.equal(stub.calls.fulfilled.length, 0);
  });
});

test('неудачная выдача помечает заказ как требующий внимания', async () => {
  await withServer(async ({ base, db, stub }) => {
    const { order_id } = await (await post(base, '/api/checkout',
      { days: 30, telegram: 'anna_test' })).json();
    const paymentId = db.byId(order_id).payment_id;
    Object.assign(stub.payments[paymentId], { status: 'succeeded', paid: true });

    await post(base, '/api/yookassa/webhook', { object: { id: paymentId } });
    await new Promise((r) => setTimeout(r, 250));

    const order = db.byId(order_id);
    assert.equal(order.status, 'succeeded');
    assert.equal(order.fulfilled_at, null);

    const status = await (await fetch(`${base}/api/payment/${order_id}`)).json();
    assert.equal(status.needs_attention, true);
    assert.equal(status.delivered, false);

    const health = await fetch(base + '/health');
    assert.equal(health.status, 503, 'health должен сигналить о невыданных заказах');
  }, { onFulfil: () => ({ ok: false }) });
});

test('статус заказа не раскрывает чужие данные', async () => {
  await withServer(async ({ base }) => {
    const res = await fetch(base + '/api/payment/00000000-0000-0000-0000-000000000000');
    assert.equal(res.status, 404);
  });
});

test('конфигурация не поднимается без адреса выдачи', () => {
  const { load } = require('../src/config');
  const saved = { ...process.env };
  process.env.YOOKASSA_SHOP_ID = '139865';
  process.env.YOOKASSA_SECRET_KEY = 'x';
  process.env.PUBLIC_URL = 'https://hollvpn.online';
  delete process.env.FULFILMENT_URL;

  assert.throws(() => load(), /FULFILMENT_URL/,
    'сервис, умеющий брать деньги и не умеющий выдавать доступ, стартовать не должен');

  process.env.FULFILMENT_URL = 'https://bot.example/fulfil';
  assert.ok(load().fulfilmentUrl);
  Object.assign(process.env, saved);
});

test('адреса уведомлений ЮKassa проверяются', () => {
  assert.equal(net.isAllowed('185.71.76.10'), true);
  assert.equal(net.isAllowed('77.75.156.11'), true);
  assert.equal(net.isAllowed('2a02:5180::9'), true);
  assert.equal(net.isAllowed('203.0.113.7'), false);
});
