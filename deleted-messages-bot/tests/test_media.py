from types import SimpleNamespace

from app.media import Media, extract, too_big


def file(file_id: str = "AgAC", size: int | None = 1000, **over) -> SimpleNamespace:
    base = dict(file_id=file_id, file_unique_id=f"u-{file_id}", file_size=size)
    base.update(over)
    return SimpleNamespace(**base)


def message(**over) -> SimpleNamespace:
    base = dict(
        photo=None,
        video=None,
        animation=None,
        audio=None,
        voice=None,
        video_note=None,
        sticker=None,
        document=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_из_фото_берётся_самый_большой_размер():
    found = extract(
        message(photo=[file("small", 100), file("medium", 500), file("big", 9000)])
    )

    assert found == Media(
        file_id="big", unique_id="u-big", kind="photo", size=9000, name=None
    )


def test_видео_не_подменяется_превью():
    # У сообщения с видео есть и миниатюра, но интересует само видео.
    found = extract(message(video=file("vid"), photo=None))

    assert found is not None
    assert found.kind == "video"
    assert found.file_id == "vid"


def test_имя_файла_сохраняется():
    found = extract(message(document=file("doc", 2048, file_name="отчёт.pdf")))

    assert found is not None
    assert found.kind == "document"
    assert found.name == "отчёт.pdf"


def test_голосовое_и_видеосообщение_опознаются():
    assert extract(message(voice=file("v"))).kind == "voice"
    assert extract(message(video_note=file("vn"))).kind == "video_note"
    assert extract(message(sticker=file("s"))).kind == "sticker"


def test_текстовое_сообщение_без_вложений():
    assert extract(message()) is None


def test_пустая_запись_без_file_id_не_считается_вложением():
    assert extract(message(document=file(file_id=""))) is None


def test_большой_файл_не_качаем():
    assert too_big(Media("a", "b", "video", size=25 * 1024 * 1024), max_mb=20)
    assert not too_big(Media("a", "b", "video", size=5 * 1024 * 1024), max_mb=20)
    # Размер неизвестен — пробуем скачать, Telegram сам откажет.
    assert not too_big(Media("a", "b", "video", size=None), max_mb=20)
