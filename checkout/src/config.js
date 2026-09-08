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

    /* Куда сообщить об оплате, чтобы выдать доступ.
     *
     * Способа два, и хотя бы один обязателен:
     *
     *   FULFILMENT_URL — эндпоинт бота, выдаёт подписку сам. Основной путь.
     *   TELEGRAM_*     — сообщение вам в Telegram, выдаёте руками.
     *
     * Без обоих сервис не стартует: чекаут, который умеет принять деньги
     * и никак не сообщить об этом, — это способ собрать оплаты и не оказать
     * услугу. Лучше не подняться, чем подняться таким. */
    fulfilmentUrl:   optional('FULFILMENT_URL', ''),
    fulfilmentToken: optional('FULFILMENT_TOKEN', ''),

    telegramToken:  optional('TELEGRAM_BOT_TOKEN', ''),
    telegramChatId: optional('TELEGRAM_ADMIN_CHAT_ID', ''),

    port:   Number(optional('PORT', '8080')),
    dbPath: optional('DB_PATH', './orders.db'),

    /* Чек. У самозанятого чек формируется в «Мой налог», а не в ЮKassa,
     * поэтому по умолчанию выключено: передача receipt в магазин, не
     * настроенный на 54-ФЗ, приводит к ошибке создания платежа. */
    sendReceipt: optional('SEND_RECEIPT', 'false') === 'true',
    receiptEmailRequired: optional('RECEIPT_EMAIL_REQUIRED', 'false') === 'true',

    // Проверка адреса источника вебхука. Выключать только локально.
    verifyWebhookIp: optional('VERIFY_WEBHOOK_IP', 'true') !== 'false',

    /* За nginx сервис видит адрес прокси, а не ЮKassa, и проверка источника
     * отклонила бы все настоящие уведомления. Включите, если перед сервисом
     * стоит обратный прокси, который проставляет X-Real-IP. Включать только
     * когда прокси действительно ваш: иначе заголовок подделает кто угодно. */
    trustProxy: optional('TRUST_PROXY', 'false') === 'true',

    /* Паузы между попытками выдачи, мс. Переопределяются только в тестах —
     * в бою нужны именно длинные, чтобы пережить перезапуск бота. */
    fulfilRetries: optional('FULFIL_RETRY_MS', '')
      ? optional('FULFIL_RETRY_MS', '').split(',').map(Number)
      : null,

    terms: TERMS
  };

  if (!/^https?:\/\//.test(cfg.publicUrl)) {
    throw new Error('PUBLIC_URL должен начинаться с http:// или https://');
  }
  if ((cfg.telegramToken && !cfg.telegramChatId) || (!cfg.telegramToken && cfg.telegramChatId)) {
    throw new Error('TELEGRAM_BOT_TOKEN и TELEGRAM_ADMIN_CHAT_ID задаются только вместе');
  }

  var hasTelegram = Boolean(cfg.telegramToken && cfg.telegramChatId);
  if (!cfg.fulfilmentUrl && !hasTelegram) {
    throw new Error(
      'Не настроен ни один способ сообщить об оплате.\n' +
      '  Задайте FULFILMENT_URL (бот выдаёт подписку сам)\n' +
      '  или TELEGRAM_BOT_TOKEN вместе с TELEGRAM_ADMIN_CHAT_ID (выдаёте вручную).\n' +
      '  Сервис не запускается без этого намеренно: иначе он принимал бы\n' +
      '  деньги, не сообщая об этом никому.'
    );
  }
  if (cfg.fulfilmentUrl && !/^https?:\/\//.test(cfg.fulfilmentUrl)) {
    throw new Error('FULFILMENT_URL должен начинаться с http:// или https://');
  }

  // Выдаёт бот или человек — от этого зависит, что мы говорим покупателю.
  cfg.deliveryMode = cfg.fulfilmentUrl ? 'auto' : 'manual';
  cfg.hasTelegram = hasTelegram;
  if (!Number.isInteger(cfg.port) || cfg.port < 1 || cfg.port > 65535) {
    throw new Error('PORT должен быть числом от 1 до 65535');
  }
  return cfg;
}

function rubles(kopecks) {
  return (kopecks / 100).toFixed(2);
}

module.exports = { load, TERMS, rubles };
