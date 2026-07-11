FROM python:3.12-slim

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir playwright \
    && playwright install --with-deps chromium

COPY app ./app
COPY seed ./seed

ENV AT_DB_PATH=data/tracker.db
VOLUME ["/srv/data"]
EXPOSE 8033

CMD ["sh", "-c", "python -m seed.seed && uvicorn app.main:app --host 0.0.0.0 --port 8033"]
