"""Опрос статуса платежей.

Почему опрос, а не вебхук: вебхуку нужен принимающий адрес, открытый
наружу, а на этом сервере лишний публичный порт — не то, что стоит
заводить ради оплаты. Опрос обходится без входящих соединений вообще.

Правила, вокруг которых всё построено:

  - статус платежа берётся только из ответа API ЮKassa;
  - сумма из ответа сверяется с той, на которую выставляли счёт;
  - подписка выдаётся ровно один раз — заказ занимается атомарно;
  - если выдать не удалось, заказ остаётся оплаченным и невыданным,
    и об этом сообщается: деньги получены, услуга нет.
"""
import asyncio
import logging

from .yookassa import YooKassaError, rubles

log = logging.getLogger(__name__)


class PaymentPoller:
    def __init__(self, store, api, issue, *, notify_user=None, notify_admin=None,
                 interval=10, max_age=3600, stale_claim=300):
        """
        issue(order) — корутина бота, выдающая подписку. Должна бросить
            исключение, если выдать не удалось: молчаливый отказ здесь
            означал бы принятые деньги без доступа.
        notify_user(order, event) — необязательно: 'paid', 'canceled',
            'delayed'.
        notify_admin(text) — необязательно: тревога, когда выдача сорвалась.
        """
        self._store = store
        self._api = api
        self._issue = issue
        self._notify_user = notify_user
        self._notify_admin = notify_admin
        self._interval = interval
        self._max_age = max_age
        self._stale_claim = stale_claim
        self._task = None

    # ------------------------------------------------------------ запуск --

    async def start(self):
        if self._task is None:
            self._task = asyncio.create_task(self._loop())
        return self._task

    async def stop(self):
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self):
        while True:
            try:
                await self.tick()
            except Exception:                      # цикл не должен умирать
                log.exception('опрос платежей: непредвиденная ошибка')
            await asyncio.sleep(self._interval)

    # -------------------------------------------------------------- шаг ---

    async def tick(self):
        """Один проход. Возвращает число выданных подписок."""
        issued = 0
        for order in await self._store.to_poll(self._max_age):
            try:
                if await self._check(order):
                    issued += 1
            except YooKassaError as e:
                # Недоступность API — не повод что-то менять в заказе:
                # на следующем проходе спросим снова.
                log.warning('заказ %s: %s', order['id'], e)
            except Exception:
                log.exception('заказ %s: ошибка обработки', order['id'])
        return issued

    async def _check(self, order):
        # Оплату уже подтвердили раньше, осталась только выдача.
        if order['status'] == 'succeeded':
            return await self._deliver(order)

        payment = await self._api.get_payment(order['payment_id'])
        status = (payment or {}).get('status')

        if status == 'canceled':
            await self._store.set_status(order['id'], 'canceled')
            await self._tell_user(order, 'canceled')
            log.info('заказ %s: платёж отменён', order['id'])
            return False

        if status != 'succeeded' or not payment.get('paid'):
            return False

        # Сумма из API должна совпадать с той, на которую выставляли счёт.
        expected = rubles(order['kopecks'])
        amount = payment.get('amount') or {}
        if amount.get('value') != expected or amount.get('currency') != 'RUB':
            log.error('ВНИМАНИЕ: заказ %s: сумма не совпала '
                      '(ждали %s RUB, пришло %s %s)',
                      order['id'], expected,
                      amount.get('value'), amount.get('currency'))
            await self._alert(
                f'Заказ {order["id"]}: сумма платежа не совпала с заказом. '
                f'Ждали {expected} RUB, пришло {amount.get("value")} '
                f'{amount.get("currency")}. Подписка не выдана.')
            return False

        await self._store.set_status(order['id'], 'succeeded')
        return await self._deliver(await self._store.by_id(order['id']))

    async def _deliver(self, order):
        if order['issued_at']:
            return False
        if not await self._store.claim(order['id'], self._stale_claim):
            return False                       # заказ уже взял кто-то другой

        try:
            await self._issue(order)
        except Exception as e:
            await self._store.fail(order['id'], e)
            log.error('ВНИМАНИЕ: заказ %s оплачен, подписка не выдана: %s',
                      order['id'], e)
            await self._alert(
                f'Заказ {order["id"]} оплачен ({rubles(order["kopecks"])} ₽, '
                f'{order["days"]} дн., пользователь {order["user_id"]}), '
                f'но подписка не выдана: {e}\nВыдайте вручную.')
            await self._tell_user(order, 'delayed')
            return False

        await self._store.mark_issued(order['id'])
        log.info('заказ %s: подписка выдана (%s дн. → %s)',
                 order['id'], order['days'], order['user_id'])
        await self._tell_user(order, 'paid')
        return True

    # ------------------------------------------------------- уведомления --

    async def _tell_user(self, order, event):
        if self._notify_user is None:
            return
        try:
            await self._notify_user(order, event)
        except Exception:
            log.exception('заказ %s: не удалось написать покупателю', order['id'])

    async def _alert(self, text):
        if self._notify_admin is None:
            return
        try:
            await self._notify_admin(text)
        except Exception:
            log.exception('не удалось отправить тревогу администратору')
