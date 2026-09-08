"""Клиент API ЮKassa. Ровно два вызова: создать платёж и прочитать платёж.

Чтение — не роскошь. Узнать, что платёж прошёл, можно только у самой
ЮKassa: всё остальное приходит из сети и доверять ему нельзя.

Секретный ключ живёт только здесь и в заголовке Authorization. Он не
попадает ни в логи, ни в текст ошибок: описание ошибки берётся из полей
code и description ответа, а не из заголовков запроса.
"""
import asyncio
import base64
import json
import logging

import aiohttp

log = logging.getLogger(__name__)

DEFAULT_API = 'https://api.yookassa.ru/v3'
TIMEOUT = aiohttp.ClientTimeout(total=15)


class YooKassaError(Exception):
    """Ошибка обращения к API. status = None, если до API не дошли."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class YooKassa:
    def __init__(self, shop_id, secret_key, api=DEFAULT_API, session=None):
        if not shop_id or not secret_key:
            raise ValueError('Не заданы shop_id или secret_key ЮKassa')
        self._auth = 'Basic ' + base64.b64encode(
            f'{shop_id}:{secret_key}'.encode()).decode()
        self._api = api.rstrip('/')
        self._session = session

    async def _request(self, method, path, body=None, idempotence_key=None):
        headers = {'Authorization': self._auth, 'Content-Type': 'application/json'}
        if idempotence_key:
            headers['Idempotence-Key'] = idempotence_key

        session = self._session or aiohttp.ClientSession(timeout=TIMEOUT)
        try:
            async with session.request(
                method, self._api + path, headers=headers,
                data=json.dumps(body) if body is not None else None,
            ) as res:
                text = await res.text()
                try:
                    data = json.loads(text) if text else None
                except ValueError:
                    data = None

                if res.status >= 400:
                    detail = ''
                    if isinstance(data, dict):
                        detail = ' '.join(filter(None, [
                            str(data.get('code', '')), str(data.get('description', ''))
                        ])).strip()
                    raise YooKassaError(
                        f'ЮKassa {method} {path} → {res.status}: {detail or text[:200]}',
                        status=res.status)
                return data
        except aiohttp.ClientError as e:
            raise YooKassaError(f'ЮKassa недоступна: {e}') from e
        except asyncio.TimeoutError as e:
            raise YooKassaError('ЮKassa не ответила за 15 секунд') from e
        finally:
            if self._session is None:
                await session.close()

    async def create_payment(self, order_id, kopecks, description, return_url,
                             metadata=None):
        """Создаёт платёж и возвращает ответ API.

        Idempotence-Key — идентификатор нашего заказа. Повторный запрос
        с тем же ключом возвращает тот же платёж, а не создаёт второй:
        пользователь, дважды нажавший кнопку, не заплатит дважды.
        """
        body = payment_body(order_id, kopecks, description, return_url, metadata)
        return await self._request('POST', '/payments', body,
                                   idempotence_key=order_id)

    async def get_payment(self, payment_id):
        return await self._request('GET', f'/payments/{payment_id}')


def payment_body(order_id, kopecks, description, return_url, metadata=None):
    """Тело запроса на создание платежа.

    Вынесено отдельно, потому что это то место, где ошибка стоит денег:
    сумма, валюта и order_id в метаданных. Чистая функция проверяется
    напрямую, без подмены HTTP.
    """
    return {
        'amount': {'value': rubles(kopecks), 'currency': 'RUB'},
        'capture': True,
        'confirmation': {'type': 'redirect', 'return_url': return_url},
        'description': description,
        'metadata': dict(metadata or {}, order_id=order_id),
    }


def rubles(kopecks):
    """Копейки в строку рублей, как их ждёт API: 19900 → '199.00'."""
    return f'{kopecks // 100}.{kopecks % 100:02d}'
