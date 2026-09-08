-- Схема базы заказов для Cloudflare D1.
--
-- D1 — это SQLite, поэтому таблица та же, что у серверного варианта.
-- Суммы в копейках целым числом: рубли с копейками в double — это способ
-- однажды недосчитаться копейки и не понять почему.

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

-- Оплачено, но не выдано: деньги взяты, услуга нет. Этот индекс —
-- для запроса, который такие заказы находит.
CREATE INDEX IF NOT EXISTS orders_unfulfilled
  ON orders(status, fulfilled_at) WHERE status = 'succeeded' AND fulfilled_at IS NULL;

-- Ограничение частоты создания заказов.
--
-- Ключ — не адрес, а его хеш: сервис про приватность не должен вести
-- список адресов своих покупателей. По хешу узнать адрес нельзя, а для
-- «этот же посетитель за последний час» его достаточно. Строки живут
-- один час и удаляются.
CREATE TABLE IF NOT EXISTS throttle (
  key       TEXT PRIMARY KEY,
  hits      INTEGER NOT NULL DEFAULT 0,
  window_at INTEGER NOT NULL
);
