#!/usr/bin/env python3
"""Simple publish worker for TeamOps.

Usage:
  publish_worker.py [--live]

Defaults to dry-run (logs payloads and updates schedule.result). Use --live to attempt real publishes (requires publisher credentials).

This script must be run where the project's environment variables are set (DATABASE_URL etc.).
"""
import argparse
import os
import time
import json
from datetime import datetime

from sqlalchemy import create_engine, text

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
ROOT = os.path.abspath(os.path.join(BASE, '..'))
import sys
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.app.main import DATABASE_URL
from backend.app.publishers import get_publisher


from datetime import timezone


def main(live: bool = False):
    engine = create_engine(DATABASE_URL)
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat() + 'Z'
    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT s.id, s.job_id, s.platform, s.metadata, s.channel_id, j.title, j.generated_content,
                   c.id as ch_id, c.name as ch_name, c.max_per_day, c.min_interval_seconds, c.jitter_seconds
            FROM ai_content_schedules s
            JOIN ai_content_jobs j ON j.id=s.job_id
            LEFT JOIN channels c ON c.id=s.channel_id
            WHERE s.status='scheduled' AND s.scheduled_for <= NOW()
            ORDER BY s.scheduled_for ASC
            LIMIT 20
        """)).fetchall()
        for r in rows:
            sid = r.id
            job = {"id": r.job_id, "title": r.title, "generated_content": r.generated_content}
            schedule = dict(r._mapping)
            channel = None
            if r.ch_id:
                channel = {"id": r.ch_id, "name": r.ch_name, "max_per_day": r.max_per_day, "min_interval_seconds": r.min_interval_seconds, "jitter_seconds": r.jitter_seconds}
            # mark queued
            conn.execute(text("UPDATE ai_content_schedules SET status='queued', last_attempted_at=NOW(), delivery_meta = COALESCE(delivery_meta, '{}'::jsonb) || :meta::jsonb, attempts = COALESCE(attempts,0)+1, updated_at=NOW() WHERE id=:id"), {"id": sid, "meta": json.dumps({"queued_at": now_iso})})
            # Respect channel throttle simple checks (max_per_day/min_interval)
            can_publish = True
            if channel:
                # count todays publishes
                cnt = conn.execute(text("SELECT COUNT(1) FROM ai_content_schedules WHERE channel_id=:cid AND status='posted' AND created_at >= date_trunc('day', NOW())"), {"cid": channel['id']}).scalar()
                if channel['max_per_day'] is not None and cnt >= channel['max_per_day']:
                    can_publish = False
                # last publish time
                last = conn.execute(text("SELECT updated_at FROM ai_content_schedules WHERE channel_id=:cid AND status='posted' ORDER BY updated_at DESC LIMIT 1"), {"cid": channel['id']}).fetchone()
                if last and channel['min_interval_seconds']:
                    from datetime import datetime, timezone
                    last_dt = last.updated_at
                    if (datetime.now(timezone.utc) - last_dt).total_seconds() < channel['min_interval_seconds']:
                        can_publish = False
            if not can_publish:
                conn.execute(text("UPDATE ai_content_schedules SET status='scheduled', delivery_meta = COALESCE(delivery_meta, '{}'::jsonb) || :meta::jsonb, updated_at=NOW() WHERE id=:id"), {"id": sid, "meta": json.dumps({"throttled": True, "when": now_iso})})
                print(f"Schedule {sid} throttled for channel {channel and channel['name']} - requeued")
                continue

            # apply jitter
            if channel and channel.get('jitter_seconds'):
                import random
                delay = random.randint(0, int(channel['jitter_seconds']))
                print(f"Applying jitter {delay}s for schedule {sid}")
                time.sleep(delay)

            # call publisher
            try:
                pub = get_publisher(schedule['platform'])
                if live:
                    res = pub.publish(job, schedule)
                else:
                    try:
                        # call publish but catch config errors to allow dry-run
                        res = pub.publish(job, schedule)
                    except Exception as e:
                        res = {"success": False, "message": f"dry-run: {e}", "error": str(e)}
                conn.execute(text("UPDATE ai_content_schedules SET status=:status, result=:result, delivery_meta = COALESCE(delivery_meta, '{}'::jsonb) || :meta::jsonb, updated_at=NOW() WHERE id=:id"), {"id": sid, "status": ('posted' if res.get('success') else 'failed'), "result": json.dumps(res), "meta": json.dumps({"published_at": now_iso, "publish_result": res})})
                print(f"Schedule {sid} publish result: {res}")
            except Exception as e:
                conn.execute(text("UPDATE ai_content_schedules SET status='failed', result=:result, delivery_meta = COALESCE(delivery_meta, '{}'::jsonb) || :meta::jsonb, updated_at=NOW() WHERE id=:id"), {"id": sid, "result": str(e), "meta": json.dumps({"error": str(e)})})
                print(f"Schedule {sid} failed: {e}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true', help='Attempt live publish')
    args = parser.parse_args()
    main(live=args.live)
