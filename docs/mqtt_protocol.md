# MQTT Protocol

## Overview

All station communication uses MQTT.

- **Production:** AWS IoT Core (MQTT over TLS, port 8883)
- **Local dev:** Eclipse Mosquitto (plain MQTT, port 1883, no TLS)
- **QoS:** 1 (at-least-once delivery) for all messages
- **Payload format:** JSON, UTF-8 encoded
- **Timestamps:** Unix epoch seconds (UTC)

The MQTT topic structure and all payload schemas are **identical** between local dev and production. Only the broker address and TLS settings differ.

---

## Topic Structure

| Direction | Topic | Purpose |
|-----------|-------|---------|
| Backend → Station | `station/{station_id}/cmd` | Commands to the station controller |
| Station → Backend | `station/{station_id}/events` | Station-initiated events |
| Station → Backend | `station/{station_id}/telemetry` | Periodic health/state snapshots |

`{station_id}` is a string, e.g. `S001`.

---

## Backend → Station: Commands

Published to `station/{station_id}/cmd`.

### UNLOCK

Instructs the station to release the latch on a specific dock.

```json
{
  "type": "UNLOCK",
  "requestId": "550e8400-e29b-41d4-a716-446655440000",
  "stationId": "S001",
  "dockId": 1,
  "bikeId": "B742",
  "ttlSec": 10,
  "ts": 1741341600
}
```

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | Always `"UNLOCK"` |
| `requestId` | UUID string | Matches `Command.request_id` in DB. Used for correlation in `UNLOCK_RESULT`. |
| `stationId` | string | Station identifier |
| `dockId` | integer | Dock index (1-based). Matches `Dock.dock_index` in DB. |
| `bikeId` | string | Expected bike in this dock. Station **must verify** this matches before unlocking. |
| `ttlSec` | integer | Seconds the station should wait before giving up |
| `ts` | integer | Unix timestamp of command publication |

**Station behavior:**
1. Verify `bikeId` matches the bike sensor reading at `dockId`
2. If mismatch: publish `UNLOCK_RESULT` with `status: "FAILED"`, `reason: "BIKE_MISMATCH"`
3. Attempt to release the dock latch
4. If latch releases: publish `UNLOCK_RESULT` with `status: "SUCCESS"`
5. If latch fails: publish `UNLOCK_RESULT` with `status: "FAILED"`, `reason: "LATCH_FAULT"`
6. If `ttlSec` elapses with no resolution: publish `UNLOCK_RESULT` with `status: "FAILED"`, `reason: "TIMEOUT"`

---

## Station → Backend: Events

Published to `station/{station_id}/events`.

All events from stations are ingested via:
- **Production:** AWS IoT Rule → Lambda (`infra/aws/lambdas/event_ingestion/`)
- **Local dev:** Mosquitto subscriber → `apps/iot/event_handler.py`

### UNLOCK_RESULT

Result of an UNLOCK command. Always published, success or failure.

```json
{
  "type": "UNLOCK_RESULT",
  "requestId": "550e8400-e29b-41d4-a716-446655440000",
  "stationId": "S001",
  "dockId": 1,
  "bikeId": "B742",
  "status": "SUCCESS",
  "reason": null,
  "ts": 1741341603
}
```

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | Always `"UNLOCK_RESULT"` |
| `requestId` | UUID string | Matches the UNLOCK command's `requestId`. Used to update the correct `Command` record. |
| `stationId` | string | Station identifier |
| `dockId` | integer | Dock index |
| `bikeId` | string | Bike that was (or was not) unlocked |
| `status` | string | `"SUCCESS"` or `"FAILED"` |
| `reason` | string or null | null on success. On failure: see reason codes below |
| `ts` | integer | Unix timestamp of event |

**Failure reason codes:**

| Reason | Meaning |
|--------|---------|
| `BIKE_MISMATCH` | The bike at the dock does not match `bikeId` in the command |
| `LATCH_FAULT` | Hardware failure during unlock attempt |
| `TIMEOUT` | Station did not complete unlock within `ttlSec` |
| `UNKNOWN` | Unclassified error |

**Backend behavior on `SUCCESS`:**
- `Command` → `SUCCESS`, `resolved_at = now`
- Create `Ride` with `status = ACTIVE`
- `Bike` → `IN_USE`, `current_ride = ride`
- `Dock` → `UNLOCKING` (waiting for physical departure)

**Backend behavior on `FAILED`:**
- `Command` → `FAILED`, `failure_reason = reason`
- `Dock` → `OCCUPIED` (restore from `UNLOCKING`)

**Idempotency:** If `Command` is already in a terminal state (`SUCCESS`, `FAILED`, `TIMEOUT`), the event is ignored.

---

### BIKE_UNDOCKED

Published when a bike physically leaves a dock (departure sensor fires). Informational only — the ride has already started via `UNLOCK_RESULT SUCCESS`.

```json
{
  "type": "BIKE_UNDOCKED",
  "stationId": "S001",
  "dockId": 1,
  "bikeId": "B742",
  "ts": 1741341605
}
```

**Backend behavior:**
- `Dock` → `AVAILABLE`, `current_bike = null`
- Idempotent: if dock is already `AVAILABLE`, no-op

---

### BIKE_DOCKED

Published when a bike physically enters a dock (arrival sensor fires). **This is the ride-end trigger.**

```json
{
  "type": "BIKE_DOCKED",
  "stationId": "S001",
  "dockId": 1,
  "bikeId": "B742",
  "ts": 1741341920
}
```

> **Critical:** `bikeId` is the key field. The backend uses `bikeId` to find the active `Ride` and end it. The station **must always** include `bikeId` in this event.

**Backend behavior:**
1. Find `Bike` by `bikeId`
2. Find active `Ride` for that bike (`ride.status == ACTIVE`)
3. `Ride` → `COMPLETED`, `ended_at = now`, `end_station/dock` set
4. `Bike` → `AVAILABLE`, `current_station/dock` updated
5. `Dock` → `OCCUPIED`, `current_bike = bike`
6. Idempotent: if no active ride for `bikeId`, no-op

---

### DOCK_FAULT

Published when a dock hardware fault is detected.

```json
{
  "type": "DOCK_FAULT",
  "stationId": "S001",
  "dockId": 1,
  "faultCode": "LATCH_STUCK",
  "ts": 1741341700
}
```

**Fault codes:**

| Code | Meaning |
|------|---------|
| `LATCH_STUCK` | Latch cannot move |
| `SENSOR_ERROR` | Presence sensor malfunction |
| `POWER_FAULT` | Dock power issue |
| `COMMUNICATION_ERROR` | Station controller cannot reach dock module |
| `UNKNOWN` | Unclassified hardware fault |

**Backend behavior:**
- `Dock` → `FAULT`, `fault_code = faultCode`

---

### DOCK_FAULT_CLEARED

Published when a dock fault is resolved (e.g., after maintenance or automatic recovery).

```json
{
  "type": "DOCK_FAULT_CLEARED",
  "stationId": "S001",
  "dockId": 1,
  "ts": 1741341800
}
```

**Backend behavior:**
- If dock has a bike: `Dock` → `OCCUPIED`
- If dock is empty: `Dock` → `AVAILABLE`
- `fault_code` cleared

---

## Station → Backend: Telemetry

Published to `station/{station_id}/telemetry` every **30 seconds**.

This is a safety-net reconciliation snapshot. The backend uses it to catch missed events but does not rely on it as the primary state source.

```json
{
  "type": "STATION_TELEMETRY",
  "stationId": "S001",
  "ts": 1741341600,
  "docks": [
    {
      "dockId": 1,
      "state": "OCCUPIED",
      "bikeId": "B742",
      "healthy": true,
      "faultCode": null
    },
    {
      "dockId": 2,
      "state": "AVAILABLE",
      "bikeId": null,
      "healthy": true,
      "faultCode": null
    },
    {
      "dockId": 3,
      "state": "FAULT",
      "bikeId": null,
      "healthy": false,
      "faultCode": "SENSOR_ERROR"
    }
  ]
}
```

**Dock state values in telemetry:** `OCCUPIED | AVAILABLE | UNLOCKING | FAULT`

**Backend behavior:**
- Update `Station.last_telemetry_at` — used by station heartbeat monitoring to detect downed stations
- If station was `INACTIVE` (flagged as down), restore it to `ACTIVE`
- Reconcile each dock in the snapshot against DB state — on discrepancy, update DB to match physical reality (telemetry wins)
- Do not end rides from telemetry — only explicit `BIKE_DOCKED` events do that (stale ride reconciliation via two-snapshot confirmation is a planned enhancement)

---

## Idempotency Requirements

| Event | Idempotency Rule |
|-------|-----------------|
| `UNLOCK_RESULT` | Skip if `Command` not in `PENDING` state |
| `BIKE_DOCKED` | Skip if no active ride for `bikeId` |
| `BIKE_UNDOCKED` | Skip if dock already `AVAILABLE` |
| `DOCK_FAULT` | Safe to re-apply (overwrite fault_code) |
| `DOCK_FAULT_CLEARED` | Safe to re-apply |

---

## Local Development Setup

```
# Mosquitto config: mosquitto/config/mosquitto.conf
listener 1883
allow_anonymous true
```

Backend env vars for local:
```
MQTT_BROKER_TYPE=local
MQTT_BROKER_HOST=mosquitto   # or localhost if running outside Docker
MQTT_BROKER_PORT=1883
```

The station simulator (`simulator/station_sim/`) connects to Mosquitto and implements the full station behavior.

---

## Command Correlation Diagram

```
Backend publishes:
  station/S001/cmd  →  { type: UNLOCK, requestId: "abc", dockId: 1, bikeId: "B742" }

Station responds:
  station/S001/events  →  { type: UNLOCK_RESULT, requestId: "abc", status: "SUCCESS" }
                                                             ↑
                                          Backend uses this to find Command record
```
