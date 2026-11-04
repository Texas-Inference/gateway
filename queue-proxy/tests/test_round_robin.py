"""Unit tests for the pure round-robin primitives (no external deps).

Run:  python3 queue-proxy/tests/test_round_robin.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models import Job  # noqa: E402
from app.rr import RoundRobinState, WindowCounter  # noqa: E402


def J(key_id, i=0):
    return Job(
        job_id=f"{key_id}-{i}",
        user_id="u1",
        key_id=key_id,
        path="/v1/chat/completions",
        headers={},
        body=b"{}",
    )


def test_interleaves_across_keys():
    rr = RoundRobinState()
    for k in ("k1", "k2", "k3"):
        for i in range(3):
            rr.enqueue(J(k, i))
    order = [rr.pick(lambda _k: True).key_id for _ in range(9)]
    assert order == ["k1", "k2", "k3"] * 3, order
    assert rr.depth() == 0
    print("test_interleaves_across_keys OK")


def test_skips_key_without_capacity():
    rr = RoundRobinState()
    for k in ("k1", "k2"):
        rr.enqueue(J(k, 0))
        rr.enqueue(J(k, 1))
    # k1 has no capacity -> only k2 should be served until empty
    picked = []
    while True:
        job = rr.pick(lambda k: k != "k1")
        if job is None:
            break
        picked.append(job.key_id)
    assert picked == ["k2", "k2"], picked
    print("test_skips_key_without_capacity OK")


def test_fair_with_uneven_queues():
    rr = RoundRobinState()
    # k1 has 5 jobs, k2 has 1: k2 must not be starved; k1,k2,k1,k1,k1 interleaved-ish
    for i in range(5):
        rr.enqueue(J("k1", i))
    rr.enqueue(J("k2", 0))
    picked = []
    while True:
        job = rr.pick(lambda _k: True)
        if job is None:
            break
        picked.append(job.key_id)
    assert picked[0] == "k1" and picked[1] == "k2", picked
    assert picked.count("k2") == 1 and picked.count("k1") == 5, picked
    print("test_fair_with_uneven_queues OK")


def test_window_counter():
    w = WindowCounter(0.05)
    for _ in range(3):
        w.hit()
    assert w.count == 3
    import time

    time.sleep(0.06)
    assert w.count == 0
    print("test_window_counter OK")


if __name__ == "__main__":
    test_interleaves_across_keys()
    test_skips_key_without_capacity()
    test_fair_with_uneven_queues()
    test_window_counter()
    print("ALL TESTS PASSED")
