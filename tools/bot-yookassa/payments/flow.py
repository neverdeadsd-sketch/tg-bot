"""Создание платежа: заказ в базе, платёж в ЮKassa, ссылка на оплату."""
import uuid

from .yookassa import rubles


async def create_order(store, api, *, user_id, days, prices, return_url,
                       title='Доступ к сервису HollVPN, {days} дней',
                       metadata=None):
    """Заводит заказ и платёж, возвращает (order_id, confirmation_url).

    Сумма берётся из prices по числу дней, а не приходит откуда-то ещё:
    цену, названную покупателем, можно подменить, цену из таблицы — нет.

    prices: {30: 199, 90: 499, ...} — рубли, как в config.PRICES.
    """
    if days not in prices:
        raise ValueError(f'Неизвестный срок подписки: {days}')

    kopecks = int(round(prices[days] * 100))
    order_id = str(uuid.uuid4())
    await store.create(order_id, user_id, days, kopecks)

    payment = await api.create_payment(
        order_id=order_id,
        kopecks=kopecks,
        description=title.format(days=days),
        return_url=return_url,
        metadata=dict(metadata or {}, user_id=str(user_id), days=str(days)),
    )

    payment_id = (payment or {}).get('id')
    if payment_id:
        await store.attach_payment(order_id, payment_id)

    url = ((payment or {}).get('confirmation') or {}).get('confirmation_url')
    if not url:
        raise RuntimeError('ЮKassa не вернула ссылку на оплату')

    return order_id, url


def price_kopecks(prices, days):
    return int(round(prices[days] * 100))


__all__ = ['create_order', 'price_kopecks', 'rubles']
