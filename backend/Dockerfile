FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system dbzenith && adduser --system --ingroup dbzenith dbzenith

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY alembic.ini .
COPY alembic ./alembic
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh && chown -R dbzenith:dbzenith /app

USER dbzenith
EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
