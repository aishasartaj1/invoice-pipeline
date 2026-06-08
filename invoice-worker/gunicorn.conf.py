import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8080')}"
worker_class = "gthread"
workers = 1
threads = int(os.environ.get("GUNICORN_THREADS", "4"))
timeout = 120
graceful_timeout = 10
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")
access_log_format = 'method=%(m)s path="%(U)s" status=%(s)s duration_ms=%(D)s bytes=%(b)s'