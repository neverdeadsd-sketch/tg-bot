# Убрать секреты из config.py бота

Одноразовая миграция. В `/opt/tg-bot/config.py` вписаны прямо в код пути
к панели Hiddify, uuid администратора и реквизиты перевода. Пока они там,
файл нельзя ни закоммитить, ни кому-то показать.

Скрипт переносит их в `.env`, а `config.py.new` — тот же файл, но читающий
всё из окружения. Значения при этом никуда не отправляются и не печатаются
в вывод: скрипт называет только имена переменных.

Проверено на копии этой структуры: новый `config.py` даёт **те же 13
значений**, что старый, и не запускается, если в `.env` чего-то не хватает.

## Порядок

Всё — на сервере, от root.

```bash
cd /opt/hollvpn && sudo git pull
```

**1. Резервная копия — до всего остального.**

```bash
sudo cp /opt/tg-bot/config.py /opt/tg-bot/config.py.orig
sudo cp /opt/tg-bot/.env      /opt/tg-bot/.env.orig
```

**2. Достать значения в отдельный файл.**

```bash
sudo python3 /opt/hollvpn/tools/bot-secrets/extract-secrets.py \
     /opt/tg-bot/config.py /opt/tg-bot/.env.new
```

Печатает список имён. Посмотреть, что получилось (это ваши секреты —
только для ваших глаз):

```bash
sudo cat /opt/tg-bot/.env.new
```

**3. Дописать их в .env.**

```bash
sudo sh -c 'printf "\n# перенесено из config.py\n" >> /opt/tg-bot/.env'
sudo sh -c 'cat /opt/tg-bot/.env.new >> /opt/tg-bot/.env'
sudo rm /opt/tg-bot/.env.new
```

**4. Заменить config.py.**

```bash
sudo cp /opt/hollvpn/tools/bot-secrets/config.py.new /opt/tg-bot/config.py
```

**5. Проверить, что значения не разъехались, — до перезапуска.**

```bash
cd /opt/tg-bot && sudo ./venv/bin/python3 -c "
import config
print('токен бота задан:', bool(config.BOT_TOKEN))
print('серверов:', len(config.HIDDIFY_SERVERS))
for name, s in config.HIDDIFY_SERVERS.items():
    print(' ', name, '->', s['base_url'], '| все поля на месте:',
          all(s.get(k) for k in ('proxy_path', 'proxy_path_admin', 'admin_uuid')))
print('реквизиты в тексте оплаты:', '<code>' in config.PAYMENT_TEXT)
"
```

Если вместо этого напечаталась ошибка со списком переменных — значит
что-то не перенеслось. Верните старый файл и напишите, что именно:

```bash
sudo cp /opt/tg-bot/config.py.orig /opt/tg-bot/config.py
```

**6. Перезапустить бота и убедиться, что он живой.**

```bash
sudo systemctl restart tg-bot
sleep 3
sudo systemctl status tg-bot --no-pager | head -12
sudo tail -20 /opt/tg-bot/logs/bot.log
```

Проверьте в самом Telegram, что бот отвечает и что «Купить» показывает
реквизиты. Только после этого — первый коммит.

**7. Убрать копии, в которых секреты остались.**

```bash
sudo shred -u /opt/tg-bot/config.py.orig /opt/tg-bot/.env.orig
```

Делайте это, когда бот уже проверен: пока не проверен, копии нужны.
