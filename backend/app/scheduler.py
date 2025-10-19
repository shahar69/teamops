import asyncio
import json
import sys
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine
import os

from backend.app.publishers import get_publisher


class AIScheduleDispatcher:
    """Reliable polling dispatcher for scheduled AI content deliveries."""

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
        self._stopping = False
        loop = asyncio.get_running_loop()
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
                await self._process_due()
            except Exception as e:  # pragma: no cover - defensive logging
                print("Scheduler error:", e, file=sys.stderr)
            await asyncio.sleep(self.interval_seconds)

    async def _process_due(self) -> None:
        now = datetime.utcnow().replace(tzinfo=timezone.utc)
        now_iso = now.isoformat().replace("+00:00", "Z")
        with self.engine.begin() as conn:
            # select due schedules
            due_rows = conn.execute(
                text(
                    """
                    SELECT id, job_id, platform
                    FROM ai_content_schedules
                    WHERE status='scheduled' AND scheduled_for <= NOW()
                    ORDER BY scheduled_for ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT :limit
                    """
                ),
                {"limit": self.batch_size},
            ).fetchall()
            for row in due_rows:
                try:
                    payload = {
                        "last_enqueued_at": now_iso,
                        "note": "queued for downstream delivery",
                    }
                    conn.execute(
                        text(
                            """
                            UPDATE ai_content_schedules
                            SET status='queued',
                                delivery_meta = COALESCE(delivery_meta, '{}'::jsonb) || :meta::jsonb,
                                last_attempted_at = NOW(),
                                attempts = COALESCE(attempts,0) + 1,
                                updated_at=NOW()
                            WHERE id=:id
                            """
                        ),
                        {"id": row.id, "meta": json.dumps(payload)},
                    )
                    # Optionally attempt immediate publish if enabled
                    try_publish = os.environ.get("ENABLE_PUBLISH", "false").lower() in ("1","true","yes")
                    if try_publish:
                        # fetch job and schedule full rows
                        sched = conn.execute(text(
                            "SELECT s.*, j.title, j.generated_content, j.content_type FROM ai_content_schedules s JOIN ai_content_jobs j ON j.id=s.job_id WHERE s.id=:id"
                        ), {"id": row.id}).fetchone()
                        if sched:
                            job = {
                                "id": sched.job_id,
                                "title": sched.title,
                                "generated_content": sched.generated_content,
                                "content_type": sched.content_type,
                            }
                            schedule = dict(sched._mapping)
                            try:
                                pub = get_publisher(sched.platform)
                                res = pub.publish(job, schedule)
                                conn.execute(text(
                                    """
                                    UPDATE ai_content_schedules
                                    SET status = 'posted',
                                        result = :result,
                                        delivery_meta = COALESCE(delivery_meta, '{}'::jsonb) || :meta::jsonb,
                                        updated_at = NOW()
                                    WHERE id=:id
                                    """
                                ), {"id": row.id, "result": str(res), "meta": json.dumps({"published_at": now_iso, "publish_result": res})})
                            except Exception as pp_err:
                                conn.execute(text(
                                    """
                                    UPDATE ai_content_schedules
                                    SET status = 'failed',
                                        result = :result,
                                        delivery_meta = COALESCE(delivery_meta, '{}'::jsonb) || :meta::jsonb,
                                        updated_at = NOW()
                                    WHERE id=:id
                                    """
                                ), {"id": row.id, "result": str(pp_err), "meta": json.dumps({"failed_at": now_iso, "error": str(pp_err)})})
                except Exception as exc:  # pragma: no cover - defensive logging
                    print(
                        f"[AI-SCHEDULE] failed queueing schedule {row.id}: {exc}",
                        file=sys.stderr,
                    )
                    conn.execute(
                        text(
                            """
                            UPDATE ai_content_schedules
                            SET status='error',
                                delivery_meta = COALESCE(delivery_meta, '{}'::jsonb) || :meta::jsonb,
                                last_attempted_at = NOW(),
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
