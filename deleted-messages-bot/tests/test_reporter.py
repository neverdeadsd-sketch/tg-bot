import re

from app import reporter
from app.reporter import TEXT_LIMIT, human_delta, render


def row(**over) -> dict:
    base = {
        "source": "bot",
        "chat_id": -1001234567890,
        "message_id": 42,
        "chat_title": "Рабочий чат",
        "chat_type": "supergroup",
        "user_id": 777,
        "user_name": "Иван Петров",
        "user_username": "ivan",
        "content_type": "text",
        "text": "привет",
        "text_lower": "привет",
        "media_file_id": None,
        "media_unique_id": None,
        "media_path": None,
        "media_name": None,
        "media_type": None,
        "reply_to": None,
        "forward_from": None,
        "has_markup": 0,
        "sent_at": "2026-10-25T12:00:00.000000+00:00",
        "saved_at": "2026-10-25T12:00:00.000000+00:00",
        "edited_at": None,
        "deleted_at": "2026-10-25T12:05:00.000000+00:00",
        "reported_at": None,
        "next_probe_at": None,
        "watch_until": None,
        "probe_count": 1,
    }
    base.update(over)
    return base


def test_разница_во_времени_по_русски():
    assert human_delta(0) == "0 с"
    assert human_delta(59) == "59 с"
    assert human_delta(60) == "1 мин"
    assert human_delta(3600) == "1 ч"
    assert human_delta(3660) == "1 ч 1 мин"
    assert human_delta(86400) == "1 д"
    assert human_delta(90000) == "1 д 1 ч"
    assert human_delta(-5) == "0 с"


def test_в_отчёте_есть_всё_нужное():
    [text] = render(row())

    assert "Удалённое сообщение" in text
    assert "Рабочий чат" in text
    assert "-1001234567890" in text
    assert "Иван Петров" in text
    assert "@ivan" in text
    assert "через 5 мин после отправки" in text
    assert "привет" in text
    assert "42" in text


def test_бот_не_выдаёт_обнаружение_за_точное_время_удаления():
    # Бот узнаёт о пропаже при очередной проверке, точного времени он не знает.
    [by_bot] = render(row(source="bot"))
    assert "Замечено удалённым:" in by_bot

    # Наблюдению с аккаунта Telegram сообщает удаление сам и сразу.
    [by_user] = render(row(source="user"))
    assert "<b>Удалено:</b>" in by_user


def test_пост_канала_подписан_каналом():
    [text] = render(row(user_id=None, user_name=None, user_username=None))
    assert "<b>Автор:</b> канал" in text


def test_разметка_из_чата_не_становится_разметкой_отчёта():
    [text] = render(
        row(text="<b>жирный</b> & <script>alert(1)</script>", user_name="Вася <админ>")
    )

    assert "<script>" not in text
    assert "&lt;script&gt;" in text
    assert "Вася &lt;админ&gt;" in text
    # Теги самого отчёта на месте.
    assert "<b>Чат:</b>" in text


def test_длинный_текст_режется_под_лимит():
    chunks = render(row(text="строка текста\n" * 1500))

    assert len(chunks) > 1
    assert all(len(chunk) <= TEXT_LIMIT for chunk in chunks)
    # Ничего не потерялось: строк столько же, сколько было.
    assert sum(chunk.count("строка текста") for chunk in chunks) == 1500


def test_разрез_не_рвёт_мнемонику():
    # Каждая кавычка превращается в &quot; — разрез вслепую оставил бы
    # половину мнемоники и Telegram отказался бы разбирать сообщение.
    chunks = render(row(text='"' * 4000))

    for chunk in chunks:
        assert len(chunk) <= TEXT_LIMIT
        assert "&" not in re.sub(r"&quot;", "", chunk.replace("&lt;", "").replace("&gt;", ""))


def test_сообщение_без_текста():
    [text] = render(row(text=None, content_type="sticker"))
    assert "Текста в сообщении не было." in text
    assert "<b>Тип:</b> sticker" in text


def test_пометка_о_вложении():
    [saved] = render(
        row(text=None, content_type="photo", media_type="photo", media_path="/d/x.jpg")
    )
    assert "фото" in saved and "файл сохранён" in saved

    [link_only] = render(
        row(text=None, content_type="photo", media_type="photo", media_file_id="AgAC")
    )
    assert "только ссылка Telegram" in link_only


def test_имя_файла_экранируется():
    [text] = render(
        row(
            text=None,
            content_type="document",
            media_type="document",
            media_name="<отчёт>.pdf",
            media_path="/d/x.pdf",
        )
    )
    assert "&lt;отчёт&gt;.pdf" in text


def test_версии_до_удаления_показываются():
    edits = [
        {"text": "первая правка", "edited_at": "2026-10-25T12:01:00.000000+00:00"},
        {"text": "вторая правка", "edited_at": "2026-10-25T12:02:00.000000+00:00"},
    ]
    chunks = render(row(), edits)
    joined = "\n".join(chunks)

    assert "Версии до удаления: 2" in joined
    assert "первая правка" in joined
    assert "вторая правка" in joined


def test_лишние_версии_не_раздувают_отчёт():
    edits = [
        {"text": f"правка {i}", "edited_at": "2026-10-25T12:01:00.000000+00:00"}
        for i in range(12)
    ]
    joined = "\n".join(render(row(), edits))

    assert "Версии до удаления: 12" in joined
    assert f"показаны последние {reporter.MAX_EDITS_SHOWN}" in joined
    assert "правка 0" not in joined
    assert "правка 11" in joined


def test_пересланное_сообщение_отмечено():
    [text] = render(row(forward_from="Другой чат"))
    assert "Переслано от:</b> Другой чат" in text


def test_ответ_на_сообщение_отмечен():
    [text] = render(row(reply_to=17))
    assert "Ответ на сообщение" in text
