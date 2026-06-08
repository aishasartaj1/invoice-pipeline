FROM python:3.12-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim
RUN useradd --uid 1000 --no-create-home --shell /sbin/nologin appuser
WORKDIR /app
COPY --from=builder /install /usr/local
COPY wsgi.py gunicorn.conf.py ./
COPY app/ ./app/
ENV PORT=8080 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LOG_LEVEL=info
USER appuser
EXPOSE 8080
CMD ["gunicorn", "-c", "gunicorn.conf.py", "wsgi:application"]