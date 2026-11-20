"""Cache policies sharing one interface."""
from __future__ import annotations
from collections import OrderedDict, Counter
from typing import Iterable


class CachePolicy:
    name = "base"

    def __init__(self, capacity: int):
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self.hits = 0
        self.requests = 0

    def request(self, key: int) -> bool:
        raise NotImplementedError

    def prefetch(self, keys: Iterable[int]) -> None:
        """Optional hook: load keys ahead of demand."""

    @property
    def hit_rate(self) -> float:
        return self.hits / self.requests if self.requests else 0.0


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

    def request(self, key: int) -> bool:
        self.requests += 1
        if key in self._store:
            self.hits += 1
            self._store.move_to_end(key)
            return True
        self._insert(key)
        return False

    def __contains__(self, key: int) -> bool:
        return key in self._store


class LFUCache(CachePolicy):
    name = "LFU"

    def __init__(self, capacity: int):
        super().__init__(capacity)
        self._store: set[int] = set()
        self._freq: Counter[int] = Counter()

    def request(self, key: int) -> bool:
        self.requests += 1
        self._freq[key] += 1
        if key in self._store:
            self.hits += 1
            return True
        if len(self._store) >= self.capacity:
            victim = min(self._store, key=self._freq.__getitem__)
            if self._freq[victim] > self._freq[key]:
                return False
            self._store.remove(victim)
        self._store.add(key)
        return False


class PredictiveCache(LRUCache):
    """LRU cache pre-warmed with model-predicted hot items each hour."""
    name = "Predictive"

    def __init__(self, capacity: int, prefetch_fraction: float = 0.5):
        super().__init__(capacity)
        self.prefetch_size = max(1, int(capacity * prefetch_fraction))

    def prefetch(self, keys: Iterable[int]) -> None:
        for k in list(keys)[: self.prefetch_size]:
            self._insert(k)


class HybridCache(CachePolicy):
    """LFU for steady favourites + a reserved slot filled with model-predicted trending items."""
    name = "Hybrid"

    def __init__(self, capacity: int, prefetch_fraction: float = 0.25):
        super().__init__(capacity)
        self.prefetch_size = max(1, int(capacity * prefetch_fraction))
        self._lfu = LFUCache(max(1, capacity - self.prefetch_size))
        self._hot: set[int] = set()

    def prefetch(self, keys: Iterable[int]) -> None:
        self._hot = set(list(keys)[: self.prefetch_size])

    def request(self, key: int) -> bool:
        self.requests += 1
        in_lfu = self._lfu.request(key)
        if in_lfu or key in self._hot:
            self.hits += 1
            return True
        return False
