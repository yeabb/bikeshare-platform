.PHONY: dev setup infra stop test migrate migrations seed shell

PYTHON     = backend/.venv/bin/python3
MANAGE     = cd backend && DJANGO_SETTINGS_MODULE=bikeshare.settings.local $(PYTHON) manage.py
SIM_PYTHON = simulator/.venv/bin/python3

# ---------------------------------------------------------------
# Main commands
# ---------------------------------------------------------------

# First time setup — install deps, run migrations, seed dev data
setup:
	cd backend && python3 -m venv .venv && .venv/bin/pip install -q -r requirements/local.txt
	cd simulator && python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt
	$(MANAGE) migrate
	$(MANAGE) seed_dev_data

# Start infrastructure (Postgres + Mosquitto) in background
infra:
	docker compose up -d db mosquitto

# Start the full dev stack — infra + all app processes via honcho
dev: infra
	DJANGO_SETTINGS_MODULE=bikeshare.settings.local backend/.venv/bin/honcho start -f Procfile

# Stop infrastructure
stop:
	docker compose down

# ---------------------------------------------------------------
# Backend helpers
# ---------------------------------------------------------------

migrate:
	$(MANAGE) migrate

migrations:
	$(MANAGE) makemigrations

seed:
	$(MANAGE) seed_dev_data

test:
	$(MANAGE) test apps --settings=bikeshare.settings.test

shell:
	$(MANAGE) shell
