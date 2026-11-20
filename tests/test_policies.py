import pytest
from pcache.policies import LRUCache, LFUCache, PredictiveCache, HybridCache


def test_lru_evicts_oldest():
    c = LRUCache(2)
    c.request(1); c.request(2); c.request(1); c.request(3)
    assert 1 in c and 3 in c and 2 not in c


def test_hit_rate():
    c = LRUCache(2)
    for k in [1, 1, 1, 2]:
        c.request(k)
    assert c.hit_rate == 0.5


def test_lfu_keeps_frequent():
    c = LFUCache(1)
    for k in [1, 1, 2]:
        c.request(k)
    assert c.request(1) is True


def test_prefetch_creates_hit():
    c = PredictiveCache(4)
    c.prefetch([9])
    assert c.request(9) is True


def test_hybrid_prefetch_hit():
    c = HybridCache(8)
    c.prefetch([5])
    assert c.request(5) is True


def test_bad_capacity():
    with pytest.raises(ValueError):
        LRUCache(0)
