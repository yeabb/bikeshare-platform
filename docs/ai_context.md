# AI Context — Bikeshare Platform

Quick reference for AI-assisted development. Read this before touching any core logic.

---

## What This System Does

A dock-based bike sharing platform. Riders scan a **bike** QR code → app calls backend → backend finds which dock/station has that bike → sends unlock command to station via MQTT → station unlocks → ride begins. Ride ends when bike is physically docked at any station.

---

## The Hardest Part (Read This First)

The bike unlock flow is async. The HTTP call returns immediately with `PENDING`. The real state change happens when the station publishes `UNLOCK_RESULT` via MQTT, which is ingested by a Lambda (prod) or local subscriber (dev) and written to Postgres.

**Never create a ride optimistically.** Ride is created only in `handle_unlock_result()` after `status == SUCCESS`.

**Never end a ride via HTTP.** Ride ends only in `end_ride_on_dock()` triggered by `BIKE_DOCKED` event.

---

## Critical Mapping

```
bike_id → (station_id, dock_index) via Bike.current_dock FK
```

This is updated by:
- `BIKE_DOCKED` event → `end_ride_on_dock()` sets `Bike.current_station/current_dock`
- `BIKE_UNDOCKED` event → `handle_bike_undocked()` clears `Dock.current_bike`
- Command SUCCESS → `start_ride()` does not change dock location yet (bike still physically there)

---

## Module Responsibilities

| Module | File | Does |
|--------|------|------|
| Unlock entry point | `apps/commands/services.py:create_unlock_command` | Validates, creates Command, publishes MQTT |
| UNLOCK_RESULT handler | `apps/commands/services.py:handle_unlock_result` | Updates Command, calls start_ride |
| Ride start | `apps/rides/services.py:start_ride` | Creates Ride, updates Bike |
| Ride end | `apps/rides/services.py:end_ride_on_dock` | Ends Ride, updates Bike + Dock |
| MQTT publisher | `apps/iot/publisher.py` | Publishes to Mosquitto (local) or AWS IoT Core |
| Event router | `apps/iot/event_handler.py` | Parses event type, dispatches to correct service |
| Dock events | `apps/stations/services.py` | `handle_bike_undocked`, `handle_dock_fault`, etc. |
| MQTT listener | `apps/iot/management/commands/mqtt_listener.py` | Local dev only — bridges Mosquitto → event_handler (Lambda does this in production) |
| Seed script | `apps/common/management/commands/seed_dev_data.py` | Populates DB from simulator/fleet.yml |
| Station simulator | `simulator/station_sim/main.py` | Simulates fleet of stations over MQTT (local dev only) |

---

## Key Models

```python
# apps/users/models.py
User: id (UUID), phone (unique), status, otp_code, otp_expires_at

# apps/stations/models.py
Station: id (str PK e.g. "S001"), name, lat, lng, status, total_docks
Dock: station (FK), dock_index (int, 1-based), state, current_bike (FK→Bike, nullable), fault_code

# apps/bikes/models.py
Bike: id (str PK e.g. "B742"), status, current_station (FK), current_dock (FK), current_ride (FK)

# apps/commands/models.py
Command: request_id (UUID PK), type, user, station, dock, bike, status, failure_reason, expires_at

# apps/rides/models.py
Ride: ride_id (UUID PK), user, bike, unlock_command (1:1), start_station, start_dock,
      end_station (null), end_dock (null), started_at, ended_at, status
```

---

## MQTT dockId vs DB dock PK

- MQTT uses `dockId` = **integer dock_index** (1-based), e.g. `1`, `2`
- DB uses auto-int PK for Dock, with `(station_id, dock_index)` unique constraint
- Look up dock by: `Dock.objects.get(station_id=station_id, dock_index=dock_index)`
- Display ID (API): `f"{station_id}-D{dock_index:02d}"` e.g. `"S001-D01"`

---

## Adding a New Station Event Type

1. Add the event type to `mqtt_protocol.md`
2. Add a handler method `_handle_<event>()` in `apps/iot/event_handler.py`
3. Register it in `handle_station_event()` dispatcher
4. Implement the service function in the relevant app's `services.py`
5. Write a test in `apps/<app>/tests.py`
6. Update `state_machines.md` if state transitions change

---

## Settings Structure

```
bikeshare/settings/
  base.py       ← all default settings, reads from env vars
  local.py      ← DEBUG=True, local MQTT, permissive CORS
  production.py ← DEBUG=False, AWS MQTT, strict settings
```

Select with `DJANGO_SETTINGS_MODULE`:
- Local: `bikeshare.settings.local`
- Production: `bikeshare.settings.production`

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DJANGO_SECRET_KEY` | insecure default | Must be set in production |
| `POSTGRES_DB` | `bikeshare` | Database name |
| `POSTGRES_USER` | `bikeshare` | DB user |
| `POSTGRES_PASSWORD` | `bikeshare` | DB password |
| `POSTGRES_HOST` | `localhost` | DB host |
| `POSTGRES_PORT` | `5432` | DB port |
| `MQTT_BROKER_TYPE` | `local` | `local` or `aws` |
| `MQTT_BROKER_HOST` | `localhost` | Mosquitto host (local mode) |
| `MQTT_BROKER_PORT` | `1883` | Mosquitto port (local mode) |
| `AWS_REGION` | `us-east-1` | AWS region (aws mode) |
| `AWS_IOT_ENDPOINT` | — | AWS IoT Core endpoint (aws mode) |

---

## Local Dev Quick Start

```bash
# First time only
make setup      # creates venvs, installs deps, runs migrations, seeds DB

# Every time you work
make dev        # starts Postgres + Mosquitto (Docker) + Django + MQTT listener + simulator
make stop       # stops Docker when done
```

Other useful commands:
```bash
make test       # run test suite
make migrate    # run migrations
make seed       # re-seed dev data from simulator/fleet.yml
make shell      # Django shell
```

---

## Command Timeout

Commands have `expires_at = created_at + 10s`. A background sweep (future: Celery Beat or Lambda scheduled rule) queries:

```python
Command.objects.filter(status='PENDING', expires_at__lt=timezone.now())
```

and marks them `TIMEOUT`. This is not yet implemented — tracked in roadmap.

---

## Test Locations

- `apps/commands/tests.py` — command creation, UNLOCK_RESULT handling, idempotency
- `apps/rides/tests.py` — ride start, ride end via BIKE_DOCKED, idempotency
- `apps/stations/tests.py` — dock state transitions

---

## What Is Not Built Yet

- Command timeout sweep job (commands have expires_at but nothing sweeps them yet)
- SMS OTP (stubbed — returns OTP in response when DEBUG=True)
- Telemetry reconciliation (handler exists, logic is TODO)
- User simulator (simulator/user_sim/ is empty)
- AWS Lambda ingestion function (mqtt_listener management command is the local analog)
- AWS IoT Core setup (Things, certificates, policies, IoT Rules)
- Payment processing
- Android/iOS apps
