
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

This starts three processes via honcho:

| Process | What it does |
|---------|-------------|
| `api` | Django dev server on `localhost:8000` |
| `listener` | MQTT listener — bridges Mosquitto events into Django (local Lambda equivalent) |
| `sim` | Station simulator — simulates the fleet of stations over MQTT |

To stop Docker when done:

```bash
make stop
```

---

## Testing the unlock flow end to end

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
  -d '{"phone": "+15550000001", "otp": "123456"}'
```

Response:

```json
{
  "access": "<your-jwt-token>",
  "refresh": "...",
  "user": {"id": "...", "phone": "+15550000001"}
}
```

### 3. Unlock a bike

Bike `B001` is at station `S001` which is configured as `always_success`.

```bash
curl -X POST http://localhost:8000/api/v1/commands/unlock \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <your-jwt-token>" \
  -d '{"bike_id": "B001"}'
```

Response (immediate, before the station has responded):

```json
{
  "request_id": "...",
  "status": "PENDING",
  ...
}
```

### 4. Poll for the result

```bash
curl http://localhost:8000/api/v1/commands/<request_id> \
  -H "Authorization: Bearer <your-jwt-token>"
```

Once the station simulator responds (usually within 1-2 seconds):

```json
{
  "request_id": "...",
  "status": "SUCCESS",
  "ride_id": "...",
  ...
}
```

---

## Test users and fleet

Seeded from `simulator/fleet.yml`:

| Phone | Use |
|-------|-----|
| `+15550000001` | Test user 1 |
| `+15550000002` | Test user 2 |
| `+15550000003` | Test user 3 |

| Station | Bikes | Behavior |
|---------|-------|----------|
| `S001` — Market & 5th | B001, B002, B003 | `always_success` |
| `S002` — Mission & 16th | B004, B005 | `flaky` (30% fail rate) |
| `S003` — Castro & Market | B006 | `always_fail` |
| `S004` — Caltrain Station | B007 | `timeout` (never responds) |

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
│   │   ├── commands/         # Unlock command lifecycle
│   │   ├── rides/            # Ride start and end
│   │   ├── stations/         # Station and dock state
│   │   ├── bikes/            # Bike state
│   │   ├── users/            # Auth (phone + OTP)
│   │   └── iot/              # MQTT publisher and event handler
│   ├── bikeshare/settings/   # base / local / production / test
│   └── requirements/         # base / local / production
├── simulator/                # Station simulator (local dev only)
│   ├── fleet.yml             # Fleet config — stations, docks, bikes
│   └── station_sim/          # Simulator code
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
