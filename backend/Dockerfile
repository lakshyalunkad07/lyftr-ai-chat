FROM python:3.12-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000
WORKDIR /app
COPY --from=builder /install /usr/local
COPY app ./app
COPY entrypoint.py ./entrypoint.py
RUN mkdir -p /data && useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app /data
EXPOSE 8000
ENTRYPOINT ["python", "/app/entrypoint.py"]
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
