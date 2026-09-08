#!/usr/bin/env python3
"""Достаёт вписанные в config.py значения и раскладывает их по строкам .env.

Файл не импортируется, а разбирается как текст (ast): побочных эффектов нет,
бот при этом продолжает работать. Значения печатаются только в файл, в вывод
идут одни имена — чтобы их можно было показать, не показывая сами значения.

    sudo python3 extract-secrets.py /opt/tg-bot/config.py /opt/tg-bot/.env.new
"""
import ast
import pathlib
import re
import sys

SRC = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else '/opt/tg-bot/config.py')
OUT = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else '/opt/tg-bot/.env.new')

# Как называть переменную окружения для каждого сервера.
PREFIX = {'finland': 'HIDDIFY_FI', 'netherlands': 'HIDDIFY_NL'}
FIELDS = ['base_url', 'proxy_path', 'proxy_path_admin', 'admin_uuid']

def literal(node):
    """literal_eval, дополнительно понимающий "текст".strip().

    PAYMENT_TEXT записан именно так, и без этого он бы не разобрался.
    """
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in ('strip', 'lstrip', 'rstrip') and not node.args):
        return getattr(ast.literal_eval(node.func.value), node.func.attr)()
    return ast.literal_eval(node)


tree = ast.parse(SRC.read_text(encoding='utf-8'))

consts, servers = {}, None
for node in tree.body:
    if not (isinstance(node, ast.Assign) and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)):
        continue
    name = node.targets[0].id
    if name == 'HIDDIFY_SERVERS':
        servers = node.value
        continue
    try:
        consts[name] = literal(node.value)
    except Exception:
        pass          # выражения вроде int(os.getenv(...)) нам не нужны

lines, names = [], []


def put(env_name, value):
    if value in (None, ''):
        return
    lines.append(f'{env_name}={value}')
    names.append(env_name)


# Адрес сведённой подписки был вписан прямо в код.
put('MERGED_SUBSCRIPTION_URL', consts.get('MERGED_SUBSCRIPTION_URL'))

# Реквизиты перевода: покупатель их видит, но в репозитории им не место.
codes = re.findall(r'<code>(.*?)</code>', consts.get('PAYMENT_TEXT', ''), re.S)
if len(codes) >= 1:
    put('PAYMENT_SBP_PHONE', codes[0].strip())
if len(codes) >= 2:
    put('PAYMENT_CARD', codes[1].strip())

if servers is None:
    sys.exit('В config.py не найден HIDDIFY_SERVERS — остановился, ничего не написав.')

for key_node, val_node in zip(servers.keys, servers.values):
    key = consts.get(key_node.id) if isinstance(key_node, ast.Name) \
        else ast.literal_eval(key_node)
    prefix = PREFIX.get(key)
    if prefix is None:
        sys.exit(f'Незнакомый сервер «{key}» — остановился, ничего не написав.')
    server = ast.literal_eval(val_node)
    for field in FIELDS:
        if field not in server:
            sys.exit(f'У сервера «{key}» нет поля «{field}» — остановился.')
        put(f'{prefix}_{field.upper()}', server[field])

OUT.write_text('\n'.join(lines) + '\n', encoding='utf-8')
OUT.chmod(0o600)

print(f'Записано в {OUT} ({len(lines)} строк). Имена переменных:')
for n in names:
    print('   ', n)
print('\nЗначения в вывод не печатались. Посмотреть их:  sudo cat', OUT)
