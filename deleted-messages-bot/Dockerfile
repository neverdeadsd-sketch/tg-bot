FROM python:3.13-slim

WORKDIR /app

# Зависимости отдельным слоем: правка кода не пересобирает их заново.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# База и вложения лежат в томе, иначе архив исчезнет вместе с контейнером.
VOLUME ["/app/data", "/app/logs"]

CMD ["python", "bot.py"]
