#!/usr/bin/env python3
"""Ищет секреты, вписанные прямо в код.

    python3 find-secrets.py КАТАЛОГ [ФАЙЛ …]

Печатает, ГДЕ нашлось и КАК НАЗЫВАЕТСЯ, но никогда — что именно: вывод
этой проверки попадает в журналы и в переписку, и печатать там найденный
секрет значило бы разгласить его ровно тем, что его ищет.

Ищем двумя способами, потому что секреты бывают двух сортов.

Первый — узнаваемые по виду: токен бота, ключ ЮKassa, приватный ключ.
Их ловит шаблон.

Второй — неотличимые от любой другой строки: путь к панели Hiddify,
uuid администратора, номер карты. Шаблоном их не поймать, зато их
выдаёт имя рядом: значение, вписанное в поле с именем proxy_path или
admin_uuid, — секрет, как бы оно ни выглядело. Именно на этом сорте
первая версия проверки и промахнулась.
"""
import ast
import pathlib
import re
import sys

# Имена, рядом с которыми вписанное значение — секрет.
SECRET_NAME = re.compile(
    r'token|secret|password|passwd|api[_-]?key|private[_-]?key|'
    r'proxy[_-]?path|admin[_-]?uuid|uuid|credential|auth|card|'
    r'phone|sbp|account|iban|cvv',
    re.I,
)

# Имена, которые похожи на секретные, но секретами не являются.
NOT_SECRET = re.compile(r'^(shop_id|username|user|login|token_url|auth_url)$', re.I)

# Значения, узнаваемые по виду.
BY_LOOK = [
    (re.compile(r'\b\d{8,10}:AA[A-Za-z0-9_-]{30,}'),   'токен бота Telegram'),
    (re.compile(r'\b(?:live|test)_[A-Za-z0-9_-]{30,}'), 'ключ ЮKassa'),
    (re.compile(r'\bghp_[A-Za-z0-9]{30,}'),             'токен GitHub'),
    (re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----'), 'приватный ключ'),
    (re.compile(r'\b(?:\d[ -]?){15,18}\b'),             'похоже на номер карты'),
]

# Значения, которые ничего не раскрывают, даже если стоят в секретном поле.
HARMLESS = re.compile(r'^\s*$|^(?:x+|X+|\.{3}|-+|_+|None|null|true|false|'
                      r'ваш[_а-я]*|your[_a-z]*|change[_-]?me|example|test|'
                      r'placeholder|todo|секрет|token|key)\s*$', re.I)


def by_look(text):
    for pattern, what in BY_LOOK:
        if pattern.search(text):
            return what
    return None


def suspicious_name(name):
    name = str(name)
    return bool(SECRET_NAME.search(name)) and not NOT_SECRET.match(name)


def check_python(path, report):
    try:
        tree = ast.parse(path.read_text(encoding='utf-8'))
    except (SyntaxError, UnicodeDecodeError):
        return

    def value_is_literal(node):
        return isinstance(node, ast.Constant) and isinstance(node.value, str)

    for node in ast.walk(tree):
        # ИМЯ = "значение"
        if isinstance(node, ast.Assign) and value_is_literal(node.value):
            for target in node.targets:
                name = getattr(target, 'id', None) or getattr(target, 'attr', None)
                if name and suspicious_name(name) and not HARMLESS.match(node.value.value):
                    report(path, node.lineno, f'значение вписано в {name}')
        # {"имя": "значение"}
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if (isinstance(key, ast.Constant) and isinstance(key.value, str)
                        and value_is_literal(value)
                        and suspicious_name(key.value)
                        and not HARMLESS.match(value.value)):
                    report(path, key.lineno, f'значение вписано в "{key.value}"')
        # ИМЯ: тип = "значение"
        elif isinstance(node, ast.AnnAssign) and node.value is not None \
                and value_is_literal(node.value):
            name = getattr(node.target, 'id', None)
            if name and suspicious_name(name) and not HARMLESS.match(node.value.value):
                report(path, node.lineno, f'значение вписано в {name}')


def check_text(path, report):
    try:
        text = path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return
    for number, line in enumerate(text.splitlines(), 1):
        what = by_look(line)
        if what:
            report(path, number, what)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    root = pathlib.Path(sys.argv[1])
    paths = [root / f for f in sys.argv[2:]] if len(sys.argv) > 2 else [
        p for p in root.rglob('*')
        if p.is_file() and not {'.git', '__pycache__', 'venv', '.venv'} & set(p.parts)
    ]

    found = []

    def report(path, line, what):
        try:
            shown = path.relative_to(root)
        except ValueError:
            shown = path
        found.append(f'  {shown}:{line} — {what}')

    for path in paths:
        if not path.is_file():
            continue
        if path.suffix == '.py':
            check_python(path, report)
        check_text(path, report)

    if not found:
        print('Вписанных секретов не нашлось.')
        return 0

    print('Похоже на секреты, вписанные прямо в код:')
    for line in sorted(set(found)):
        print(line)
    print()
    print('Сами значения не печатаются намеренно. Проверьте эти места:')
    print('секретам место в .env, а не в файлах, которые уезжают в репозиторий.')
    return 1


if __name__ == '__main__':
    sys.exit(main())
