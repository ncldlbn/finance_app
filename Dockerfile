# Finance Tracker: app Flask servita da gunicorn. Il database è PostgreSQL (servizio «db» di docker-compose.yml).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt requirements-docker.txt ./
RUN pip install -r requirements.txt -r requirements-docker.txt

COPY . .
# Utente senza privilegi: il processo non gira come root.
RUN useradd --create-home --uid 10001 app && chown -R app:app /app
USER app

EXPOSE 8000
# Lo schema PostgreSQL viene creato al primo avvio (sotto un lock: più worker non lo creano insieme).
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-", "app:create_app()"]
