#!/usr/bin/env python3
"""Сводит подписки двух панелей Hiddify в один файл.

Чем отличается от прежнего скрипта:

  - не знает названий протоколов. Прежний искал строки по приметам
    вроде «ss:// и адрес» или «vless:// и grpc»; панели перенастроили
    на trojan, приметы перестали совпадать, и подписка молча стала
    пустой. Здесь берутся все строки вида «схема://», какими бы они
    ни были;
  - не молчит. Пустой источник, недоступная панель, нулевой итог —
    это ошибка с внятным текстом и ненулевым кодом возврата, а не
    тихо перезаписанный пустой файл;
  - не содержит ссылок с ключами. Адреса подписок читаются из файла
    рядом, который в репозиторий не попадает.

    sudo python3 merge_sub.py
"""
import base64
import binascii
import os
import pathlib
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

CONF = pathlib.Path(os.environ.get('MERGE_SUB_ENV', '/root/.merge_sub.env'))
OUT = pathlib.Path(os.environ.get('MERGE_SUB_OUT', '/var/www/html/merged/sub.txt'))
TIMEOUT = 20

SCHEME = ('://',)


def die(message):
    print(f'merge_sub: {message}', file=sys.stderr)
    raise SystemExit(1)


def read_conf():
    """Источники берём из файла: в скрипте им не место — там ключи."""
    if not CONF.exists():
        die(f'нет файла {CONF}. Заведите его по образцу merge_sub.env.example')
    conf = {}
    for line in CONF.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        conf[key.strip()] = value.strip()
    return conf


def fetch(url, insecure):
    ctx = ssl.create_default_context()
    if insecure:
        # Панель по IP-адресу отдаёт сертификат не на этот адрес.
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT, context=ctx) as r:
            return r.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        die(f'панель ответила {e.code} на {mask(url)}')
    except Exception as e:                       # сеть, TLS, таймаут
        die(f'не удалось получить {mask(url)}: {e}')


def mask(url):
    """Адрес для сообщения об ошибке — без пути, в котором ключи."""
    p = urllib.parse.urlsplit(url)
    return f'{p.scheme}://{p.netloc}/…'


def links(text):
    """Строки подписки. Содержимое бывает и base64, и открытым текстом."""
    if '://' not in text:
        try:
            text = base64.b64decode(text + '=' * (-len(text) % 4)).decode('utf-8', 'replace')
        except (binascii.Error, ValueError):
            pass
    out = []
    for line in text.splitlines():
        line = line.strip()
        if '://' in line and not line.startswith('#'):
            out.append(line)
    return out


def rename(line, label):
    """Имя узла — то, что клиент показывает в списке."""
    return f"{line.split('#')[0]}#{urllib.parse.quote(label)}"


def check_url(prefix, url):
    """Отличить незаполненный образец от настоящего адреса.

    Иначе первым сообщением будет что-нибудь про кодировку ASCII —
    формально верное и совершенно бесполезное.
    """
    if not url.startswith(('http://', 'https://')):
        die(f'{prefix}_URL не похож на адрес: должен начинаться с https://')
    host = urllib.parse.urlsplit(url).netloc
    if not host.isascii() or any(w in url for w in ('АДРЕС', 'ПУТЬ', 'UUID')):
        die(f'{prefix}_URL — это заполнитель из образца, а не настоящий адрес.\n'
            f'  Перенести адреса из старого скрипта:\n'
            f'    sudo bash /opt/hollvpn/tools/merge-sub/init-env.sh')


def main():
    conf = read_conf()
    insecure = conf.get('INSECURE', '0') == '1'

    sources = []
    for prefix in ('NL', 'FI'):
        url = conf.get(f'{prefix}_URL')
        if not url:
            die(f'в {CONF} не задан {prefix}_URL')
        check_url(prefix, url)
        sources.append((prefix, url, conf.get(f'{prefix}_NAME', prefix)))

    lines = []
    for prefix, url, label in sources:
        found = links(fetch(url, insecure))
        if not found:
            die(f'{prefix}: панель ответила, но ни одной ссылки в ответе нет. '
                f'Подписка не тронута.')
        print(f'  {prefix}: {len(found)} ссыл. → «{label}»')
        for i, line in enumerate(found, 1):
            lines.append(rename(line, label if len(found) == 1 else f'{label} {i}'))

    if not lines:
        die('итог пуст — файл не переписан')

    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = base64.b64encode('\n'.join(lines).encode('utf-8')).decode('ascii')

    # Пишем через временный файл: клиент, обновляющий подписку в этот
    # момент, не должен увидеть половину.
    tmp = OUT.with_suffix('.tmp')
    tmp.write_text(payload, encoding='utf-8')
    tmp.replace(OUT)
    print(f'  записано {len(lines)} ссыл. в {OUT}')


if __name__ == '__main__':
    main()
