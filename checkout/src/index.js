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

const db = store.open(cfg.dbPath);
const server = create(cfg, db);

server.listen(cfg.port, () => {
  console.log(`Чекаут HollVPN слушает :${cfg.port}`);
  console.log(`  сайт:   ${cfg.publicUrl}`);
  console.log(`  выдача: ${cfg.fulfilmentUrl}`);
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
