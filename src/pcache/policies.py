"""Cache policies sharing one interface."""
from __future__ import annotations
from collections import OrderedDict, Counter
from itertools import islice
from typing import Iterable


class CachePolicy:
    name = "base"

    def __init__(self, capacity: int):
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self.hits = 0
        self.requests = 0
        self.bytes_hit = 0
        self.bytes_requested = 0

    def request(self, key: int, size: int = 0) -> bool:
        raise NotImplementedError

    def _count(self, hit: bool, size: int) -> bool:
        """Record one request of `size` bytes; returns `hit`."""
        self.requests += 1
        self.bytes_requested += size
        if hit:
            self.hits += 1
            self.bytes_hit += size
        return hit

    def prefetch(self, keys: Iterable[int]) -> None:
        """Optional hook: load keys ahead of demand."""

    @property
    def hit_rate(self) -> float:
        return self.hits / self.requests if self.requests else 0.0

    @property
    def byte_hit_rate(self) -> float:
        return self.bytes_hit / self.bytes_requested if self.bytes_requested else 0.0


class LRUCache(CachePolicy):
    name = "LRU"

    def __init__(self, capacity: int):
        super().__init__(capacity)
        self._store: OrderedDict[int, None] = OrderedDict()

    def _insert(self, key: int) -> None:
        self._store[key] = None
        self._store.move_to_end(key)
        while len(self._store) > self.capacity:
            self._store.popitem(last=False)

    def request(self, key: int, size: int = 0) -> bool:
        if key in self._store:
            self._store.move_to_end(key)
            return self._count(True, size)
        self._insert(key)
        return self._count(False, size)

    def __contains__(self, key: int) -> bool:
        return key in self._store


class LFUCache(CachePolicy):
    name = "LFU"

    def __init__(self, capacity: int):
        super().__init__(capacity)
        self._store: set[int] = set()
        self._freq: Counter[int] = Counter()

    def request(self, key: int, size: int = 0) -> bool:
        self._freq[key] += 1
        if key in self._store:
            return self._count(True, size)
        if len(self._store) >= self.capacity:
            victim = min(self._store, key=self._freq.__getitem__)
            if self._freq[victim] > self._freq[key]:
                return self._count(False, size)
            self._store.remove(victim)
        self._store.add(key)
        return self._count(False, size)


class PredictiveCache(LRUCache):
    """LRU cache pre-warmed with model-predicted hot items each hour."""
    name = "Predictive"

    def __init__(self, capacity: int, prefetch_fraction: float = 0.5):
        super().__init__(capacity)
        self.prefetch_size = max(1, int(capacity * prefetch_fraction))

    def prefetch(self, keys: Iterable[int]) -> None:
        """`keys` ranked best first; the budget counts only uncached items, cached ones are refreshed."""
        chosen, budget = [], self.prefetch_size
        for k in keys:
            if budget == 0 or len(chosen) == self.capacity:
                break
            budget -= k not in self._store
            chosen.append(k)
        for k in reversed(chosen):  # best ranked ends most recent, so it is evicted last
            self._insert(k)


class HybridCache(CachePolicy):
    """LRU for recent items + a reserved share holding predicted items the LRU part lacks."""
    name = "Hybrid"

    def __init__(self, capacity: int, prefetch_fraction: float = 0.10):
        super().__init__(capacity)
        self.prefetch_size = max(1, int(capacity * prefetch_fraction))
        self._lru = LRUCache(max(1, capacity - self.prefetch_size))
        self._hot: set[int] = set()

    def prefetch(self, keys: Iterable[int]) -> None:
        """`keys` ranked best first; reserve slots only for items the LRU part does not hold."""
        self._hot = set(islice((k for k in keys if k not in self._lru), self.prefetch_size))

    def request(self, key: int, size: int = 0) -> bool:
        if key in self._hot:  # served from the reserved share; not copied into LRU (no duplicate slot)
            return self._count(True, size)
        return self._count(self._lru.request(key, size), size)
