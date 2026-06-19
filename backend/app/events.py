"""Bus d'événements en mémoire : une file asyncio par job pour diffuser les logs en SSE."""
from __future__ import annotations

import asyncio
from typing import AsyncIterator

from .models import LogEvent

# Sentinelle de fin de flux.
_SENTINEL = object()


class JobBus:
    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue] = {}
        # On garde un buffer des événements déjà émis pour qu'un client qui se
        # connecte juste après le démarrage ne rate pas les premières lignes.
        self._history: dict[str, list[LogEvent]] = {}

    def create(self, job_id: str) -> None:
        self._queues[job_id] = asyncio.Queue()
        self._history[job_id] = []

    async def publish(self, event: LogEvent) -> None:
        self._history.setdefault(event.job_id, []).append(event)
        q = self._queues.get(event.job_id)
        if q is not None:
            await q.put(event)
            if event.done:
                await q.put(_SENTINEL)

    async def subscribe(self, job_id: str) -> AsyncIterator[LogEvent]:
        """Renvoie d'abord l'historique, puis les nouveaux événements jusqu'à `done`."""
        q = self._queues.get(job_id)
        if q is None:
            return
        already = list(self._history.get(job_id, []))
        last_done = False
        for ev in already:
            yield ev
            last_done = ev.done
        if last_done:
            return
        while True:
            item = await q.get()
            if item is _SENTINEL:
                return
            yield item

    def cleanup(self, job_id: str) -> None:
        self._queues.pop(job_id, None)
        self._history.pop(job_id, None)


bus = JobBus()
