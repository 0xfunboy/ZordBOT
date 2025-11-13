"""Simple cooperative scheduler for mint loops and watchers."""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional


class Scheduler:
    def __init__(self, logger) -> None:
        self.logger = logger
        self.jobs = []
        self._stop_event = threading.Event()

    def add_interval_job(self, func: Callable[[], None], interval_seconds: int, name: str = "job") -> None:
        job = {"func": func, "interval": interval_seconds, "name": name}
        self.jobs.append(job)

    def _job_loop(self, job) -> None:
        self.logger.info("Scheduler started job %s (interval=%ss)", job["name"], job["interval"])
        while not self._stop_event.is_set():
            try:
                job["func"]()
            except Exception as exc:  # noqa: BLE001
                self.logger.error("Scheduled job %s failed: %s", job["name"], exc)
            waited = 0
            while waited < job["interval"] and not self._stop_event.is_set():
                time.sleep(1)
                waited += 1

    def start(self) -> None:
        threads = []
        for job in self.jobs:
            thread = threading.Thread(target=self._job_loop, args=(job,), daemon=True)
            thread.start()
            threads.append(thread)
        try:
            while not self._stop_event.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            self.logger.info("Stopping scheduler...")
            self.stop()
        for thread in threads:
            thread.join()

    def stop(self) -> None:
        self._stop_event.set()


def run_auto_loop(bot_fn: Callable[[], None], interval: int, logger) -> None:
    scheduler = Scheduler(logger)
    scheduler.add_interval_job(bot_fn, interval, name="auto-mint")
    scheduler.start()


def watch_ticker_and_mint(
    watch_fn: Callable[[], bool],
    mint_fn: Callable[[], None],
    interval_seconds: int,
    logger,
    name: str = "watcher",
) -> None:
    def job() -> None:
        if watch_fn():
            logger.info("Watcher %s detected target, minting...", name)
            mint_fn()
        else:
            logger.debug("Watcher %s reported no action", name)

    scheduler = Scheduler(logger)
    scheduler.add_interval_job(job, interval_seconds, name=name)
    scheduler.start()


class ManualCommand:
    def __init__(self, func: Callable[[], None], logger, name: str = "manual-mint") -> None:
        self.func = func
        self.logger = logger
        self.name = name

    def run(self) -> None:
        self.logger.info("Manual command %s triggered", self.name)
        self.func()
