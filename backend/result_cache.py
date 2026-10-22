"""
Bounded LRU + TTL cache of verdicts for repeated identical claims. Saves cloud-LLM calls and latency.
In-process state: one uvicorn worker per container (see backend/main.py).
"""
import re
import threading
import time
from collections import OrderedDict
from typing import Optional, Tuple

from backend import config
from backend.models.schemas import VerificationResponse

# Results produced while a configured cloud judge was unavailable are not cached: a transient
# outage should not pin the weaker offline verdict for hours.
_UNCACHEABLE_NOTES = ("Cloud judge unavailable", "Daily cloud-judge budget reached")


def _now() -> float:
    return time.monotonic()


def normalize_claim(claim: str) -> str:
    text = re.sub(r"\s+", " ", (claim or "").strip().lower())
    return text.rstrip(" .!?;:,")


class ResultCache:
    def __init__(self):
        self._data: "OrderedDict[Tuple[str, str], Tuple[float, VerificationResponse]]" = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: Tuple[str, str]) -> Optional[VerificationResponse]:
        if config.CACHE_TTL_S <= 0:
            return None
        with self._lock:
            item = self._data.get(key)
            if not item:
                return None
            stored_at, response = item
            if _now() - stored_at > config.CACHE_TTL_S:
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return response.model_copy(deep=True)

    def put(self, key: Tuple[str, str], response: VerificationResponse) -> bool:
        if config.CACHE_TTL_S <= 0:
            return False
        if any(l.startswith(_UNCACHEABLE_NOTES) for l in response.limitations):
            return False
        with self._lock:
            self._data[key] = (_now(), response.model_copy(deep=True))
            self._data.move_to_end(key)
            while len(self._data) > max(1, config.CACHE_MAX_ENTRIES):
                self._data.popitem(last=False)
        return True

    def clear(self):
        with self._lock:
            self._data.clear()

    def __len__(self):
        return len(self._data)


result_cache = ResultCache()
