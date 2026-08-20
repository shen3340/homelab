FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY rag.py .
COPY webhook.py .
COPY mcp_server.py .

RUN useradd \
    --create-home \
    --uid 10001 \
    rag

USER rag

EXPOSE 8000
EXPOSE 8001

CMD ["uvicorn", "webhook:app", "--host", "0.0.0.0", "--port", "8000"]