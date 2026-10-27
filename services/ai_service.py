import os
from pathlib import Path
import httpx
from config import (
    AI_PROVIDER,
    GEMINI_API_KEY,
    OPENAI_API_KEY,
    GROQ_API_KEY,
)

SYSTEM_EVENING_PROMPT = """Ты — автономный персональный ассистент по разгрузке головы, планированию и структурированию задач.
Текущая задача: провести вечернюю выгрузку и планирование («Итоги дня»).

Тебе передано содержимое файла inbox.md с мыслями, задачами и заметками за день.

Действия:
1. Сгруппируй всё собранное по категориям:
   • Трейдинг & Аналитика
   • Обучение / Менторство / Проекты
   • Ариана (семья, школа, занятия)
   • Быт / Здоровье / Спорт
   • Идеи в бэклог

2. Раздели задачи на:
   — ЖЁСТКИЕ (Hard events, с привязкой ко времени)
   — ГИБКИЕ (To-Do, по блокам дня: Утро / День / Вечер)
   — Идеи и долгосрочные проекты (пойдут в backlog.md)

3. Выведи пользователю:
   — Структурированный красивый отчёт по категориям с эмодзи.
   — Черновик плана на завтра (Top-3 фокуса, Жёсткие дела, Гибкие по блокам).
   — Задай 1-2 конкретных уточняющих вопроса, если у каких-то задач не указано время или приоритет.

Отвечай на чистом русском языке, форматируя текст для Telegram (markdown/bold/bullet points).
В самом конце ответа добавь специальный скрытый JSON-блок (в тегах ```json_plan ... ```) со структурой:
{
  "top_3": ["задача 1", "задача 2", "задача 3"],
  "hard_events": ["10:00 Встреча..."],
  "morning": ["задача 1"],
  "day": ["задача 2"],
  "evening": ["задача 3"],
  "backlog_items": {
    "trading": ["..."],
    "learning": ["..."],
    "ariana": ["..."],
    "lifestyle": ["..."],
    "other": ["..."]
  }
}
"""

SYSTEM_MORNING_PROMPT = """Ты — персональный ассистент по планированию.
Пользователь написал «Доброе утро».
Тебе передано содержимое актуального файла todo.md.

Твоя задача:
Выдать короткий, ёмкий фокус на день:
— 🎯 Top-3 главных задачи.
— ⏰ ЖЁСТКИЕ дела по времени.
— 📋 ГИБКИЕ задачи по блокам (🌅 Утро / ☀️ День / 🌙 Вечер).

Будь лаконичен, структурирован и заряди на продуктивный день. Форматируй красиво для Telegram.
"""

SYSTEM_REVIEW_PROMPT = """Ты — персональный ассистент по планированию.
Пользователь написал «Ревизия недели».
Тебе переданы файлы todo.md и backlog.md.

Твоя задача:
1. Найти незакрытые задачи.
2. Проверить задачи на «Правило 3-х недель» (если задача кочует или висит без движения):
   Сформулируй: «⚠️ Правило 3-х недель: [Задача]. Удаляем, делегируем или ставим конкретную дату?»
3. Подвести краткий итог недели и предложить пересобрать приоритеты на следующую неделю.
Форматируй для Telegram.
"""


async def transcribe_audio(file_path: Path) -> str:
    """
    Transcribes audio (e.g. .ogg, .mp3) using the configured provider.
    Tries Groq -> Gemini -> OpenAI based on config and available keys.
    """
    # 1. Try Groq if selected or key exists
    if AI_PROVIDER == "groq" and GROQ_API_KEY:
        return await _transcribe_groq(file_path)

    # 2. Try Gemini if selected or key exists
    if AI_PROVIDER == "gemini" and GEMINI_API_KEY:
        return await _transcribe_gemini(file_path)

    # 3. Try OpenAI if selected or key exists
    if AI_PROVIDER == "openai" and OPENAI_API_KEY:
        return await _transcribe_openai(file_path)

    # Fallbacks if default not configured but another key is available
    if GROQ_API_KEY:
        return await _transcribe_groq(file_path)
    if GEMINI_API_KEY:
        return await _transcribe_gemini(file_path)
    if OPENAI_API_KEY:
        return await _transcribe_openai(file_path)

    raise ValueError(
        "Не настроен API ключ для распознавания голоса. Укажите GEMINI_API_KEY, GROQ_API_KEY или OPENAI_API_KEY в .env"
    )


async def _transcribe_gemini(file_path: Path) -> str:
    import google.generativeai as genai

    genai.configure(api_key=GEMINI_API_KEY)
    uploaded_file = genai.upload_file(path=str(file_path), mime_type="audio/ogg")
    
    # Try gemini-2.0-flash or fallback to 1.5-flash
    for model_name in ["gemini-2.0-flash", "gemini-1.5-flash"]:
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content([
                "Расшифруй это голосовое сообщение на русском языке максимально точно. "
                "Если в речи звучат слова 'задача', 'рынок' или 'идея' в начале, сохрани их как теги !задача, !рынок, !идея. "
                "Выведи ТОЛЬКО текст расшифровки без вводных слов и кавычек.",
                uploaded_file,
            ])
            text = response.text.strip()
            # Clean up uploaded file reference
            try:
                uploaded_file.delete()
            except Exception:
                pass
            return text
        except Exception as e:
            continue
    raise RuntimeError("Не удалось расшифровать аудио через Gemini")


async def _transcribe_groq(file_path: Path) -> str:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        base_url="https://api.groq.com/openai/v1",
        api_key=GROQ_API_KEY,
    )
    with open(file_path, "rb") as audio:
        transcription = await client.audio.transcriptions.create(
            model="whisper-large-v3",
            file=audio,
            language="ru",
        )
    return transcription.text.strip()


async def _transcribe_openai(file_path: Path) -> str:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    with open(file_path, "rb") as audio:
        transcription = await client.audio.transcriptions.create(
            model="whisper-1",
            file=audio,
            language="ru",
        )
    return transcription.text.strip()


async def generate_completion(system_prompt: str, user_prompt: str) -> str:
    """
    Generates LLM response using available provider (Gemini / OpenAI / Groq).
    """
    if (AI_PROVIDER == "gemini" or not OPENAI_API_KEY) and GEMINI_API_KEY:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        for model_name in ["gemini-2.0-flash", "gemini-1.5-flash"]:
            try:
                model = genai.GenerativeModel(
                    model_name=model_name,
                    system_instruction=system_prompt,
                )
                res = model.generate_content(user_prompt)
                return res.text
            except Exception:
                continue

    if OPENAI_API_KEY:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        res = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.4,
        )
        return res.choices[0].message.content or ""

    if GROQ_API_KEY:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=GROQ_API_KEY,
        )
        res = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.4,
        )
        return res.choices[0].message.content or ""

    raise ValueError("Не настроен API ключ для LLM (GEMINI_API_KEY, OPENAI_API_KEY или GROQ_API_KEY).")


async def process_evening_review(inbox_content: str) -> str:
    return await generate_completion(
        SYSTEM_EVENING_PROMPT,
        f"Вот содержимое файла inbox.md за сегодня:\n\n{inbox_content}",
    )


async def process_morning_focus(todo_content: str) -> str:
    return await generate_completion(
        SYSTEM_MORNING_PROMPT,
        f"Вот актуальное содержимое файла todo.md:\n\n{todo_content}",
    )


async def process_weekly_review(todo_content: str, backlog_content: str) -> str:
    return await generate_completion(
        SYSTEM_REVIEW_PROMPT,
        f"--- todo.md ---\n{todo_content}\n\n--- backlog.md ---\n{backlog_content}",
    )
