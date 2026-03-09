"""
Loads and validates fleet.yml into plain dataclasses.
Both the simulator and the seed script reference this structure.
"""
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class DockConfig:
    index: int
    bike_id: Optional[str]


@dataclass
class StationConfig:
    id: str
    name: str
    lat: float
    lng: float
    behavior: str               # always_success | always_fail | flaky | slow | timeout
    docks: list[DockConfig]
    failure_reason: str = "LATCH_FAULT"
    fail_rate: float = 0.3      # used only when behavior=flaky
    delay_sec: float = 3.0      # used only when behavior=slow


@dataclass
class UserConfig:
    phone: str


@dataclass
class FleetConfig:
    stations: list[StationConfig]
    users: list[UserConfig]


def load_fleet(path: Path) -> FleetConfig:
    with open(path) as f:
        raw = yaml.safe_load(f)

    stations = []
    for s in raw.get("stations", []):
        docks = [
            DockConfig(index=d["index"], bike_id=d.get("bike_id"))
            for d in s.get("docks", [])
        ]
        stations.append(
            StationConfig(
                id=s["id"],
                name=s["name"],
                lat=s["lat"],
                lng=s["lng"],
                behavior=s["behavior"],
                docks=docks,
                failure_reason=s.get("failure_reason", "LATCH_FAULT"),
                fail_rate=s.get("fail_rate", 0.3),
                delay_sec=s.get("delay_sec", 3.0),
            )
        )

    users = [UserConfig(phone=u["phone"]) for u in raw.get("users", [])]

    return FleetConfig(stations=stations, users=users)
