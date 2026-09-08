/* Уведомления в Telegram.
 *
 * Два назначения. Первое — сообщить об оплате, когда выдача происходит
 * вручную: тогда это сообщение и есть способ доставки. Второе — поднять
 * тревогу, когда автоматическая выдача сорвалась: деньги получены, доступа
 * нет, и об этом надо узнать сразу, а не из жалобы клиента.
 */
'use strict';

/* Адрес — из конфигурации, а не из process.env: модуль работает и в Worker. */
const DEFAULT_API = 'https://api.telegram.org';

/* Telegram разбирает HTML в сообщении, поэтому имя пользователя и любые
 * другие внешние данные экранируем — иначе сообщение просто не отправится. */
function esc(v) {
  return String(v == null ? '' : v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

async function send(cfg, text) {
  if (!cfg.telegramToken || !cfg.telegramChatId) return false;

  const res = await fetch(`${cfg.telegramApi || DEFAULT_API}/bot${cfg.telegramToken}/sendMessage`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      chat_id: cfg.telegramChatId,
      text,
      parse_mode: 'HTML',
      disable_web_page_preview: true
    }),
    signal: AbortSignal.timeout(15000)
  });

  if (!res.ok) {
    const body = await res.text();
    // Токен в тексте ошибки Telegram не возвращает, но URL в лог не пишем.
    throw new Error(`Telegram ответил ${res.status}: ${body.slice(0, 200)}`);
  }
  return true;
}

function money(kopecks) { return (kopecks / 100).toFixed(2).replace(/\.00$/, ''); }

/* Сообщение об оплате при ручной выдаче: всё, что нужно, чтобы выдать
 * подписку, — в одном сообщении, без похода в базу. */
function paidText(order) {
  return [
    '💳 <b>Оплачена подписка</b>',
    '',
    `Кому: ${esc(order.telegram)}`,
    `Срок: ${order.days} дн.`,
    `Сумма: ${money(order.kopecks)} ₽`,
    '',
    `Заказ: <code>${esc(order.id)}</code>`,
    `Платёж: <code>${esc(order.payment_id)}</code>`,
    '',
    '⚠️ Выдайте подписку вручную — автоматическая выдача не настроена.'
  ].join('\n');
}

function failedText(order, reason) {
  return [
    '🔴 <b>Оплата прошла, выдача сорвалась</b>',
    '',
    `Кому: ${esc(order.telegram)}`,
    `Срок: ${order.days} дн.`,
    `Сумма: ${money(order.kopecks)} ₽`,
    '',
    `Заказ: <code>${esc(order.id)}</code>`,
    `Платёж: <code>${esc(order.payment_id)}</code>`,
    `Причина: ${esc(reason)}`,
    '',
    '⚠️ Деньги получены, доступ не выдан. Выдайте вручную.'
  ].join('\n');
}

module.exports = { send, paidText, failedText, esc, money };
