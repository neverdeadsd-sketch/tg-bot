#!/usr/bin/env python3
"""Показывает, куда в боте подключается оплата.

    sudo python3 report-hooks.py /opt/tg-bot

Печатает только каркас: имена функций, их аргументы, декораторы обработчиков
и список вызываемых имён. Тела функций, строки и любые значения не выводятся
вовсе — поэтому вывод можно показать кому угодно, не вычитывая его построчно
на предмет токенов. Для подключения оплаты этого достаточно: нужно знать, как
называется выдача подписки и какой обработчик ведёт покупку.

Файлы разбираются как текст (ast), ничего не импортируется: бот при этом
продолжает работать.
"""
import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else '/opt/tg-bot')

# Что ищем. Первая группа — выдача подписки: ей оплата передаёт заказ.
# Вторая — покупка: туда встаёт кнопка «оплатить картой».
WANTED = {
    'выдача подписки': (
        'hiddify', 'panel', 'subscription', 'sub_link', 'sublink', 'issue',
        'add_user', 'create_user', 'new_user', 'grant', 'prolong', 'extend',
        'give', 'activate', 'выдач', 'подпис', 'продл',
    ),
    'покупка и оплата': (
        'price', 'prices', 'buy', 'pay', 'paid', 'payment', 'invoice',
        'checkout', 'tariff', 'plan', 'days', 'term', 'kassa', 'yoo',
        'stars', 'crypto', 'card', 'оплат', 'плат', 'куп', 'тариф',
        'срок', 'карт', 'счет', 'счёт', 'юкасс',
    ),
}

# На случай, если значение всё же попадёт в декоратор: длинные бессмысленные
# строки не печатаем. Дешевле перестраховаться, чем объяснять утечку.
SECRETISH = re.compile(r'[A-Za-z0-9_\-]{24,}|\d{6,}:[A-Za-z0-9_\-]{20,}')


def hide(text):
    return SECRETISH.sub('…', text)


def called_names(node):
    """Имена, которые функция вызывает. Не значения — только имена."""
    names = []
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        f = sub.func
        if isinstance(f, ast.Name):
            names.append(f.id)
        elif isinstance(f, ast.Attribute):
            names.append(f.attr)
    seen, out = set(), []
    for n in names:
        if n not in seen and not n.startswith('_'):
            seen.add(n)
            out.append(n)
    return out


def signature(node):
    a = node.args
    parts = [x.arg for x in (*a.posonlyargs, *a.args)]
    if a.vararg:
        parts.append('*' + a.vararg.arg)
    parts += [x.arg for x in a.kwonlyargs]
    if a.kwarg:
        parts.append('**' + a.kwarg.arg)
    kind = 'async def' if isinstance(node, ast.AsyncFunctionDef) else 'def'
    return f'{kind} {node.name}({", ".join(parts)})'


def decorators(node):
    out = []
    for d in node.decorator_list:
        try:
            out.append(hide(ast.unparse(d)))
        except Exception:
            pass
    return out


def main():
    if not ROOT.is_dir():
        sys.exit(f'Нет каталога {ROOT}. Укажите путь к боту первым аргументом.')

    def ours(path):
        """Наш же модуль оплаты, если он уже установлен.

        Он весь про оплату и подписки, поэтому иначе забивает собой отчёт,
        в котором ищут код бота, а не наш.
        """
        d = path.parent
        return (d.name == 'payments'
                and (d / 'yookassa.py').is_file() and (d / 'poller.py').is_file())

    files = sorted(p for p in ROOT.rglob('*.py')
                   if '.venv' not in p.parts and 'site-packages' not in p.parts
                   and '__pycache__' not in p.parts and 'venv' not in p.parts
                   and not ours(p))
    if not files:
        sys.exit(f'В {ROOT} нет файлов .py — это точно каталог бота?')

    print(f'Каталог: {ROOT}')
    print(f'Файлов .py: {len(files)}')
    print()

    found = {k: [] for k in WANTED}
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'))
        except (SyntaxError, UnicodeDecodeError) as e:
            print(f'  {path}: не разобрался ({type(e).__name__})')
            continue
        rel = path.relative_to(ROOT)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            haystack = ' '.join((
                node.name,
                signature(node),          # имена аргументов тоже говорящие
                ' '.join(called_names(node)),
                ' '.join(decorators(node)),
            )).lower()
            for group, words in WANTED.items():
                if any(w in haystack for w in words):
                    found[group].append((rel, node))

    for group, items in found.items():
        print(f'=== {group} ===')
        if not items:
            print('  ничего не нашлось')
        for rel, node in items:
            print(f'  {rel}:{node.lineno}')
            for d in decorators(node):
                print(f'    @{d}')
            print(f'    {signature(node)}')
            calls = called_names(node)
            if calls:
                print(f'    вызывает: {", ".join(calls[:20])}')
        print()

    # Имена верхнего уровня в config.py: по ним видно, что уже настроено.
    cfg = ROOT / 'config.py'
    if cfg.is_file():
        print('=== имена в config.py (только имена) ===')
        try:
            tree = ast.parse(cfg.read_text(encoding='utf-8'))
        except SyntaxError:
            print('  не разобрался')
        else:
            names = [t.id for n in tree.body
                     if isinstance(n, ast.Assign)
                     for t in n.targets if isinstance(t, ast.Name)]
            print('  ' + ', '.join(names))


if __name__ == '__main__':
    main()
