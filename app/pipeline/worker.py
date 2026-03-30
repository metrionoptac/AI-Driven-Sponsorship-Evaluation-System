"""
E7: Scalability — PostgreSQL-backed task queue with async workers.
Uses SELECT FOR UPDATE SKIP LOCKED for distributed job claiming.
Priority: REQUEUED > DEFERRED > NEW
"""

import asyncio
import logging
import signal
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Priority mapping — lower number = higher priority
STATE_PRIORITY = {
    "requeued": 1,
    "deferred": 2,
    "ingested": 3,
    "extracted": 4,
    "eligible": 5,
    "evaluated": 6,
    "recommended": 7,
}


class PipelineWorker:
    """
    Async worker that claims pipeline tasks from PostgreSQL and processes them.
    Uses SELECT FOR UPDATE SKIP LOCKED for safe concurrent access.
    """

    def __init__(self, db, pipeline_executor, worker_id: int = 0):
        self.db = db
        self.executor = pipeline_executor
        self.worker_id = worker_id
        self._running = False
        self._current_task: str | None = None

    async def claim_next(self) -> dict | None:
        """
        Claim the next available request for processing using
        SELECT FOR UPDATE SKIP LOCKED (PostgreSQL advisory lock pattern).
        Returns request dict or None if no work available.
        """
        async with self.db.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT id, state, created_at
                FROM requests
                WHERE state IN ('ingested', 'extracted', 'eligible', 'evaluated',
                                'recommended', 'requeued', 'deferred')
                ORDER BY
                    CASE state
                        WHEN 'requeued'    THEN 1
                        WHEN 'deferred'    THEN 2
                        WHEN 'ingested'    THEN 3
                        WHEN 'extracted'   THEN 4
                        WHEN 'eligible'    THEN 5
                        WHEN 'evaluated'   THEN 6
                        WHEN 'recommended' THEN 7
                        ELSE 10
                    END,
                    created_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            """)

            if row is None:
                return None

            # Mark as being processed
            await conn.execute(
                "UPDATE requests SET updated_at = NOW() WHERE id = $1",
                row["id"],
            )

            return dict(row)

    async def process(self, task: dict) -> bool:
        """
        Process a claimed request through the pipeline.
        Returns True if processing succeeded, False otherwise.
        """
        request_id = str(task["id"])
        state = task["state"]
        self._current_task = request_id

        logger.info(
            "[Worker %d] Processing %s (state=%s)",
            self.worker_id, request_id[:8], state,
        )

        try:
            result = await self.executor.run(request_id)
            logger.info(
                "[Worker %d] Completed %s -> %s",
                self.worker_id, request_id[:8],
                result.final_state if result else "unknown",
            )
            return True
        except Exception as e:
            logger.error(
                "[Worker %d] Failed processing %s: %s",
                self.worker_id, request_id[:8], e,
            )
            try:
                await self.db.update_state(request_id, "failed", actor="worker")
            except Exception:
                pass
            return False
        finally:
            self._current_task = None

    async def run_loop(self, poll_interval: float = 2.0):
        """
        Main worker loop: claim -> process -> repeat.
        Polls at poll_interval seconds when no work is available.
        """
        self._running = True
        logger.info("[Worker %d] Started", self.worker_id)

        while self._running:
            try:
                task = await self.claim_next()
                if task:
                    await self.process(task)
                else:
                    await asyncio.sleep(poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[Worker %d] Loop error: %s", self.worker_id, e)
                await asyncio.sleep(poll_interval)

        logger.info("[Worker %d] Stopped", self.worker_id)

    def stop(self):
        """Signal the worker to stop after current task completes."""
        self._running = False

    @property
    def is_busy(self) -> bool:
        return self._current_task is not None


class WorkerPool:
    """
    Manages multiple PipelineWorker instances.
    Provides graceful shutdown with in-progress request completion.
    """

    def __init__(self, db, pipeline_executor, num_workers: int = 3):
        self.db = db
        self.executor = pipeline_executor
        self.num_workers = num_workers
        self.workers: list[PipelineWorker] = []
        self._tasks: list[asyncio.Task] = []

    async def start(self):
        """Start all workers."""
        logger.info("Starting worker pool with %d workers", self.num_workers)
        for i in range(self.num_workers):
            worker = PipelineWorker(self.db, self.executor, worker_id=i)
            self.workers.append(worker)
            task = asyncio.create_task(worker.run_loop())
            self._tasks.append(task)
        logger.info("Worker pool started: %d workers active", self.num_workers)

    async def shutdown(self, timeout: float = 30.0):
        """
        Graceful shutdown: signal all workers to stop,
        then wait for in-progress tasks to complete (up to timeout).
        """
        logger.info("Shutting down worker pool...")

        # Signal all workers to stop
        for worker in self.workers:
            worker.stop()

        # Wait for tasks with timeout
        if self._tasks:
            done, pending = await asyncio.wait(
                self._tasks, timeout=timeout,
            )
            # Cancel any still-running after timeout
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        busy_count = sum(1 for w in self.workers if w.is_busy)
        if busy_count:
            logger.warning(
                "Worker pool shutdown: %d workers still had tasks", busy_count
            )
        else:
            logger.info("Worker pool shutdown: all workers idle, clean exit")

    def get_status(self) -> dict:
        """Get worker pool status for monitoring."""
        return {
            "total_workers": self.num_workers,
            "active_workers": sum(1 for w in self.workers if w.is_busy),
            "idle_workers": sum(1 for w in self.workers if not w.is_busy),
            "workers": [
                {
                    "id": w.worker_id,
                    "busy": w.is_busy,
                    "current_task": w._current_task,
                }
                for w in self.workers
            ],
        }
