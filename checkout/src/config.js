/* Конфигурация чекаута.
 *
 * Всё приходит из переменных окружения. Секретный ключ ЮKassa нигде не
 * логируется и не попадает в ответы — он существует только здесь и в
 * заголовке Authorization.
 */
'use strict';

/* Тарифы — на сервере, а не в браузере. Клиент присылает только число дней;
 * сумму он назвать не может, иначе её можно было бы подменить. */
const TERMS = {
  30:  { days: 30,  kopecks: 19900,  title: 'Доступ к сервису HollVPN, 30 дней'  },
  90:  { days: 90,  kopecks: 49900,  title: 'Доступ к сервису HollVPN, 90 дней'  },
  180: { days: 180, kopecks: 89900,  title: 'Доступ к сервису HollVPN, 180 дней' },
  365: { days: 365, kopecks: 149900, title: 'Доступ к сервису HollVPN, 365 дней' }
};

function required(name) {
  const v = process.env[name];
  if (!v || !v.trim()) {
    throw new Error(
      `Не задана переменная окружения ${name}. ` +
      'Смотрите checkout/.env.example — сервис не запускается без неё намеренно.'
    );
  }
  return v.trim();
}

function optional(name, fallback) {
  const v = process.env[name];
  return v && v.trim() ? v.trim() : fallback;
}

function load() {
  const cfg = {
    shopId:    required('YOOKASSA_SHOP_ID'),
    secretKey: required('YOOKASSA_SECRET_KEY'),

    // Origin сайта: из него собирается return_url и он же единственный
    // разрешённый источник запросов CORS.
    publicUrl: required('PUBLIC_URL').replace(/\/+$/, ''),

    /* Куда сообщить об успешной оплате, чтобы выдать подписку.
     *
     * Обязательна. Без неё сервис отказывается стартовать: чекаут, который
     * умеет принять деньги, но не умеет выдать доступ, — это способ собрать
     * оплаты и не оказать услугу. Лучше не подняться, чем подняться таким. */
    fulfilmentUrl:   required('FULFILMENT_URL'),
    fulfilmentToken: optional('FULFILMENT_TOKEN', ''),

    port:   Number(optional('PORT', '8080')),
    dbPath: optional('DB_PATH', './orders.db'),

    /* Чек. У самозанятого чек формируется в «Мой налог», а не в ЮKassa,
     * поэтому по умолчанию выключено: передача receipt в магазин, не
     * настроенный на 54-ФЗ, приводит к ошибке создания платежа. */
    sendReceipt: optional('SEND_RECEIPT', 'false') === 'true',
    receiptEmailRequired: optional('RECEIPT_EMAIL_REQUIRED', 'false') === 'true',

    // Проверка адреса источника вебхука. Выключать только локально.
    verifyWebhookIp: optional('VERIFY_WEBHOOK_IP', 'true') !== 'false',

    terms: TERMS
  };

  if (!/^https?:\/\//.test(cfg.publicUrl)) {
    throw new Error('PUBLIC_URL должен начинаться с http:// или https://');
  }
  if (!/^https?:\/\//.test(cfg.fulfilmentUrl)) {
    throw new Error('FULFILMENT_URL должен начинаться с http:// или https://');
  }
  if (!Number.isInteger(cfg.port) || cfg.port < 1 || cfg.port > 65535) {
    throw new Error('PORT должен быть числом от 1 до 65535');
  }
  return cfg;
}

function rubles(kopecks) {
  return (kopecks / 100).toFixed(2);
}

module.exports = { load, TERMS, rubles };
