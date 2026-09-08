/* Выдача подписки после оплаты.
 *
 * Сервис не знает, как устроена ваша панель, и не должен знать: он сообщает
 * об оплате по FULFILMENT_URL, а выдаёт подписку тот, кто это умеет — бот
 * или панель. Здесь важна только надёжность доставки этого сообщения:
 * деньги уже списаны, и потерять факт оплаты нельзя.
 */
'use strict';

const RETRIES = [0, 2000, 8000, 30000];   // четыре попытки, растущие паузы

async function post(cfg, payload) {
  const headers = { 'Content-Type': 'application/json' };
  if (cfg.fulfilmentToken) headers['Authorization'] = 'Bearer ' + cfg.fulfilmentToken;

  const res = await fetch(cfg.fulfilmentUrl, {
    method: 'POST',
    headers,
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(15000)
  });
  if (!res.ok) {
    throw new Error(`выдача вернула ${res.status}: ${(await res.text()).slice(0, 200)}`);
  }
  return res;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* Возвращает true, если подписка выдана. При неудаче заказ остаётся
 * со статусом succeeded и непустым fulfil_error — его видно в /health
 * и в GET /api/stranded, чтобы выдать вручную. */
async function deliver(cfg, store, order, log) {
  const payload = {
    order_id: order.id,
    payment_id: order.payment_id,
    telegram: order.telegram,
    days: order.days,
    amount_kopecks: order.kopecks,
    currency: 'RUB',
    paid_at: new Date().toISOString()
  };

  let lastError = null;
  for (let i = 0; i < RETRIES.length; i++) {
    if (RETRIES[i]) await sleep(RETRIES[i]);
    try {
      await post(cfg, payload);
      store.markFulfilled(order.id);
      log(`заказ ${order.id}: подписка выдана (${order.days} дн. → ${order.telegram})`);
      return true;
    } catch (e) {
      lastError = e;
      log(`заказ ${order.id}: попытка выдачи ${i + 1} не удалась — ${e.message}`);
    }
  }

  store.setFulfilError(order.id, lastError ? lastError.message : 'неизвестная ошибка');
  log(`ВНИМАНИЕ: заказ ${order.id} оплачен, но подписка не выдана. Требуется ручная выдача.`);
  return false;
}

module.exports = { deliver };
