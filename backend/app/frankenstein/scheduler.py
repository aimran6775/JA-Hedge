"""
Frankenstein — Background Scheduler.

Runs periodic tasks on configurable intervals:
- Model retraining (hourly)
- Performance snapshots (every 5 minutes)
- Strategy adaptation (every 15 minutes)
- Memory persistence (every 30 minutes)
- Health checks (every minute)
- Outcome resolution (every 2 minutes)

All tasks run as asyncio background coroutines and
can be independently started/stopped.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

from app.logging_config import get_logger

log = get_logger("frankenstein.scheduler")


@dataclass
class ScheduledTask:
    """A single scheduled task."""
    name: str
    interval_seconds: float
    callback: Callable[[], Coroutine]
    enabled: bool = True
    last_run: float = 0.0
    run_count: int = 0
    error_count: int = 0
    last_error: str = ""
    avg_duration_ms: float = 0.0
    _task: asyncio.Task | None = field(default=None, repr=False)


class FrankensteinScheduler:
    """
    Background task scheduler for Frankenstein.

    Manages all periodic tasks: retraining, snapshots,
    adaptation, persistence, and health checks.
    """

    def __init__(self):
        self._tasks: dict[str, ScheduledTask] = {}
        self._running = False
        self._start_time: float = 0.0

        log.info("scheduler_initialized")

    def register(
        self,
        name: str,
        callback: Callable[[], Coroutine],
        interval_seconds: float,
        enabled: bool = True,
    ) -> None:
        """Register a periodic task."""
        self._tasks[name] = ScheduledTask(
            name=name,
            interval_seconds=interval_seconds,
            callback=callback,
            enabled=enabled,
        )
        log.info("task_registered", name=name, interval=f"{interval_seconds}s", enabled=enabled)

    async def start(self) -> None:
        """Start all registered tasks."""
        if self._running:
            return

        self._running = True
        self._start_time = time.time()

        for name, task in self._tasks.items():
            if task.enabled:
                task._task = asyncio.create_task(
                    self._run_loop(task),
                    name=f"fk_sched_{name}",
                )

        log.info(
            "🧟 FRANKENSTEIN SCHEDULER STARTED",
            tasks=len(self._tasks),
            active=[n for n, t in self._tasks.items() if t.enabled],
        )

    async def stop(self) -> None:
        """Stop all running tasks."""
        self._running = False

        for name, task in self._tasks.items():
            if task._task and not task._task.done():
                task._task.cancel()
                try:
                    await task._task
                except asyncio.CancelledError:
                    pass
                task._task = None

        log.info("scheduler_stopped", uptime_s=f"{time.time() - self._start_time:.0f}")

    async def _run_loop(self, task: ScheduledTask) -> None:
        """Run a single task on its interval."""
        try:
            # Initial delay to stagger task starts
            await asyncio.sleep(min(task.interval_seconds * 0.1, 5.0))

            while self._running and task.enabled:
                start = time.monotonic()
                try:
                    await task.callback()
                    duration = (time.monotonic() - start) * 1000

                    task.run_count += 1
                    task.last_run = time.time()

                    # Running average of duration
                    if task.avg_duration_ms == 0:
                        task.avg_duration_ms = duration
                    else:
                        task.avg_duration_ms = task.avg_duration_ms * 0.9 + duration * 0.1

                except Exception as e:
                    task.error_count += 1
                    task.last_error = str(e)
                    log.error(
                        "scheduled_task_error",
                        task=task.name,
                        error=str(e),
                        error_count=task.error_count,
                    )

                # Sleep until next run
                elapsed = time.monotonic() - start
                sleep_time = max(0, task.interval_seconds - elapsed)
                await asyncio.sleep(sleep_time)

        except asyncio.CancelledError:
            return

    # ── Task Control ──────────────────────────────────────────────────

    def enable_task(self, name: str) -> bool:
        """Enable a specific task."""
        task = self._tasks.get(name)
        if not task:
            return False

        task.enabled = True
        if self._running and (task._task is None or task._task.done()):
            task._task = asyncio.create_task(
                self._run_loop(task),
                name=f"fk_sched_{name}",
            )
        return True

    def disable_task(self, name: str) -> bool:
        """Disable a specific task."""
        task = self._tasks.get(name)
        if not task:
            return False

        task.enabled = False
        if task._task and not task._task.done():
            task._task.cancel()
        return True

    def update_interval(self, name: str, interval_seconds: float) -> bool:
        """Update a task's interval (takes effect on next cycle)."""
        task = self._tasks.get(name)
        if not task:
            return False
        task.interval_seconds = interval_seconds
        log.info("task_interval_updated", name=name, interval=f"{interval_seconds}s")
        return True

    # ── Statistics ────────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def uptime_seconds(self) -> float:
        return time.time() - self._start_time if self._running else 0.0

    def stats(self) -> dict[str, Any]:
        """Full scheduler statistics."""
        return {
            "running": self._running,
            "uptime": f"{self.uptime_seconds:.0f}s",
            "total_tasks": len(self._tasks),
            "active_tasks": sum(1 for t in self._tasks.values() if t.enabled),
            "tasks": {
                name: {
                    "enabled": t.enabled,
                    "interval": f"{t.interval_seconds}s",
                    "runs": t.run_count,
                    "errors": t.error_count,
                    "last_error": t.last_error[:100] if t.last_error else "",
                    "avg_duration_ms": f"{t.avg_duration_ms:.1f}",
                    "last_run": t.last_run,
                }
                for name, t in self._tasks.items()
            },
        }
