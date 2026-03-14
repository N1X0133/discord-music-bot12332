#!/bin/bash

echo "🚀 Запуск музыкального бота..."

# Проверка и установка FFmpeg
if ! command -v ffmpeg &> /dev/null; then
    echo "📦 Устанавливаю FFmpeg..."
    apt-get update && apt-get install -y ffmpeg
fi

# Установка зависимостей
echo "📦 Устанавливаю зависимости..."
pip install -r requirements.txt

# Запуск бота
echo "✅ Бот запускается..."
python main.py
