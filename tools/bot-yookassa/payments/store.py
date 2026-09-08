"""Хранилище платежей. Отдельная таблица в той же базе, что у бота.

Суммы хранятся в копейках целым числом: рубли с копейками в float — это
способ однажды недосчитаться копейки и не понять почему.

Ключевое здесь — «выдать ровно один раз». Между «оплата подтверждена»
и «подписка выдана» может случиться перезапуск, второе уведомление,
второй проход опроса. Поэтому выдача занимается атомарно: claim() меняет
строку только если её ещё никто не занял, и только тот, кому это удалось,
идёт выдавать.
"""
import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS yk_payments (
  id          TEXT PRIMARY KEY,
  payment_id  TEXT UNIQUE,
  user_id     INTEGER NOT NULL,
  days        INTEGER NOT NULL,
  kopecks     INTEGER NOT NULL CHECK (kopecks > 0),
  status      TEXT NOT NULL DEFAULT 'pending'
              CHECK (status IN ('pending','succeeded','canceled')),
  claimed_at  TEXT,
  issued_at   TEXT,
  error       TEXT,
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS yk_payments_payment ON yk_payments(payment_id);
CREATE INDEX IF NOT EXISTS yk_payments_pending ON yk_payments(status, created_at);
"""


class PaymentStore:
    def __init__(self, path):
        self._path = path
        self._db = None

    async def open(self):
        self._db = await aiosqlite.connect(self._path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute('PRAGMA journal_mode = WAL')
        await self._db.executescript(SCHEMA)
        await self._db.commit()
        return self

    async def close(self):
        if self._db is not None:
            await self._db.close()
            self._db = None

    # ------------------------------------------------------------ запись --

    async def create(self, order_id, user_id, days, kopecks):
        await self._db.execute(
            'INSERT INTO yk_payments (id, user_id, days, kopecks) VALUES (?, ?, ?, ?)',
            (order_id, user_id, days, kopecks))
        await self._db.commit()
        return await self.by_id(order_id)

    async def attach_payment(self, order_id, payment_id):
        """Связывает заказ с платежом ЮKassa.

        Платёж к этому моменту уже создан, поэтому ошибка записи не должна
        ронять покупку: опрос найдёт заказ по metadata.order_id и без этой
        связи. Возвращает False, чтобы вызывающий написал в лог.
        """
        try:
            await self._db.execute(
                "UPDATE yk_payments SET payment_id = ?, updated_at = datetime('now')"
                ' WHERE id = ?', (payment_id, order_id))
            await self._db.commit()
            return True
        except aiosqlite.Error:
            return False

    async def set_status(self, order_id, status):
        await self._db.execute(
            "UPDATE yk_payments SET status = ?, updated_at = datetime('now')"
            ' WHERE id = ?', (status, order_id))
        await self._db.commit()

    async def claim(self, order_id, stale_seconds=300):
        """Занять заказ под выдачу. True — занять удалось, выдавать вам.

        Занять можно только незанятый или занятый давно (значит, тот, кто
        занял, до выдачи не дошёл — упал или был перезапущен).
        """
        cur = await self._db.execute(
            "UPDATE yk_payments SET claimed_at = datetime('now'),"
            "       updated_at = datetime('now')"
            ' WHERE id = ? AND issued_at IS NULL'
            '   AND (claimed_at IS NULL'
            "        OR claimed_at <= datetime('now', ?))",
            (order_id, f'-{int(stale_seconds)} seconds'))
        await self._db.commit()
        return cur.rowcount == 1

    async def mark_issued(self, order_id):
        await self._db.execute(
            "UPDATE yk_payments SET issued_at = datetime('now'), error = NULL,"
            "       updated_at = datetime('now') WHERE id = ?", (order_id,))
        await self._db.commit()

    async def fail(self, order_id, message):
        """Выдача не удалась: освобождаем заказ и записываем причину."""
        await self._db.execute(
            "UPDATE yk_payments SET claimed_at = NULL, error = ?,"
            "       updated_at = datetime('now') WHERE id = ?",
            (str(message)[:500], order_id))
        await self._db.commit()

    # ------------------------------------------------------------ чтение --

    async def by_id(self, order_id):
        async with self._db.execute(
                'SELECT * FROM yk_payments WHERE id = ?', (order_id,)) as cur:
            return await cur.fetchone()

    async def by_payment(self, payment_id):
        async with self._db.execute(
                'SELECT * FROM yk_payments WHERE payment_id = ?', (payment_id,)) as cur:
            return await cur.fetchone()

    async def to_poll(self, max_age_seconds):
        """Заказы, которые ещё имеет смысл опрашивать.

        Это ожидающие оплаты и те, что оплачены, но не выданы: вторые
        важнее — деньги уже получены.
        """
        async with self._db.execute(
                "SELECT * FROM yk_payments"
                " WHERE payment_id IS NOT NULL"
                "   AND (status = 'pending' OR (status = 'succeeded' AND issued_at IS NULL))"
                "   AND created_at > datetime('now', ?)"
                ' ORDER BY created_at',
                (f'-{int(max_age_seconds)} seconds',)) as cur:
            return await cur.fetchall()

    async def stranded(self):
        """Оплачено, но не выдано. Требует вмешательства человека."""
        async with self._db.execute(
                "SELECT * FROM yk_payments WHERE status = 'succeeded'"
                ' AND issued_at IS NULL ORDER BY created_at') as cur:
            return await cur.fetchall()
