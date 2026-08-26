FROM python:3.11-slim

WORKDIR /app

# Copiar dependencias e instalar
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar codigo do servidor/bot
COPY bot_server.py .

EXPOSE 8000

ENV PORT=8000

CMD ["python", "bot_server.py"]
