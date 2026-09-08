/* Конфигурация Worker.
 *
 * В Workers переменные приходят не из process.env, а привязками в объекте
 * env. Проверки при этом те же самые — они вынесены в общий модуль, чтобы
 * серверный вариант и Worker не разошлись в понимании того, при какой
 * настройке принимать деньги нельзя.
 */
import shared from '../../checkout/src/config.js';

const { validate, TERMS } = shared;

/* Паузы между попытками выдачи, мс. Короче серверных: там процесс живёт
 * сколько угодно, а у Worker на работу после ответа ограниченное время.
 * Четыре попытки за 15 секунд вместо 40. */
const RETRIES = [0, 1000, 4000, 10000];

export function load(env) {
  return validate({
    shopId:    env.YOOKASSA_SHOP_ID,
    secretKey: env.YOOKASSA_SECRET_KEY,

    // Origin сайта: из него собирается return_url и он же единственный
    // разрешённый источник запросов CORS.
    publicUrl: env.PUBLIC_URL,

    fulfilmentUrl:   env.FULFILMENT_URL || '',
    fulfilmentToken: env.FULFILMENT_TOKEN || '',
    telegramToken:   env.TELEGRAM_BOT_TOKEN || '',
    telegramChatId:  env.TELEGRAM_ADMIN_CHAT_ID || '',

    /* Чек. У самозанятого чек формируется в «Мой налог», а не в ЮKassa,
     * поэтому по умолчанию выключено. */
    sendReceipt:          env.SEND_RECEIPT === 'true',
    receiptEmailRequired: env.RECEIPT_EMAIL_REQUIRED === 'true',

    // Проверка адреса источника вебхука. Выключать только в тестах.
    verifyWebhookIp: env.VERIFY_WEBHOOK_IP !== 'false',

    /* Соль для хеша адреса в ограничителе частоты. Если не задана, берётся
     * секретный ключ: он всё равно есть и наружу не попадает. */
    throttleSalt: env.THROTTLE_SALT || env.YOOKASSA_SECRET_KEY || '',

    // Переопределяются только в тестах.
    yookassaApi: env.YOOKASSA_API || '',
    telegramApi: env.TELEGRAM_API || '',
    fulfilRetries: env.FULFIL_RETRY_MS
      ? String(env.FULFIL_RETRY_MS).split(',').map(Number)
      : RETRIES,

    terms: TERMS
  });
}
