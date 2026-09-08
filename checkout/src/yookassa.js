/* Клиент API ЮKassa. Ровно два вызова: создать платёж и прочитать платёж.
 *
 * Чтение — не роскошь, а основа проверки вебхука: тело уведомления приходит
 * из сети и доверять ему нельзя, поэтому по его payment id мы спрашиваем
 * статус у самой ЮKassa и верим только ответу.
 */
'use strict';

const { rubles } = require('./config');

/* Адрес API берём из конфигурации, а не из process.env: тот же модуль
 * работает и в Cloudflare Worker, где переменные окружения приходят иначе.
 * Переопределяется только в тестах. */
const DEFAULT_API = 'https://api.yookassa.ru/v3';

/* btoa есть и в браузерных средах, и в Workers; Buffer — только в Node.
 * Строка «shopId:secretKey» — латиница и цифры, поэтому побайтовое
 * преобразование здесь корректно. */
function base64(str) {
  if (typeof btoa === 'function') return btoa(str);
  return Buffer.from(str, 'binary').toString('base64');
}

function authHeader(cfg) {
  return 'Basic ' + base64(`${cfg.shopId}:${cfg.secretKey}`);
}

async function request(cfg, method, path, { body, idempotenceKey } = {}) {
  const headers = {
    'Authorization': authHeader(cfg),
    'Content-Type': 'application/json'
  };
  if (idempotenceKey) headers['Idempotence-Key'] = idempotenceKey;

  const res = await fetch((cfg.yookassaApi || DEFAULT_API) + path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(15000)
  });

  const text = await res.text();
  let json = null;
  try { json = text ? JSON.parse(text) : null; } catch (e) { /* оставим null */ }

  if (!res.ok) {
    // Описание ошибки от ЮKassa полезно в логе, но секрет туда попасть не может.
    const detail = json && (json.description || json.code) ? `${json.code || ''} ${json.description || ''}`.trim() : text.slice(0, 200);
    const err = new Error(`ЮKassa ${method} ${path} → ${res.status}: ${detail}`);
    err.status = res.status;
    throw err;
  }
  return json;
}

/* Idempotence-Key — идентификатор нашего заказа. Повторный запрос с тем же
 * ключом возвращает тот же платёж, а не создаёт второй: пользователь,
 * дважды нажавший кнопку, не заплатит дважды. */
function createPayment(cfg, order) {
  const term = cfg.terms[order.days];
  const body = {
    amount: { value: rubles(term.kopecks), currency: 'RUB' },
    capture: true,
    confirmation: {
      type: 'redirect',
      return_url: `${cfg.publicUrl}/checkout.html?order=${encodeURIComponent(order.id)}`
    },
    description: term.title,
    metadata: { order_id: order.id, days: String(order.days), telegram: order.telegram }
  };

  if (cfg.sendReceipt) {
    body.receipt = {
      customer: order.email ? { email: order.email } : { email: cfg.receiptFallbackEmail },
      items: [{
        description: term.title,
        quantity: '1.00',
        amount: { value: rubles(term.kopecks), currency: 'RUB' },
        vat_code: 1,                 // без НДС
        payment_mode: 'full_prepayment',
        payment_subject: 'service'
      }]
    };
  }

  return request(cfg, 'POST', '/payments', { body, idempotenceKey: order.id });
}

function getPayment(cfg, paymentId) {
  return request(cfg, 'GET', `/payments/${encodeURIComponent(paymentId)}`);
}

module.exports = { createPayment, getPayment, request };
