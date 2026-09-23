"""Leituras do diretório com cache curto (evita chamadas repetidas ao Graph)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from app.graph.models import TenantSnapshot
from app.graph.service import GraphService


class DirectoryCache:
    def __init__(self, graph: GraphService, ttl_seconds: int = 300, clock=time.monotonic) -> None:
        self.graph = graph
        self.ttl = ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._data: dict[str, tuple[float, Any]] = {}

    def _cached(self, key: str, loader: Callable[[], Any], refresh: bool) -> Any:
        now = self._clock()
        with self._lock:
            hit = self._data.get(key)
            if hit and not refresh and now - hit[0] < self.ttl:
                return hit[1]
        value = loader()
        with self._lock:
            self._data[key] = (now, value)
        return value

    def groups(self, refresh: bool = False):
        return self._cached("groups", self.graph.list_groups, refresh)

    def skus(self, refresh: bool = False):
        return self._cached("skus", self.graph.list_subscribed_skus, refresh)

    def snapshot(self, refresh: bool = False) -> TenantSnapshot:
        return self._cached(
            "snapshot",
            lambda: TenantSnapshot(
                organization=self.graph.get_organization(),
                domains=self.graph.list_domains(),
                skus=self.skus(refresh),
                tap_policy=self.graph.get_tap_policy(),
                groups=self.groups(refresh),
            ),
            refresh,
        )

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
