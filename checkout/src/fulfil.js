/* Выдача подписки после оплаты.
 *
 * Сервис не знает, как устроена ваша панель, и не должен знать: он сообщает
 * об оплате по FULFILMENT_URL, а выдаёт подписку тот, кто это умеет — бот
 * или панель. Здесь важна только надёжность доставки этого сообщения:
 * деньги уже списаны, и потерять факт оплаты нельзя.
 */
'use strict';

const notify = require('./notify');

const DEFAULT_RETRIES = [0, 2000, 8000, 30000];   // четыре попытки, растущие паузы

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function postFulfilment(cfg, payload) {
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
}

async function withRetries(cfg, attempt, onFail) {
  const retries = cfg.fulfilRetries || DEFAULT_RETRIES;
  let lastError = null;
  for (let i = 0; i < retries.length; i++) {
    if (retries[i]) await sleep(retries[i]);
    try { await attempt(); return null; }
    catch (e) { lastError = e; onFail(i + 1, e); }
  }
  return lastError;
}

/* Возвращает true, если обязательство сервиса выполнено.
 *
 * В режиме auto это значит «бот принял заказ и выдал подписку». В режиме
 * manual — «вам ушло сообщение с данными заказа»: дальше выдаёте руками,
 * поэтому покупателю мы и говорим не «подписка активна», а «выдаём». */
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

  if (cfg.deliveryMode === 'auto') {
    const err = await withRetries(cfg,
      () => postFulfilment(cfg, payload),
      (n, e) => log(`заказ ${order.id}: попытка выдачи ${n} не удалась — ${e.message}`));

    if (!err) {
      store.markFulfilled(order.id);
      log(`заказ ${order.id}: подписка выдана (${order.days} дн. → ${order.telegram})`);
      return true;
    }

    store.setFulfilError(order.id, err.message);
    log(`ВНИМАНИЕ: заказ ${order.id} оплачен, но подписка не выдана. Требуется ручная выдача.`);

    /* Автовыдача сорвалась — это тот случай, ради которого уведомления
     * и нужны: деньги уже получены, и узнать об этом надо сразу. */
    if (cfg.hasTelegram) {
      try {
        await notify.send(cfg, notify.failedText(order, err.message));
        log(`заказ ${order.id}: тревога отправлена в Telegram`);
      } catch (e) {
        log(`заказ ${order.id}: не удалось отправить тревогу — ${e.message}`);
      }
    }
    return false;
  }

  // Ручной режим: сообщение вам и есть доставка.
  const err = await withRetries(cfg,
    () => notify.send(cfg, notify.paidText(order)),
    (n, e) => log(`заказ ${order.id}: попытка уведомления ${n} не удалась — ${e.message}`));

  if (!err) {
    store.markFulfilled(order.id);
    log(`заказ ${order.id}: уведомление отправлено (${order.days} дн. → ${order.telegram})`);
    return true;
  }

  store.setFulfilError(order.id, err.message);
  log(`ВНИМАНИЕ: заказ ${order.id} оплачен, уведомление не доставлено. ` +
      `Данные заказа только в базе — смотрите GET /health.`);
  return false;
}

module.exports = { deliver };
