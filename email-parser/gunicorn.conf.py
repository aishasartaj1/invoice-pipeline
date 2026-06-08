import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8080')}"
worker_class = "gthread"
workers = 1
threads = int(os.environ.get("GUNICORN_THREADS", "8"))
timeout = 60
graceful_timeout = 8
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")
access_log_format = 'method=%(m)s path="%(U)s" status=%(s)s duration_ms=%(D)s bytes=%(b)s'