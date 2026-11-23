"""ผังกล้องของอาคาร (topology.toml)"""

from __future__ import annotations

import heapq
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ROLES = ("entry", "exit", "internal")


@dataclass(frozen=True)
class LinkerConfig:
    similar_max_distance: float = 1.0
    guess_min_similarity: float = 0.80
    guess_margin: float = 0.05
    same_camera_gap_seconds: float = 60
    journey_idle_hours: float = 24
    settle_seconds: float = 5


@dataclass(frozen=True)
class Edge:
    min_seconds: float
    max_seconds: float


@dataclass
class Topology:
    roles: dict[str, str]
    edges: dict[str, dict[str, Edge]] = field(default_factory=dict)
    config: LinkerConfig = field(default_factory=LinkerConfig)

    @classmethod
    def load(cls, path: Path) -> Topology:
        return cls.from_dict(tomllib.loads(path.read_text(encoding="utf-8")))

    @classmethod
    def from_dict(cls, data: dict) -> Topology:
        roles = {}
        for cam, spec in data.get("cameras", {}).items():
            role = spec.get("role", "internal")
            if role not in ROLES:
                raise ValueError(f"camera {cam}: role must be one of {ROLES}")
            roles[cam] = role
        topo = cls(roles=roles, config=LinkerConfig(**data.get("linker", {})))
        for i, link in enumerate(data.get("links", [])):
            a, b = link["a"], link["b"]
            for cam in (a, b):
                if cam not in roles:
                    raise ValueError(f"links[{i}]: camera {cam!r} is not listed under [cameras]")
            edge = Edge(float(link["min_seconds"]), float(link["max_seconds"]))
            if not 0 <= edge.min_seconds <= edge.max_seconds:
                raise ValueError(f"links[{i}]: need 0 <= min_seconds <= max_seconds")
            topo.edges.setdefault(a, {})[b] = edge
            if link.get("both_ways", False):
                topo.edges.setdefault(b, {})[a] = edge
        return topo

    def knows(self, camera: str) -> bool:
        return camera in self.roles

    def is_exit(self, camera: str) -> bool:
        return self.roles.get(camera) == "exit"

    def fastest(self, a: str, b: str) -> float | None:
        """เวลาน้อยที่สุดที่รถจะไปจาก a ถึง b (ผ่านกล้องอื่นได้) หรือ None ถ้าไม่มีทาง"""
        if a == b:
            return 0.0
        best = {a: 0.0}
        heap = [(0.0, a)]
        while heap:
            t, cam = heapq.heappop(heap)
            if cam == b:
                return t
            if t > best.get(cam, float("inf")):
                continue
            for nxt, edge in self.edges.get(cam, {}).items():
                nt = t + edge.min_seconds
                if nt < best.get(nxt, float("inf")):
                    best[nxt] = nt
                    heapq.heappush(heap, (nt, nxt))
        return None

    def direct(self, a: str, b: str) -> Edge | None:
        return self.edges.get(a, {}).get(b)
