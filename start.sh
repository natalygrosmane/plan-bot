#!/usr/bin/env bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

# Check if .env exists
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "⚠️ Создан файл .env. Пожалуйста, откройте его и укажите ваш TELEGRAM_BOT_TOKEN и GEMINI_API_KEY!"
    fi
fi

if [ -f .venv/bin/python ]; then
    PYTHON_BIN=".venv/bin/python"
else
    PYTHON_BIN="python3"
fi

echo "🚀 Запуск Plan Bot..."
$PYTHON_BIN bot.py
