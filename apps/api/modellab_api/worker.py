"""Optional Dramatiq worker. Start it with: dramatiq modellab_api.worker"""
from __future__ import annotations

import os

_actor = None


def _setup():
    global _actor
    if _actor is not None or not os.environ.get("REDIS_URL"):
        return _actor
    try:
        import dramatiq
        from dramatiq.brokers.redis import RedisBroker
    except ImportError:
        return None
    dramatiq.set_broker(RedisBroker(url=os.environ["REDIS_URL"]))

    @dramatiq.actor(max_retries=0, time_limit=24 * 3600 * 1000)
    def run_campaign(run_id: str) -> None:
        from modellab_api.campaigns import execute_run
        from modellab_api.db import get_factory

        execute_run(get_factory(), run_id)

    _actor = run_campaign
    return _actor


def enqueue(run_id: str) -> bool:
    actor = _setup()
    if actor is None:
        return False
    actor.send(run_id)
    return True


_setup()
