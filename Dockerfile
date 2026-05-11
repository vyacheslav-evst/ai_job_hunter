# Dockerfile для AI Job Hunter Agent
# Деплой на Hugging Face Spaces (Docker SDK)

FROM python:3.11-slim

# Рабочая директория
WORKDIR /app

# Системные зависимости (шрифты для PDF + lxml)
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-dejavu-core \
    libxml2 \
    libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

# Зависимости Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Код приложения
COPY . .

# Создаём директории, которые нужны в рантайме
RUN mkdir -p output memory

# HF Spaces требует порт 7860
EXPOSE 7860

# Переменные окружения для Streamlit
ENV STREAMLIT_SERVER_PORT=7860 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    PYTHONIOENCODING=utf-8 \
    PYTHONUNBUFFERED=1

# Запуск
CMD ["streamlit", "run", "app.py", "--server.port=7860", "--server.address=0.0.0.0"]
