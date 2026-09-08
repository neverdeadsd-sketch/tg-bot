'use strict';

const { load } = require('./config');
const store = require('./store');
const { create } = require('./server');

let cfg;
try {
  cfg = load();
} catch (e) {
  console.error('\nЧекаут не запущен: ' + e.message + '\n');
  process.exit(1);
}

let db;
try {
  db = store.open(cfg.dbPath);
} catch (e) {
  console.error(`\nНе удалось открыть базу заказов ${cfg.dbPath}: ${e.message}\n`);
  console.error('  Проверьте права на каталог и что рядом не осталось файлов');
  console.error('  -wal и -shm от удалённой базы: они держат её состояние\n');
  process.exit(1);
}
const server = create(cfg, db);

server.listen(cfg.port, () => {
  console.log(`Чекаут HollVPN слушает :${cfg.port}`);
  console.log(`  сайт:   ${cfg.publicUrl}`);
  if (cfg.deliveryMode === 'auto') {
    console.log(`  выдача: автоматически, ${cfg.fulfilmentUrl}`);
    console.log(`  тревоги в Telegram: ${cfg.hasTelegram ? 'да' : 'НЕТ — сорванную выдачу узнаете только из /health'}`);
  } else {
    console.log('  выдача: ВРУЧНУЮ — уведомление в Telegram, подписку выдаёте сами');
    console.log('  чтобы бот выдавал сам, задайте FULFILMENT_URL');
  }
  console.log(`  чек через ЮKassa: ${cfg.sendReceipt ? 'да' : 'нет (через «Мой налог»)'}`);
  const stranded = db.stranded();
  if (stranded.length) {
    console.log(`  ВНИМАНИЕ: ${stranded.length} оплаченных заказов без выданной подписки`);
  }
});

for (const sig of ['SIGINT', 'SIGTERM']) {
  process.on(sig, () => {
    server.close(() => { db.close(); process.exit(0); });
  });
}
