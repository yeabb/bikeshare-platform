# Bikeshare API v1

## Overview

- **Base URL:** `/api/v1/`
- **Auth:** JWT Bearer tokens (`Authorization: Bearer <access_token>`)
- **Content-Type:** `application/json`
- **All timestamps:** ISO 8601 UTC (e.g. `2026-03-07T10:00:00Z`)
- **All IDs:** UUIDs unless noted (station/bike IDs are strings like `S001`, `B742`)

Endpoints marked **(auth)** require a valid Bearer token.

---

## Authentication

### POST /api/v1/auth/request-otp

Request an OTP sent to the user's phone. Creates user account if first login.

**Request:**
```json
{ "phone": "+15551234567" }
```

**Response 200:**
```json
{ "message": "OTP sent" }
```

> **Dev only:** When `DEBUG=True`, the OTP is included in the response:
> ```json
> { "message": "OTP sent", "otp": "482910" }
> ```

**Errors:**

| Code | HTTP | Meaning |
|------|------|---------|
| `MISSING_PHONE` | 400 | `phone` field not provided |

---

### POST /api/v1/auth/verify-otp

Verify OTP and receive JWT tokens.

**Request:**
```json
{
  "phone": "+15551234567",
  "otp": "482910"
}
```

**Response 200:**
```json
{
  "access": "<jwt_access_token>",
  "refresh": "<jwt_refresh_token>",
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "phone": "+15551234567"
  }
}
```

**Errors:**

| Code | HTTP | Meaning |
|------|------|---------|
| `MISSING_FIELDS` | 400 | `phone` or `otp` not provided |
| `INVALID_OTP` | 400 | OTP does not match or user not found |
| `OTP_EXPIRED` | 400 | OTP is older than 10 minutes |

---

### POST /api/v1/auth/token/refresh

Refresh an expired access token.

**Request:**
```json
{ "refresh": "<jwt_refresh_token>" }
```

**Response 200:**
```json
{ "access": "<new_jwt_access_token>" }
```

---

## Stations

### GET /api/v1/stations/{station_id}/state

Get current station state including all docks. No auth required (public availability info).

**Path params:** `station_id` — string, e.g. `S001`

**Response 200:**
```json
{
  "station_id": "S001",
  "name": "Market & 5th",
  "status": "ACTIVE",
  "lat": 37.7749000,
  "lng": -122.4194000,
  "docks": [
    {
      "dock_id": "S001-D01",
      "dock_index": 1,
      "state": "OCCUPIED",
      "bike_id": "B742"
    },
    {
      "dock_id": "S001-D02",
      "dock_index": 2,
      "state": "AVAILABLE",
      "bike_id": null
    },
    {
      "dock_id": "S001-D03",
      "dock_index": 3,
      "state": "FAULT",
      "bike_id": null
    }
  ]
}
```

**Station status values:** `ACTIVE | INACTIVE | MAINTENANCE`

**Dock state values:** `AVAILABLE | OCCUPIED | UNLOCKING | FAULT`

**Errors:**

| Code | HTTP | Meaning |
|------|------|---------|
| `NOT_FOUND` | 404 | Station does not exist |

---

## Commands

### POST /api/v1/commands/unlock **(auth)**

Initiate a bike unlock by bike QR code scan. Creates a `PENDING` command and publishes an UNLOCK message to the station via MQTT. Returns immediately — client must poll for status.

**Request:**
```json
{ "bike_id": "B742" }
```

**Business rules enforced:**
- `bike_id` must exist and be `AVAILABLE`
- Bike must be docked (has a known dock and station)
- User must have no `ACTIVE` ride
- User must have no `PENDING` command

**Response 202:**
```json
{
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "type": "UNLOCK",
  "status": "PENDING",
  "bike_id": "B742",
  "station_id": "S001",
  "dock_index": 1,
  "failure_reason": null,
  "created_at": "2026-03-07T10:00:00Z",
  "resolved_at": null,
  "expires_at": "2026-03-07T10:00:10Z"
}
```

**Errors:**

| Code | HTTP | Meaning |
|------|------|---------|
| `MISSING_BIKE_ID` | 400 | `bike_id` not provided |
| `BIKE_NOT_FOUND` | 400 | No bike with this ID |
| `BIKE_NOT_AVAILABLE` | 400 | Bike is IN_USE, MAINTENANCE, or LOST |
| `BIKE_NOT_DOCKED` | 400 | Bike has no associated dock |
| `DOCK_NOT_OCCUPIED` | 400 | Dock state is not OCCUPIED |
| `ACTIVE_RIDE_EXISTS` | 409 | User already has an active ride |
| `PENDING_COMMAND_EXISTS` | 409 | User already has a pending command |

---

### GET /api/v1/commands/{request_id} **(auth)**

Poll command status. User must own the command.

**Path params:** `request_id` — UUID

**Response 200:**
```json
{
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "type": "UNLOCK",
  "status": "SUCCESS",
  "bike_id": "B742",
  "station_id": "S001",
  "dock_index": 1,
  "failure_reason": null,
  "created_at": "2026-03-07T10:00:00Z",
  "resolved_at": "2026-03-07T10:00:03Z",
  "expires_at": "2026-03-07T10:00:10Z",
  "ride_id": "abc12345-e29b-41d4-a716-446655440000"
}
```

**`status` values:**

| Value | Meaning |
|-------|---------|
| `PENDING` | Awaiting station response |
| `SUCCESS` | Station confirmed unlock; `ride_id` is set |
| `FAILED` | Station reported failure; `failure_reason` explains why |
| `TIMEOUT` | No station response within TTL |

**`ride_id`** is non-null only when `status == SUCCESS`.

**Errors:**

| Code | HTTP | Meaning |
|------|------|---------|
| `NOT_FOUND` | 404 | Command not found or not owned by user |

---

## Rides

### GET /api/v1/me/active-ride **(auth)**

Get the current user's active ride.

**Response 200:**
```json
{
  "ride_id": "abc12345-e29b-41d4-a716-446655440000",
  "bike_id": "B742",
  "start_station_id": "S001",
  "start_dock_index": 1,
  "end_station_id": null,
  "end_dock_index": null,
  "started_at": "2026-03-07T10:00:03Z",
  "ended_at": null,
  "status": "ACTIVE",
  "duration_sec": null
}
```

**Errors:**

| Code | HTTP | Meaning |
|------|------|---------|
| `NO_ACTIVE_RIDE` | 404 | User has no active ride |

---

### GET /api/v1/me/rides **(auth)**

Get all rides for current user, ordered newest first.

**Response 200:**
```json
{
  "rides": [
    {
      "ride_id": "abc12345-e29b-41d4-a716-446655440000",
      "bike_id": "B742",
      "start_station_id": "S001",
      "start_dock_index": 1,
      "end_station_id": "S002",
      "end_dock_index": 3,
      "started_at": "2026-03-07T10:00:03Z",
      "ended_at": "2026-03-07T10:35:21Z",
      "status": "COMPLETED",
      "duration_sec": 2118
    }
  ]
}
```

---

### GET /api/v1/me/rides/{ride_id} **(auth)**

Get a specific ride by ID. User must own the ride.

**Response 200:** Same structure as individual ride object above.

**Errors:**

| Code | HTTP | Meaning |
|------|------|---------|
| `NOT_FOUND` | 404 | Ride not found or not owned by user |

---

## Error Response Format

All error responses follow this structure:

```json
{
  "error": "ERROR_CODE",
  "detail": "Human-readable explanation (optional)"
}
```

---

## Polling Strategy (Client Guidance)

After receiving `202` from `/commands/unlock`, the client should:

1. Poll `GET /api/v1/commands/{request_id}` every **1 second**
2. Stop polling when `status` is `SUCCESS`, `FAILED`, or `TIMEOUT`
3. On `SUCCESS`: transition to active ride screen using `ride_id`
4. On `FAILED` or `TIMEOUT`: show error, allow retry

Max wait: `expires_at` + 2s buffer. After that, assume `TIMEOUT`.
