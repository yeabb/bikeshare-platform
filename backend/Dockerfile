FROM python:3.11-slim

WORKDIR /app

COPY requirements/base.txt requirements/base.txt
COPY requirements/local.txt requirements/local.txt

RUN pip install --no-cache-dir -r requirements/local.txt

COPY . .

ENV DJANGO_SETTINGS_MODULE=bikeshare.settings.local
ENV PYTHONUNBUFFERED=1
