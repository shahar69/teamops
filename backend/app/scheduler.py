import asyncio
import json
import sys
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine


class AIScheduleDispatcher:
    """Simple polling dispatcher for scheduled AI content deliveries."""

    def __init__(
        self,
        engine: Engine,
        interval_seconds: int = 60,
        batch_size: int = 20,
    ) -> None:
        self.engine = engine
        self.interval_seconds = max(1, interval_seconds)
        self.batch_size = max(1, batch_size)
        self._task: Optional[asyncio.Task] = None
        self._stopping = False

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        loop = asyncio.get_running_loop()
        self._stopping = False
        self._task = loop.create_task(self._run())

    async def stop(self) -> None:
        if not self._task:
            return
        self._stopping = True
        await self._task
        self._task = None

    async def _run(self) -> None:
        while not self._stopping:
            try:
                processed = await asyncio.get_running_loop().run_in_executor(
                    None, self._process_due
                )
            except Exception as exc:  # pragma: no cover - defensive logging
                print(f"[AI-SCHEDULE] tick error: {exc}", file=sys.stderr)
                processed = 0
            await asyncio.sleep(self.interval_seconds if processed == 0 else 0.1)

    def _process_due(self) -> int:
        processed = 0
        now = datetime.utcnow().replace(tzinfo=timezone.utc)
        now_iso = now.isoformat().replace("+00:00", "Z")
        with self.engine.begin() as conn:
            due_rows = conn.execute(
                text(
                    """
                    SELECT id, job_id, platform
                    FROM ai_content_schedule
                    WHERE status='pending' AND publish_at <= NOW()
                    ORDER BY publish_at ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT :limit
                    """
                ),
                {"limit": self.batch_size},
            ).fetchall()
            for row in due_rows:
                processed += 1
                try:
                    payload = {
                        "last_enqueued_at": now_iso,
                        "note": "queued for downstream delivery",
                    }
                    conn.execute(
                        text(
                            """
                            UPDATE ai_content_schedule
                            SET status='queued',
                                delivery_meta = COALESCE(delivery_meta, '{}'::jsonb) || :meta::jsonb,
                                updated_at=NOW()
                            WHERE id=:id
                            """
                        ),
                        {"id": row.id, "meta": json.dumps(payload)},
                    )
                except Exception as exc:  # pragma: no cover - defensive logging
                    print(
                        f"[AI-SCHEDULE] failed queueing schedule {row.id}: {exc}",
                        file=sys.stderr,
                    )
                    conn.execute(
                        text(
                            """
                            UPDATE ai_content_schedule
                            SET status='error',
                                delivery_meta = COALESCE(delivery_meta, '{}'::jsonb) || :meta::jsonb,
                                updated_at=NOW()
                            WHERE id=:id
                            """
                        ),
                        {
                            "id": row.id,
                            "meta": json.dumps(
                                {
                                    "last_error": str(exc),
                                    "failed_at": now_iso,
                                }
                            ),
                        },
                    )
        return processed
