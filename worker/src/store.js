/* Хранилище заказов на Cloudflare D1.
 *
 * Тот же набор методов, что у серверного checkout/src/store.js, но
 * асинхронный: D1 отвечает промисами. Из-за этого общий код выдачи
 * (checkout/src/fulfil.js) ждёт записи через await — на сервере await
 * над обычным значением безвреден, здесь он обязателен.
 */

/* Ключ ограничителя — хеш адреса, а не сам адрес: список адресов
 * покупателей сервису про приватность вести незачем. */
export async function throttleKey(ip, salt) {
  const data = new TextEncoder().encode(salt + '|' + ip);
  const digest = await crypto.subtle.digest('SHA-256', data);
  return [...new Uint8Array(digest)].slice(0, 16)
    .map((b) => b.toString(16).padStart(2, '0')).join('');
}

export function open(db) {
  return {
    async create(order) {
      await db.prepare(
        'INSERT INTO orders (id, days, kopecks, telegram, email) VALUES (?, ?, ?, ?, ?)'
      ).bind(order.id, order.days, order.kopecks, order.telegram, order.email || null).run();
      return this.byId(order.id);
    },

    /* Платёж в ЮKassa к этому моменту уже создан, поэтому ошибка записи
     * не должна ронять запрос: вебхук найдёт заказ по metadata.order_id
     * даже без этой связи. Возвращаем результат, чтобы вызывающий
     * мог написать в лог. */
    async attachPayment(id, paymentId) {
      try {
        await db.prepare(
          "UPDATE orders SET payment_id = ?, updated_at = datetime('now') WHERE id = ?"
        ).bind(paymentId, id).run();
        return true;
      } catch (e) {
        return e;
      }
    },

    byId(id) {
      return db.prepare('SELECT * FROM orders WHERE id = ?').bind(id).first();
    },

    byPayment(paymentId) {
      return db.prepare('SELECT * FROM orders WHERE payment_id = ?').bind(paymentId).first();
    },

    async setStatus(id, status) {
      await db.prepare(
        "UPDATE orders SET status = ?, updated_at = datetime('now') WHERE id = ?"
      ).bind(status, id).run();
    },

    async markFulfilled(id) {
      await db.prepare(
        `UPDATE orders SET fulfilled_at = datetime('now'), fulfil_error = NULL,
         updated_at = datetime('now') WHERE id = ?`
      ).bind(id).run();
    },

    async setFulfilError(id, message) {
      await db.prepare(
        "UPDATE orders SET fulfil_error = ?, updated_at = datetime('now') WHERE id = ?"
      ).bind(String(message).slice(0, 500), id).run();
    },

    // Оплачено, но не выдано — требует вмешательства.
    async stranded() {
      const r = await db.prepare(
        `SELECT * FROM orders WHERE status = 'succeeded' AND fulfilled_at IS NULL
         ORDER BY created_at`
      ).all();
      return r.results || [];
    },

    /* Грубый ограничитель: без него один скрипт способен наплодить
     * тысячи платежей в ЮKassa. Гонка двух одновременных запросов здесь
     * возможна и допустима — задача не считать точно, а не дать залить. */
    async allowCheckout(key, limit, windowMs) {
      const now = Date.now();
      const row = await db.prepare('SELECT hits, window_at FROM throttle WHERE key = ?')
        .bind(key).first();

      if (!row || now - row.window_at >= windowMs) {
        await db.prepare(
          `INSERT INTO throttle (key, hits, window_at) VALUES (?, 1, ?)
           ON CONFLICT(key) DO UPDATE SET hits = 1, window_at = excluded.window_at`
        ).bind(key, now).run();
        // Заодно подчищаем протухшие окна, чтобы таблица не росла.
        await db.prepare('DELETE FROM throttle WHERE window_at < ?')
          .bind(now - windowMs).run();
        return true;
      }

      if (row.hits >= limit) return false;
      await db.prepare('UPDATE throttle SET hits = hits + 1 WHERE key = ?').bind(key).run();
      return true;
    }
  };
}
