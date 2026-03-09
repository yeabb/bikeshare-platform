# System Architecture

## Component Overview

```mermaid
graph TD

%% Mobile Clients
AND[Android App] -->|HTTPS + JWT| R53[Route 53: api.bikeshare.com]
IOS[iOS App] -->|HTTPS + JWT| R53
USIM[User Simulator] -->|HTTPS + JWT| R53

%% Edge
R53 --> ALB[Application Load Balancer]
ALB --> ECS[Django Backend API]

%% Backend → DB and IoT
ECS -->|1. Create Command PENDING| DB[(PostgreSQL)]
ECS -->|2. Publish UNLOCK cmd| IOT[AWS IoT Core]

%% Device layer
IOT -->|Deliver UNLOCK cmd| SSIM[Station Simulator]
IOT -->|Deliver UNLOCK cmd| STN[Real Stations - nRF9160, later]

SSIM -->|UNLOCK_RESULT event| IOT
SSIM -->|BIKE_DOCKED event| IOT
SSIM -->|BIKE_UNDOCKED event| IOT
SSIM -->|Telemetry| IOT

%% Event ingestion
IOT --> RULE[IoT Rule]
RULE --> LAMBDA[Lambda: Event Ingestion]
LAMBDA -->|Update Command state| DB
LAMBDA -->|Start / End Ride| DB
LAMBDA -->|Update Dock + Bike state| DB

%% Client polling
AND -->|GET /commands/requestId| ECS
IOS -->|GET /commands/requestId| ECS
ECS -->|Read command + ride status| DB

%% Timeout job
TIMEOUT[Scheduled Job / Celery Beat] -->|Mark expired PENDING → TIMEOUT| DB

%% Local dev alternative
LMQTT[Mosquitto - local dev] -.->|replaces IoT Core| LSUB[Local Event Subscriber]
LSUB -.->|calls event_handler directly| ECS
```

## Unlock + Ride Lifecycle (Sequence)

```mermaid
sequenceDiagram
    participant App as Mobile App
    participant API as Django API
    participant DB as PostgreSQL
    participant MQTT as IoT Core / Mosquitto
    participant Sim as Station Simulator
    participant Ingest as Lambda / Local Subscriber

    App->>API: POST /api/v1/commands/unlock {bike_id}
    API->>DB: Lookup bike → dock → station
    API->>DB: Create Command [PENDING]
    API->>MQTT: Publish station/{id}/cmd UNLOCK
    API-->>App: 202 {request_id, status: PENDING}

    App->>API: GET /api/v1/commands/{request_id}  [polls]

    MQTT->>Sim: Deliver UNLOCK command
    Sim->>Sim: Attempt latch release

    alt Unlock succeeds
        Sim->>MQTT: Publish UNLOCK_RESULT {status: SUCCESS}
        MQTT->>Ingest: Trigger on station/{id}/events
        Ingest->>DB: Command → SUCCESS
        Ingest->>DB: Create Ride [ACTIVE]
        Ingest->>DB: Bike → IN_USE
        Ingest->>DB: Dock → UNLOCKING
        App->>API: GET /commands/{request_id}
        API-->>App: {status: SUCCESS, ride_id: ...}
    else Unlock fails
        Sim->>MQTT: Publish UNLOCK_RESULT {status: FAILED}
        MQTT->>Ingest: Trigger
        Ingest->>DB: Command → FAILED
        Ingest->>DB: Dock → OCCUPIED (restore)
        App->>API: GET /commands/{request_id}
        API-->>App: {status: FAILED, failure_reason: ...}
    else No response (timeout)
        Note over API,DB: Scheduled job marks PENDING commands<br/>past expires_at as TIMEOUT
    end

    Note over Sim: Bike physically leaves dock
    Sim->>MQTT: Publish BIKE_UNDOCKED
    MQTT->>Ingest: Trigger
    Ingest->>DB: Dock → AVAILABLE
```

## Ride End (Sequence)

```mermaid
sequenceDiagram
    participant Sim as Station Simulator
    participant MQTT as IoT Core / Mosquitto
    participant Ingest as Lambda / Local Subscriber
    participant DB as PostgreSQL
    participant App as Mobile App
    participant API as Django API

    Note over Sim: Bike physically enters dock (sensor)
    Sim->>MQTT: Publish BIKE_DOCKED {stationId, dockId, bikeId}
    MQTT->>Ingest: Trigger on station/{id}/events
    Ingest->>DB: Lookup active Ride by bikeId
    Ingest->>DB: Ride → COMPLETED, ended_at = now
    Ingest->>DB: Bike → AVAILABLE, current_station/dock updated
    Ingest->>DB: Dock → OCCUPIED, current_bike = bikeId

    App->>API: GET /api/v1/me/active-ride
    API-->>App: 404 NO_ACTIVE_RIDE  (ride is now COMPLETED)
```

## Internal Code Flow (Unlock)

How a single unlock request flows through the backend code modules. This is the same regardless of whether you're running locally or in production — only the entry/exit points change.

```mermaid
flowchart TD

    subgraph HTTP ["HTTP Layer"]
        VIEW["UnlockCommandView\nviews.py"]
    end

    subgraph CMD ["commands app"]
        CS["create_unlock_command()\nservices.py\n\n• Guard: active ride?\n• Guard: pending command?\n• Lookup bike → dock → station\n• Create Command PENDING\n• Dock → UNLOCKING"]
        HUR["handle_unlock_result()\nservices.py\n\n• Idempotency check\n• Command → SUCCESS / FAILED\n• On FAILED: Dock → OCCUPIED"]
    end

    subgraph IOT ["iot app"]
        PUB["publish_unlock_command()\npublisher.py\n\n• Serialize payload\n• Publish to MQTT broker"]
        EH["handle_station_event()\nevent_handler.py\n\n• Parse event type\n• Route to correct handler"]
        HUR2["_handle_unlock_result()\nevent_handler.py\n\n• Extract requestId, status, reason\n• Call commands service"]
        HBD["_handle_bike_docked()\nevent_handler.py\n\n• Extract bikeId, stationId, dockId\n• Call rides service"]
        HBUD["_handle_bike_undocked()\nevent_handler.py\n\n• Extract stationId, dockId\n• Call stations service"]
    end

    subgraph RIDES ["rides app"]
        SR["start_ride()\nservices.py\n\n• Create Ride ACTIVE\n• Bike → IN_USE"]
        ER["end_ride_on_dock()\nservices.py\n\n• Idempotency check\n• Ride → COMPLETED\n• Bike → AVAILABLE\n• Dock → OCCUPIED"]
    end

    subgraph STATIONS ["stations app"]
        HBU["handle_bike_undocked()\nservices.py\n\n• Dock → AVAILABLE\n• Clear Dock.current_bike"]
    end

    subgraph ENTRY ["Entry Points (environment-dependent)"]
        LOCAL["mqtt_listener\nmanagement command\nlocal dev only"]
        LAMBDA["AWS Lambda\nEvent Ingestion\nproduction only"]
    end

    DB[("PostgreSQL")]

    %% Unlock request path
    VIEW -->|"bike_id"| CS
    CS -->|"Command obj"| PUB
    CS -->|"write"| DB
    PUB -->|"MQTT: station/id/cmd"| MQTT[["MQTT Broker\nMosquitto / IoT Core"]]

    %% Event ingestion path
    MQTT -->|"station/id/events"| LOCAL
    MQTT -->|"station/id/events"| LAMBDA
    LOCAL -->|"station_id + payload"| EH
    LAMBDA -->|"station_id + payload"| EH

    %% Event routing
    EH --> HUR2
    EH --> HBD
    EH --> HBUD

    %% Handler → service calls
    HUR2 -->|"request_id, status, reason"| HUR
    HBD -->|"bike_id, station_id, dock_index"| ER
    HBUD -->|"station_id, dock_index"| HBU

    %% Service → service calls
    HUR -->|"On SUCCESS"| SR

    %% DB writes
    SR -->|"write"| DB
    HUR -->|"write"| DB
    ER -->|"write"| DB
    HBU -->|"write"| DB
```

### What each layer is responsible for

| Layer | File | Knows about | Does NOT know about |
|-------|------|-------------|---------------------|
| View | `commands/views.py` | HTTP request/response | MQTT, DB |
| Command service | `commands/services.py` | Business rules, DB | MQTT payload format |
| IoT publisher | `iot/publisher.py` | MQTT protocol | Business rules |
| Event handler | `iot/event_handler.py` | MQTT payload fields | Business rules, DB |
| Ride service | `rides/services.py` | Ride/Bike/Dock state | MQTT, HTTP |
| Station service | `stations/services.py` | Dock state | MQTT, HTTP, Rides |

## Bike → Dock Mapping (Critical)

The user scans the **bike** QR code, not the dock. The backend maintains this mapping:

```
bike_id → (station_id, dock_id, status)
```

This mapping is updated by:
- `BIKE_DOCKED` event → bike now at new station/dock
- `BIKE_UNDOCKED` event → bike no longer at dock
- `UNLOCK_RESULT SUCCESS` → bike transitions to IN_USE

**The station must always include `bikeId` in `BIKE_DOCKED` events.** This is how the backend correlates a docking event to the active ride.

## Local Development

In local development AWS IoT Core and Lambda are replaced by two local processes:

| Production | Local equivalent |
|------------|-----------------|
| AWS IoT Core | Mosquitto (Docker) |
| Lambda ingestion function | `python manage.py mqtt_listener` — subscribes to `station/+/events`, calls `event_handler` directly |
| Real station hardware | `python -m station_sim.main` — simulates a fleet of stations, subscribes to `station/+/cmd`, publishes events back |

The backend publishes to Mosquitto via paho-mqtt (`MQTT_BROKER_TYPE=local`). Everything else — models, services, event_handler — is identical between local and production.

**Starting the full local stack:**
```bash
make setup   # first time only
make dev     # starts everything
```

**Fleet config:** `simulator/fleet.yml` defines stations, docks, bikes, and behavior modes.
Each station has a configurable behavior: `always_success`, `always_fail`, `flaky`, `slow`, `timeout`.

## Key Design Constraints

| Constraint | Why |
|------------|-----|
| Ride starts only on UNLOCK_RESULT SUCCESS | Never create a ride for a locked bike |
| Ride ends only on BIKE_DOCKED event | HTTP-based end would require trusting the client |
| Command is idempotent | Duplicate UNLOCK_RESULT events must not create duplicate rides |
| BIKE_DOCKED is idempotent | Already-completed rides must be ignored |
| bikeId in all dock events | Required to map events back to rides |
| Command has expires_at | Prevents permanently stuck PENDING commands |
