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


def test_prefetch_skips_cached_items():
    c = PredictiveCache(4, prefetch_fraction=0.5)  # budget 2
    c.request(1)
    c.prefetch([1, 2, 3, 4])
    assert 2 in c and 3 in c and 4 not in c


def test_prefetch_keeps_top_cached_prediction():
    c = PredictiveCache(4, prefetch_fraction=0.5)  # budget 2
    for k in (1, 2, 3, 4):  # 1 is the LRU tail
        c.request(k)
    c.prefetch([1, 8, 9])
    assert 1 in c and 8 in c and 9 in c


def test_hybrid_is_lru_based_and_reserves_uncached():
    c = HybridCache(4, prefetch_fraction=0.25)  # 3 LRU slots + 1 reserved
    for k in [1, 2, 3, 1, 4]:  # LRU evicts 2 (least recent), not by frequency
        c.request(k)
    assert c.request(2) is False
    c.prefetch([1, 4, 9])  # 1 and 4 are already in LRU, so 9 gets the reserved slot
    assert c.request(9) is True


def test_byte_hit_rate_counts_sizes():
    c = LRUCache(2)
    c.request(1, 100); c.request(1, 100); c.request(2, 900)
    assert c.byte_hit_rate == pytest.approx(100 / 1100)


def test_byte_hit_rate_zero_without_bytes():
    c = HybridCache(10)
    c.request(1)
    assert c.byte_hit_rate == 0.0
