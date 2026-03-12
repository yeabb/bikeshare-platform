# Bikeshare Platform

A dock-based bike sharing system. Riders scan a bike QR code, the backend locates the dock, sends an unlock command to the station over MQTT, and the station responds with the result. Ride ends when the bike is physically docked at any station.

See [`docs/system-architecture.md`](docs/system-architecture.md) for full architecture diagrams and design decisions.

---

## Prerequisites

- Python 3.11+
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (for Postgres + Mosquitto)
- Node.js (only if you use the gitmoji commit hook)

---

## First-time setup

```bash
git clone git@github.com:yeabb/bikeshare-platform.git
cd bikeshare-platform
make setup
```

`make setup` does four things:
1. Creates Python virtual environments for `backend/` and `simulator/`
2. Installs dependencies in both
3. Runs database migrations
4. Seeds the database with stations, docks, bikes, and test users from `simulator/fleet.yml`

---

## Running the stack

Make sure Docker Desktop is running, then:

```bash
make dev
```

This starts five processes via honcho:

| Process | What it does |
|---------|-------------|
| `api` | Django dev server on `localhost:8000` |
| `listener` | MQTT listener — bridges Mosquitto events into Django (local Lambda equivalent) |
| `sweep` | Timeout sweep — marks stale PENDING commands as TIMEOUT every 5s (local CloudWatch equivalent) |
| `heartbeat` | Station heartbeat — marks silent stations INACTIVE every 60s (local CloudWatch equivalent) |
| `sim` | Station simulator — simulates the fleet of stations over MQTT, publishes telemetry every 30s |

Wait until you see all of these in the output:
```
api.1           | Watching for file changes with StatReloader
sim.1           | Connected to MQTT broker
sim.1           | User profiles: +15550000001 (commuter), +15550000002 (explorer), +15550000003 (ghost)
sweep.1         | Timeout sweep started — running every 5s
heartbeat.1     | Station heartbeat started — running every 60s
```

To stop Docker when done:

```bash
make stop
```

---

## Routine testing workflow

After running end-to-end tests, bikes move around the fleet and dock states change. Run `make seed` before each test session to reset everything back to the starting positions from `fleet.yml`.

```bash
make seed       # reset bikes to home positions (safe to run anytime, no duplicates)
make dev        # start the stack (skip if already running)
```

Then in a second terminal, run the user simulator against the scenario you want to test:

```bash
cd simulator

# Single scenario
.venv/bin/python -m user_sim.main --user +15550000001   # normal success (S001 → S004)
.venv/bin/python -m user_sim.main --user +15550000002   # flaky unlock (S002)
.venv/bin/python -m user_sim.main --user +15550000003   # ghost — bike not returned
.venv/bin/python -m user_sim.main --user +15550000004   # stale ride reconciliation (S005 silent_return)

# All users concurrently
.venv/bin/python -m user_sim.main
```

Watch Terminal 1 for the full station + backend event flow.

**Full reset** (wipe DB and start clean):
```bash
make stop
docker compose down -v   # removes volumes — DB is wiped
make dev
make seed
```

---

## Testing the unlock flow end to end

You need two terminals. **Terminal 1** runs `make dev`. **Terminal 2** runs the curl commands below. After step 3, switch your eyes back to Terminal 1 to watch the ride play out automatically.

### 1. Request an OTP

```bash
curl -X POST http://localhost:8000/api/v1/auth/request-otp \
  -H "Content-Type: application/json" \
  -d '{"phone": "+15550000001"}'
```

In local dev, the OTP is returned directly in the response (no SMS sent):

```json
{"message": "OTP sent", "otp": "123456"}
```

### 2. Verify OTP and get a JWT token

```bash
curl -X POST http://localhost:8000/api/v1/auth/verify-otp \
  -H "Content-Type: application/json" \
  -d '{"phone": "+15550000001", "otp": "PASTE_OTP_HERE"}'
```

Copy the `access` token from the response.

### 3. Unlock a bike

Bike `B001` is at station `S001` (`always_success`). User `+15550000001` is a commuter — always rides to S004.

```bash
curl -X POST http://localhost:8000/api/v1/commands/unlock \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer PASTE_TOKEN_HERE" \
  -d '{"bike_id": "B001"}'
```

You'll get back `status: PENDING` and a `request_id`. Now switch to Terminal 1 and watch — within a few seconds you'll see:

```
sim.1    | [S001] Unlock SUCCESS for bike B001
sim.1    | Published → station/S001/events: UNLOCK_RESULT
sim.1    | Published → station/S001/events: BIKE_UNDOCKED
sim.1    | [Ride] +15550000001 (commuter) — riding for 24s, will return bike B001
          ... wait ...
sim.1    | [Ride] Bike B001 returned to S004 dock 2
sim.1    | Published → station/S004/events: BIKE_DOCKED
```

The ride completes automatically. No further action needed.

### 4. (Optional) Poll for the result

```bash
curl http://localhost:8000/api/v1/commands/PASTE_REQUEST_ID_HERE \
  -H "Authorization: Bearer PASTE_TOKEN_HERE"
```

```json
{
  "request_id": "...",
  "status": "SUCCESS",
  "ride_id": "...",
  ...
}
```

---

## Testing the timeout scenario

Bike `B007` is at station `S004` which is configured as `timeout` — it never responds to unlock commands.

Repeat steps 1-3 above using `+15550000001` and `bike_id: B007`. After 10 seconds (the command TTL) you'll see in Terminal 1:

```
sim.1    | [S004] Simulating timeout — not responding
sweep.1  | Command ... → TIMEOUT. Dock S004-D01 → OCCUPIED.
sweep.1  | Swept 1 timed-out command(s) → TIMEOUT
```

The command is marked `TIMEOUT`, the dock is restored to `OCCUPIED`, and the user is unblocked.

---

## Test users and fleet

Seeded from `simulator/fleet.yml`:

| Phone | Behavior | What they do |
|-------|----------|-------------|
| `+15550000001` | `commuter` | Always rides to S004, always returns the bike |
| `+15550000002` | `explorer` | Random destination, 15% chance of not returning |
| `+15550000003` | `ghost` | Random destination, 80% chance of never returning |
| `+15550000004` | `commuter` | Always rides to S005 — stale ride reconciliation demo |

| Station | Bikes | Unlock behavior |
|---------|-------|----------|
| `S001` — Market & 5th | B001, B002, B003, B008 | `always_success` |
| `S002` — Mission & 16th | B004, B005 | `flaky` (30% fail rate) |
| `S003` — Castro & Market | B006 | `always_fail` |
| `S004` — Caltrain Station | B007 | `timeout` (never responds) |
| `S005` — Embarcadero | — | `silent_return` (unlocks succeed, BIKE_DOCKED suppressed) |

---

## Testing with the user simulator

Instead of running curl commands manually, use the user simulator to drive the full HTTP flow automatically. It authenticates, unlocks a bike, polls for the result, and waits for the ride to end.

**Terminal 1** — run the stack:
```bash
make dev
```

**Terminal 2** — run the user simulator:
```bash
# All three users concurrently (each uses their default bike from fleet.yml)
cd simulator && .venv/bin/python -m user_sim.main

# Single user
cd simulator && .venv/bin/python -m user_sim.main --user +15550000001

# Override bike (useful after re-seeding when bikes have moved)
cd simulator && .venv/bin/python -m user_sim.main --user +15550000001 --bike B001
```

Watch Terminal 1 for the station events, ride lifecycle, and sweep activity.

---

## Other useful commands

```bash
make test       # run the test suite
make migrate    # run database migrations
make seed       # re-seed dev data (safe to run multiple times)
make shell      # open a Django shell
```

---

## Project structure

```
bikeshare-platform/
├── backend/                  # Django backend
│   ├── apps/
│   │   ├── commands/         # Unlock command lifecycle + timeout sweep
│   │   ├── rides/            # Ride start and end
│   │   ├── stations/         # Station and dock state
│   │   ├── bikes/            # Bike state
│   │   ├── users/            # Auth (phone + OTP)
│   │   └── iot/              # MQTT publisher and event handler
│   ├── bikeshare/settings/   # base / local / production / test
│   └── requirements/         # base / local / production
├── simulator/                # Station and user simulators (local dev only)
│   ├── fleet.yml             # Fleet config — stations, docks, bikes, user behaviors
│   ├── station_sim/          # Station simulator — responds to MQTT unlock commands
│   └── user_sim/             # User simulator — drives the HTTP API flow
├── docs/                     # Architecture, API, MQTT protocol, state machines
├── mosquitto/                # Mosquitto broker config
├── docker-compose.yml        # Postgres + Mosquitto
├── Makefile                  # Dev commands
└── Procfile                  # Process definitions for honcho
```

---

## Docs

| Doc | What it covers |
|-----|---------------|
| [`docs/system-architecture.md`](docs/system-architecture.md) | Component diagram, sequence diagrams, internal code flow |
| [`docs/api_v1.md`](docs/api_v1.md) | Full HTTP API reference |
| [`docs/mqtt_protocol.md`](docs/mqtt_protocol.md) | MQTT topics and event payload schemas |
| [`docs/state_machines.md`](docs/state_machines.md) | Command, Ride, Dock, Bike state transitions |
| [`docs/ai_context.md`](docs/ai_context.md) | Quick reference for AI-assisted development |
