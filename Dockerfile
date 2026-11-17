FROM node:24-bookworm-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN groupadd -r attendance && useradd -r -g attendance attendance \
    && install -d -o attendance -g attendance /app/data
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY config.py main.py web_main.py transfer_sqlite.py alembic.ini ./
COPY backend backend
COPY bot bot
COPY database database
COPY services services
COPY migrations migrations
COPY --from=frontend /src/frontend/dist frontend/dist
USER attendance
CMD ["python", "web_main.py", "--host", "0.0.0.0"]
