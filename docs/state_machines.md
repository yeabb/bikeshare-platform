# State Machines

## Command States

Commands track the lifecycle of a station instruction (currently only `UNLOCK`).

```
           ┌─────────────────────────────────────────────────────┐
           │                    PENDING                          │
           │   (Command published to MQTT, awaiting response)    │
           └──────────────────────┬──────────────────────────────┘
                                  │
               ┌──────────────────┼──────────────────┐
               ▼                  ▼                  ▼
          ┌─────────┐       ┌─────────┐       ┌─────────┐
          │ SUCCESS │       │ FAILED  │       │ TIMEOUT │
          └─────────┘       └─────────┘       └─────────┘
         (terminal)         (terminal)         (terminal)
```

### Transition Table

| From | Trigger | To | Side Effects |
|------|---------|-----|-------------|
| `PENDING` | `UNLOCK_RESULT` event with `status=SUCCESS` | `SUCCESS` | Create Ride, Bike→IN_USE |
| `PENDING` | `UNLOCK_RESULT` event with `status=FAILED` | `FAILED` | Dock→OCCUPIED (restore) |
| `PENDING` | `expires_at` elapsed (background job) | `TIMEOUT` | — |

### Rules

- Only `PENDING` commands can transition. `SUCCESS`, `FAILED`, and `TIMEOUT` are **terminal**.
- Duplicate `UNLOCK_RESULT` events for a resolved command are **silently ignored** (idempotency).
- `PENDING_COMMAND_EXISTS` error prevents duplicate commands per user.
- `expires_at = created_at + ttlSec` (default 10s). A scheduled job sweeps for expired commands.

---

## Ride States

Rides track the physical bike usage by a rider.

```
           ┌──────────────────────────────────────────────────┐
           │  [created by start_ride() on Command SUCCESS]    │
           │                   ACTIVE                         │
           │          (Bike is in use by rider)               │
           └────────────────────┬─────────────────────────────┘
                                │
                   ┌────────────┴────────────┐
                   ▼                         ▼
           ┌───────────────┐        ┌──────────────┐
           │   COMPLETED   │        │    FAILED    │
           │ (bike docked) │        │ (admin only) │
           └───────────────┘        └──────────────┘
              (terminal)               (terminal)
```

### Transition Table

| From | Trigger | To | Side Effects |
|------|---------|-----|-------------|
| [none] | `Command` reaches `SUCCESS` | `ACTIVE` | Bike→IN_USE, Bike.current_ride set |
| `ACTIVE` | `BIKE_DOCKED` event for this bike | `COMPLETED` | Bike→AVAILABLE, Dock→OCCUPIED, end_station/dock set |
| `ACTIVE` | Admin action | `FAILED` | Reserved for ops use |

### Rules

- **One active ride per user** — enforced at command creation time.
- Ride is created only after `UNLOCK_RESULT SUCCESS` — never speculatively.
- Ride ends only on `BIKE_DOCKED` — client cannot end a ride via HTTP.
- `BIKE_DOCKED` for a bike with no active ride is a no-op (idempotent).

---

## Dock States

Docks track the physical state of a dock slot.

```
  OCCUPIED ◄──────────────────────── BIKE_DOCKED event
     │                                       ▲
     │ UNLOCK cmd published                  │
     ▼                                       │
  UNLOCKING ──── UNLOCK_RESULT SUCCESS ──► AVAILABLE
     │                                       │
     └──── UNLOCK_RESULT FAILED ─────────► OCCUPIED (restore)

  Any state ──── DOCK_FAULT event ─────────► FAULT
  FAULT ──────── DOCK_FAULT_CLEARED ──────► AVAILABLE or OCCUPIED
                                              (based on bike presence)
```

### Transition Table

| From | Trigger | To |
|------|---------|-----|
| `OCCUPIED` | UNLOCK command published | `UNLOCKING` |
| `UNLOCKING` | `UNLOCK_RESULT SUCCESS` + bike departs | `AVAILABLE` (via BIKE_UNDOCKED) |
| `UNLOCKING` | `UNLOCK_RESULT FAILED` | `OCCUPIED` |
| `AVAILABLE` | `BIKE_DOCKED` event | `OCCUPIED` |
| Any | `DOCK_FAULT` event | `FAULT` |
| `FAULT` | `DOCK_FAULT_CLEARED` | `AVAILABLE` or `OCCUPIED` |

### Notes

- `UNLOCKING` is a transitional state. Duration is bounded by `ttlSec`.
- On `UNLOCK_RESULT SUCCESS`, dock moves to `UNLOCKING` first, then `AVAILABLE` on `BIKE_UNDOCKED`.
- Dock can receive `BIKE_DOCKED` from `AVAILABLE` state (normal docking after a ride).

---

## Bike States

Bikes track ridability status.

```
  AVAILABLE ──── start_ride() ──────────────► IN_USE
     ▲                                          │
     └──────────── end_ride_on_dock() ──────────┘

  Any ─────────── Admin action ─────────────► MAINTENANCE
  Any ─────────── Admin action ─────────────► LOST
  MAINTENANCE/LOST ── Admin action ─────────► AVAILABLE
```

### Transition Table

| From | Trigger | To |
|------|---------|-----|
| `AVAILABLE` | `Ride` created (Command SUCCESS) | `IN_USE` |
| `IN_USE` | `Ride` completed (BIKE_DOCKED) | `AVAILABLE` |
| Any | Admin action | `MAINTENANCE` |
| Any | Admin action | `LOST` |
| `MAINTENANCE` or `LOST` | Admin action | `AVAILABLE` |

### Rules

- Only `AVAILABLE` bikes can be unlocked (enforced at command creation).
- `IN_USE` → `AVAILABLE` transition happens in `end_ride_on_dock()`, not directly.

---

## State Consistency Guarantees

The following invariants must always hold:

| Invariant | Enforced By |
|-----------|-------------|
| A `PENDING` command → dock is in `UNLOCKING` state | `create_unlock_command()` |
| An `ACTIVE` ride → bike is `IN_USE` | `start_ride()` |
| A `COMPLETED` ride → bike is `AVAILABLE` + dock is `OCCUPIED` | `end_ride_on_dock()` |
| `Bike.current_dock` and `Dock.current_bike` agree | Both updated atomically in service calls |
| No two active rides for the same user | Checked in `create_unlock_command()` |
| No two active rides for the same bike | Enforced by `Bike.current_ride` uniqueness + status check |
