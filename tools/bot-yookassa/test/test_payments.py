"""Проверяем не «работает ли счастливый путь», а то, чем в платежах ломают:
подменённая сумма, повторная выдача, сорванная выдача, недоступное API
и гонка двух проходов опроса за один и тот же заказ.

    cd tools/bot-yookassa && python3 -m unittest discover -s test -v
"""
import asyncio
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from payments import PaymentPoller, PaymentStore, create_order      # noqa: E402
from payments.yookassa import (                                     # noqa: E402
    YooKassaError, payment_body, rubles,
)

PRICES = {30: 199, 90: 499, 180: 899, 365: 1499}
RETURN_URL = 'https://t.me/hollvpn_bot'


class FakeApi:
    """Подменяет ЮKassa. Платежи заводит сам, статус меняет тест."""

    def __init__(self, fail_get=False):
        self.payments = {}
        self.created = []
        self.fail_get = fail_get

    async def create_payment(self, order_id, kopecks, description, return_url,
                             metadata=None):
        # Тело собираем той же функцией, что и настоящий клиент, иначе
        # тест проверял бы подмену, а не то, что уйдёт в ЮKassa.
        self.created.append(payment_body(order_id, kopecks, description,
                                         return_url, metadata))
        pid = f'pay_{len(self.created)}'
        self.payments[pid] = {
            'id': pid, 'status': 'pending', 'paid': False,
            'amount': {'value': rubles(kopecks), 'currency': 'RUB'},
            'metadata': dict(metadata or {}, order_id=order_id),
        }
        return {'id': pid, 'status': 'pending',
                'confirmation': {'confirmation_url': f'https://yoomoney.ru/{pid}'}}

    async def get_payment(self, payment_id):
        if self.fail_get:
            raise YooKassaError('ЮKassa недоступна')
        return self.payments[payment_id]

    def succeed(self, pid):
        self.payments[pid].update(status='succeeded', paid=True)

    def cancel(self, pid):
        self.payments[pid]['status'] = 'canceled'


class Base(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = await PaymentStore(':memory:').open()
        self.api = FakeApi()
        self.issued = []
        self.alerts = []
        self.told = []

    async def asyncTearDown(self):
        await self.store.close()

    def poller(self, issue=None, **kw):
        async def default_issue(order):
            self.issued.append(order['id'])

        async def alert(text):
            self.alerts.append(text)

        async def tell(order, event):
            self.told.append((order['id'], event))

        return PaymentPoller(self.store, self.api, issue or default_issue,
                             notify_admin=alert, notify_user=tell, **kw)

    async def order(self, days=90, user_id=777):
        return await create_order(self.store, self.api, user_id=user_id,
                                  days=days, prices=PRICES,
                                  return_url=RETURN_URL)


class TestAmount(unittest.TestCase):
    def test_kopecks_to_rubles(self):
        self.assertEqual(rubles(19900), '199.00')
        self.assertEqual(rubles(149900), '1499.00')
        self.assertEqual(rubles(5), '0.05')
        self.assertEqual(rubles(100), '1.00')


class TestPaymentBody(unittest.TestCase):
    """Ключ идемпотентности и сумма — то место, где ошибка стоит денег."""

    def test_body(self):
        body = payment_body('order-1', 89900, 'Доступ, 180 дней',
                            RETURN_URL, {'user_id': '5'})
        self.assertEqual(body['amount'], {'value': '899.00', 'currency': 'RUB'})
        self.assertEqual(body['confirmation'],
                         {'type': 'redirect', 'return_url': RETURN_URL})
        # order_id в метаданных — по нему опрос находит заказ, даже если
        # связь заказа с платежом не записалась.
        self.assertEqual(body['metadata'], {'user_id': '5', 'order_id': 'order-1'})
        self.assertIs(body['capture'], True)

    def test_metadata_cannot_override_order_id(self):
        body = payment_body('настоящий', 19900, 'x', RETURN_URL,
                            {'order_id': 'подменённый'})
        self.assertEqual(body['metadata']['order_id'], 'настоящий')


class TestCreate(Base):
    async def test_amount_comes_from_price_table(self):
        order_id, url = await self.order(days=90)
        self.assertTrue(url.startswith('https://yoomoney.ru/'))
        sent = self.api.created[0]
        self.assertEqual(sent['amount'], {'value': '499.00', 'currency': 'RUB'})
        self.assertEqual(sent['metadata']['order_id'], order_id)
        self.assertEqual(sent['metadata']['days'], '90')
        self.assertTrue(sent['capture'])

        row = await self.store.by_id(order_id)
        self.assertEqual(row['kopecks'], 49900)
        self.assertEqual(row['status'], 'pending')
        self.assertEqual(row['payment_id'], 'pay_1')

    async def test_unknown_term_refused(self):
        with self.assertRaises(ValueError):
            await create_order(self.store, self.api, user_id=1, days=7,
                               prices=PRICES, return_url=RETURN_URL)
        self.assertEqual(self.api.created, [])


class TestPoll(Base):
    async def test_pending_stays_pending(self):
        order_id, _ = await self.order()
        self.assertEqual(await self.poller().tick(), 0)
        self.assertEqual(self.issued, [])
        self.assertEqual((await self.store.by_id(order_id))['status'], 'pending')

    async def test_paid_order_is_issued_once(self):
        order_id, _ = await self.order(days=30)
        self.api.succeed('pay_1')
        p = self.poller()

        self.assertEqual(await p.tick(), 1)
        self.assertEqual(self.issued, [order_id])
        row = await self.store.by_id(order_id)
        self.assertEqual(row['status'], 'succeeded')
        self.assertIsNotNone(row['issued_at'])
        self.assertIn((order_id, 'paid'), self.told)

        # Второй проход не должен выдать повторно.
        self.assertEqual(await p.tick(), 0)
        self.assertEqual(self.issued, [order_id])

    async def test_amount_mismatch_is_not_issued(self):
        order_id, _ = await self.order(days=365)
        self.api.succeed('pay_1')
        self.api.payments['pay_1']['amount'] = {'value': '1.00', 'currency': 'RUB'}
        # Счёт выставляли на 1499 ₽, «оплачен» пришёл на рубль.

        self.assertEqual(await self.poller().tick(), 0)
        self.assertEqual(self.issued, [])
        self.assertTrue(any('сумма' in a.lower() for a in self.alerts))
        self.assertEqual((await self.store.by_id(order_id))['status'], 'pending')

    async def test_wrong_currency_is_not_issued(self):
        await self.order(days=30)
        self.api.succeed('pay_1')
        self.api.payments['pay_1']['amount'] = {'value': '199.00', 'currency': 'USD'}
        self.assertEqual(await self.poller().tick(), 0)
        self.assertEqual(self.issued, [])

    async def test_canceled_payment(self):
        order_id, _ = await self.order()
        self.api.cancel('pay_1')
        await self.poller().tick()
        self.assertEqual((await self.store.by_id(order_id))['status'], 'canceled')
        self.assertIn((order_id, 'canceled'), self.told)
        self.assertEqual(self.issued, [])

    async def test_api_down_changes_nothing(self):
        order_id, _ = await self.order()
        self.api.fail_get = True
        self.assertEqual(await self.poller().tick(), 0)
        row = await self.store.by_id(order_id)
        self.assertEqual(row['status'], 'pending')
        self.assertIsNone(row['issued_at'])

        # Связь восстановилась — заказ доходит до выдачи.
        self.api.fail_get = False
        self.api.succeed('pay_1')
        self.assertEqual(await self.poller().tick(), 1)


class TestDeliveryFailure(Base):
    async def test_failed_issue_leaves_order_paid_and_alerts(self):
        async def broken(order):
            raise RuntimeError('панель не ответила')

        order_id, _ = await self.order(days=180)
        self.api.succeed('pay_1')
        p = self.poller(issue=broken)

        self.assertEqual(await p.tick(), 0)
        row = await self.store.by_id(order_id)
        self.assertEqual(row['status'], 'succeeded')
        self.assertIsNone(row['issued_at'])
        self.assertIn('панель не ответила', row['error'])
        self.assertIsNone(row['claimed_at'])          # заказ освобождён
        self.assertTrue(any('не выдана' in a for a in self.alerts))
        self.assertIn((order_id, 'delayed'), self.told)

        # Такой заказ виден как требующий вмешательства.
        self.assertEqual([r['id'] for r in await self.store.stranded()], [order_id])

    async def test_retry_after_failure_succeeds(self):
        calls = []

        async def flaky(order):
            calls.append(order['id'])
            if len(calls) == 1:
                raise RuntimeError('временная ошибка')

        order_id, _ = await self.order()
        self.api.succeed('pay_1')
        p = self.poller(issue=flaky)

        self.assertEqual(await p.tick(), 0)
        self.assertEqual(await p.tick(), 1)
        self.assertEqual(len(calls), 2)
        self.assertIsNotNone((await self.store.by_id(order_id))['issued_at'])
        self.assertEqual(await self.store.stranded(), [])


class TestClaim(Base):
    async def test_two_passes_at_once_issue_once(self):
        slow_started = asyncio.Event()

        async def slow(order):
            slow_started.set()
            await asyncio.sleep(0.05)
            self.issued.append(order['id'])

        order_id, _ = await self.order()
        self.api.succeed('pay_1')
        p = self.poller(issue=slow)

        first, second = await asyncio.gather(p.tick(), p.tick())
        self.assertEqual(sorted([first, second]), [0, 1])
        self.assertEqual(self.issued, [order_id])

    async def test_stale_claim_can_be_taken_again(self):
        order_id, _ = await self.order()
        # Заказ занят, но выдача не дошла — например, бота перезапустили.
        self.assertTrue(await self.store.claim(order_id))
        self.assertFalse(await self.store.claim(order_id))
        # С точки зрения «занято давно» — можно занять снова.
        self.assertTrue(await self.store.claim(order_id, stale_seconds=0))

    async def test_issued_order_cannot_be_claimed(self):
        order_id, _ = await self.order()
        await self.store.mark_issued(order_id)
        self.assertFalse(await self.store.claim(order_id, stale_seconds=0))


if __name__ == '__main__':
    unittest.main()
