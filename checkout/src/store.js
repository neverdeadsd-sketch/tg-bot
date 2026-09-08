/* Хранилище заказов на node:sqlite — он встроен в Node 22, поэтому у сервиса
 * нет ни одной внешней зависимости.
 *
 * Суммы хранятся в копейках целым числом: рубли с копейками в double — это
 * способ однажды недосчитаться копейки и не понять почему.
 */
'use strict';

const { DatabaseSync } = require('node:sqlite');

const SCHEMA = `
CREATE TABLE IF NOT EXISTS orders (
  id            TEXT PRIMARY KEY,
  payment_id    TEXT UNIQUE,
  days          INTEGER NOT NULL,
  kopecks       INTEGER NOT NULL CHECK (kopecks > 0),
  telegram      TEXT NOT NULL,
  email         TEXT,
  status        TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','succeeded','canceled')),
  fulfilled_at  TEXT,
  fulfil_error  TEXT,
  created_at    TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS orders_payment ON orders(payment_id);
CREATE INDEX IF NOT EXISTS orders_unfulfilled
  ON orders(status, fulfilled_at) WHERE status = 'succeeded' AND fulfilled_at IS NULL;
`;

function open(path) {
  const db = new DatabaseSync(path);
  db.exec('PRAGMA journal_mode = WAL');
  db.exec('PRAGMA foreign_keys = ON');
  db.exec(SCHEMA);

  const stmt = {
    insert: db.prepare(
      `INSERT INTO orders (id, days, kopecks, telegram, email) VALUES (?, ?, ?, ?, ?)`),
    setPayment: db.prepare(
      `UPDATE orders SET payment_id = ?, updated_at = datetime('now') WHERE id = ?`),
    byId: db.prepare(`SELECT * FROM orders WHERE id = ?`),
    byPayment: db.prepare(`SELECT * FROM orders WHERE payment_id = ?`),
    setStatus: db.prepare(
      `UPDATE orders SET status = ?, updated_at = datetime('now') WHERE id = ?`),
    markFulfilled: db.prepare(
      `UPDATE orders SET fulfilled_at = datetime('now'), fulfil_error = NULL,
       updated_at = datetime('now') WHERE id = ?`),
    setFulfilError: db.prepare(
      `UPDATE orders SET fulfil_error = ?, updated_at = datetime('now') WHERE id = ?`),
    // Оплачено, но не выдано — деньги взяты, услуга нет. Требует вмешательства.
    stranded: db.prepare(
      `SELECT * FROM orders WHERE status = 'succeeded' AND fulfilled_at IS NULL
       ORDER BY created_at`)
  };

  return {
    db,
    create(order) {
      stmt.insert.run(order.id, order.days, order.kopecks, order.telegram, order.email || null);
      return stmt.byId.get(order.id);
    },
    attachPayment(id, paymentId) { stmt.setPayment.run(paymentId, id); },
    byId(id) { return stmt.byId.get(id); },
    byPayment(paymentId) { return stmt.byPayment.get(paymentId); },
    setStatus(id, status) { stmt.setStatus.run(status, id); },
    markFulfilled(id) { stmt.markFulfilled.run(id); },
    setFulfilError(id, message) { stmt.setFulfilError.run(String(message).slice(0, 500), id); },
    stranded() { return stmt.stranded.all(); },
    close() { db.close(); }
  };
}

module.exports = { open };
