import asyncio
from datetime import datetime
from pathlib import Path
from config import INBOX_FILE, TODO_FILE, BACKLOG_FILE, TIMEZONE

INBOX_HEADER = """# Inbox — Дневной сбор входящих мыслей

_Сюда записываются все входящие мысли и заметки в течение дня._

"""

TODO_TEMPLATE = """# To-Do — Задачи и расписание

## Фокус дня (Top-3)
1. 
2. 
3. 

---

## Жёсткие дела (Hard Events / по времени)
- 

---

## Гибкие задачи (To-Do по блокам)

### Утро
- [ ] 

### День
- [ ] 

### Вечер
- [ ] 
"""

BACKLOG_TEMPLATE = """# Backlog — Долгосрочные идеи и фоновые проекты

## Трейдинг & Аналитика
- 

## Обучение / Менторство / Проекты
- 

## Ариана (семья, школа, занятия)
- 

## Быт / Здоровье / Спорт
- 

## Идеи и прочее
- 
"""


def get_current_time_str() -> str:
    now = datetime.now(TIMEZONE)
    return now.strftime("%H:%M")


def get_current_date_str() -> str:
    now = datetime.now(TIMEZONE)
    return now.strftime("%Y-%m-%d")


def parse_tag_and_content(text: str) -> tuple[str, str, str]:
    """
    Parses prefix tags from text.
    Returns: (tag, clean_text, reply_message)
    """
    stripped = text.strip()
    lower = stripped.lower()

    if lower.startswith("!рынок") or lower.startswith("!market"):
        clean = stripped.split(maxsplit=1)
        tag = "[РЫНОК]"
        clean_text = clean[1] if len(clean) > 1 else ""
        reply = "Добавил заметку по рынку."
    elif lower.startswith("!задача") or lower.startswith("!task"):
        clean = stripped.split(maxsplit=1)
        tag = "[ЗАДАЧА]"
        clean_text = clean[1] if len(clean) > 1 else ""
        reply = "Зафиксировал задачу в inbox."
    elif lower.startswith("!идея") or lower.startswith("!idea"):
        clean = stripped.split(maxsplit=1)
        tag = "[ИДЕЯ]"
        clean_text = clean[1] if len(clean) > 1 else ""
        reply = "Записал идею."
    else:
        tag = "[МЫСЛЬ]"
        clean_text = stripped
        reply = "Зафиксировал в inbox."

    return tag, clean_text, reply


def _append_inbox_sync(entry: str) -> None:
    if not INBOX_FILE.exists():
        INBOX_FILE.write_text(INBOX_HEADER, encoding="utf-8")
    with open(INBOX_FILE, "a", encoding="utf-8") as f:
        f.write(entry)


async def add_to_inbox(text: str) -> tuple[str, str]:
    """
    Appends entry to inbox.md.
    Returns: (reply_phrase, recorded_entry)
    """
    tag, clean_text, reply = parse_tag_and_content(text)
    time_str = get_current_time_str()

    entry = f"- [{time_str}] {tag} {clean_text}\n"
    await asyncio.to_thread(_append_inbox_sync, entry)

    return reply, entry.strip()


def _read_file_sync(path: Path, default_content: str = "") -> str:
    if not path.exists():
        path.write_text(default_content, encoding="utf-8")
        return default_content
    return path.read_text(encoding="utf-8")


def _write_file_sync(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


async def read_file_safe(path: Path, default_content: str = "") -> str:
    return await asyncio.to_thread(_read_file_sync, path, default_content)


async def write_file_safe(path: Path, content: str) -> None:
    await asyncio.to_thread(_write_file_sync, path, content)


async def read_inbox() -> str:
    return await read_file_safe(INBOX_FILE, INBOX_HEADER)


async def clear_inbox() -> None:
    await write_file_safe(INBOX_FILE, INBOX_HEADER)


async def read_todo() -> str:
    return await read_file_safe(TODO_FILE, TODO_TEMPLATE)


async def write_todo(content: str) -> None:
    await write_file_safe(TODO_FILE, content)


async def read_backlog() -> str:
    return await read_file_safe(BACKLOG_FILE, BACKLOG_TEMPLATE)


async def write_backlog(content: str) -> None:
    await write_file_safe(BACKLOG_FILE, content)
