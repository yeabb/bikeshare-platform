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
| Timeout sweep | `apps/commands/management/commands/sweep_timeouts.py` | Local dev only — marks stale PENDING commands TIMEOUT (EventBridge Scheduler + Lambda does this in production) |
| Station heartbeat | `apps/stations/management/commands/station_heartbeat.py` | Local dev only — marks silent stations INACTIVE every 60s (EventBridge Scheduler + Lambda does this in production) |
| Seed script | `apps/common/management/commands/seed_dev_data.py` | Populates DB from simulator/fleet.yml |
| Station simulator | `simulator/station_sim/main.py` | Simulates fleet of stations over MQTT (local dev only) — publishes STATION_TELEMETRY every 30s |
| User simulator | `simulator/user_sim/main.py` | Drives the HTTP API flow for each user in fleet.yml (auth → unlock → poll). Replaces manual curl commands for local testing. |

---

## Key Models

```python
# apps/users/models.py
User: id (UUID), phone (unique), status, otp_code, otp_expires_at

# apps/stations/models.py
Station: id (str PK e.g. "S001"), name, lat, lng, status, total_docks, last_telemetry_at (nullable)
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

## Two Simulators — How They Divide the Work

There are two simulators and they have strictly separate responsibilities:

**Station simulator** (`simulator/station_sim/`) — runs as the `sim` process in Procfile
- Connects to Mosquitto over MQTT
- Listens for UNLOCK commands published by the backend
- Responds with UNLOCK_RESULT and BIKE_UNDOCKED events
- Runs a background thread per successful ride to simulate the rider's journey, then publishes BIKE_DOCKED when the bike is returned
- Knows nothing about HTTP

**User simulator** (`simulator/user_sim/`) — run manually in a second terminal when you want to test without curl
- Talks to the Django backend over HTTP only
- Authenticates each user (request-otp → verify-otp → JWT)
- Calls POST /commands/unlock to start a ride
- Polls GET /commands/{request_id} until the command reaches a terminal state
- If SUCCESS, polls GET /me/active-ride until the ride ends
- Knows nothing about MQTT

**Together**: user_sim triggers the HTTP unlock → backend publishes MQTT → station_sim responds → backend processes the event → ride starts → station_sim docks the bike → ride ends. user_sim just watches the API side of this chain.

**fleet.yml is the shared config.** Both simulators read it. Each user entry has a `bike_id` field so the user simulator knows which bike to unlock by default. Each station entry has a `behavior` field so the station simulator knows how to respond.

---

## Station Heartbeat Monitoring

`Station.last_telemetry_at` is updated every time `reconcile_telemetry()` runs for a station. A background sweep (`station_heartbeat_check()`) runs every 60 seconds and marks stations `INACTIVE` if:

- `last_telemetry_at` is older than **90 seconds** (3 missed 30s reports), OR
- `last_telemetry_at` is null AND `created_at` is older than **5 minutes** (grace period for new stations coming online)

When a station comes back online and resumes sending telemetry, `reconcile_telemetry()` automatically restores it to `ACTIVE`.

**Ops endpoint:** `GET /api/v1/stations/inactive` — lists all currently downed stations with their `last_telemetry_at`.

**Implementation:**
- Logic: `apps/stations/services.py:station_heartbeat_check()`
- Local runner: `python manage.py station_heartbeat` — runs as the `heartbeat` process in Procfile
- Production: EventBridge Scheduler triggers a Lambda every 60 seconds

---

## Command Timeout

Commands have `expires_at = created_at + 10s`. A background sweep queries:

```python
Command.objects.filter(status='PENDING', expires_at__lt=timezone.now())
```

and marks them `TIMEOUT`, restoring the dock to `OCCUPIED`.

**Implementation:**
- Logic: `apps/commands/services.py:sweep_timed_out_commands()`
- Local runner: `python manage.py sweep_timeouts` — a `while True` loop every 5 seconds, runs as the `sweep` process in Procfile
- Production: EventBridge Scheduler triggers a Lambda every 1 minute calling the same `sweep_timed_out_commands()` function — Celery/Redis deliberately not used since we're going to AWS

**Why not Celery + Redis:**
Celery is worth adding when you need retry logic and queuing for async tasks like SMS and payments. The timeout sweep is a simple periodic DB query — EventBridge Scheduler + Lambda is the right production solution, making Celery unnecessary overhead for this use case.

---

## Test Locations

- `apps/commands/tests.py` — command creation, UNLOCK_RESULT handling, idempotency
- `apps/rides/tests.py` — ride start, ride end via BIKE_DOCKED, idempotency
- `apps/stations/tests.py` — dock state transitions, telemetry reconciliation, heartbeat check, inactive endpoint

---

## What Is Not Built Yet

- SMS OTP (stubbed — returns OTP in response when DEBUG=True)
- Stale rides stuck ACTIVE for an unusually long time (two-snapshot catches most cases; rides that slip through need a manual ops endpoint — task #12)
- Handle split-brain: UNLOCK_RESULT lost but bike physically unlocked (task #14)
- Payment processing
- Android/iOS apps

## What Is Live on AWS

- **BikeshareBackendStack**: VPC, RDS PostgreSQL (`bikeshare-db`), ECS Fargate (Django), ALB
  - ALB: `http://Bikesh-Servi-0FYN2l2GYpbE-1416179423.us-east-1.elb.amazonaws.com`
- **BikeshareLambdaStack**: event-ingestion, timeout-sweep, station-heartbeat — all wired to ALB
- **BikeshareIotStack**: IoT Things (S001–S005), certificates, per-station policies, IoT Rules
- **BikeshareSchedulerStack**: EventBridge Scheduler — timeout sweep (1 min), station heartbeat (1 min)
