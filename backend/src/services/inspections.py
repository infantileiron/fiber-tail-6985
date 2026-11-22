import logging

from fastapi import HTTPException
from psycopg.types.json import Jsonb
from redis.exceptions import RedisError

from src.config.runtime import WAKE_KEY, connect, queue
from src.constants.domain import RunStatus
from src.models.inspections import get_inspection
from src.models.ledger import get_lot, sample_snapshot, write_event
from src.services.weighted_tail import InsufficientSamples, analyze
from src.services.vehicles import process_vehicle, vehicle_snapshot
from src.utils.snapshot import checksum

log = logging.getLogger(__name__)


def enqueue(lot_id, parameters, actor):
    with connect() as db:
        get_lot(db, lot_id, lock=True)
        snapshot = sample_snapshot(db, lot_id)
        version = db.execute("""
            SELECT COALESCE(max(version), 0) + 1 AS next FROM inspections WHERE lot_id = %s
        """, (lot_id,)).fetchone()["next"]
        row = db.execute("""
            INSERT INTO inspections (lot_id, version, parameters, snapshot, checksum, status, requested_by)
            VALUES (%s, %s, %s, %s, %s, 'queued', %s) RETURNING id, version, status
        """, (lot_id, version, Jsonb(parameters.model_dump(mode="json")), Jsonb(snapshot), checksum(snapshot), actor)).fetchone()
        write_event(db, lot_id, actor, "inspection_queued", f"V{version:02}")
    try:
        with queue.pipeline() as pipeline:
            pipeline.lpush(WAKE_KEY, row["id"]).ltrim(WAKE_KEY, 0, 0).execute()
    except RedisError:
        log.warning("Redis wake signal unavailable; worker will poll the durable queue")
    return row


def _comparison(db, job, result):
    previous = db.execute("""
        SELECT version, checksum, parameters, result FROM inspections
        WHERE lot_id = %s AND version < %s AND status = 'succeeded'
        ORDER BY version DESC LIMIT 1
    """, (job["lot_id"], job["version"])).fetchone()
    if not previous:
        return None
    return {
        "previous_version": previous["version"],
        "same_samples": previous["checksum"] == job["checksum"],
        "previous_parameters": previous["parameters"],
        "exceed_delta_pp": result["exceed_share_pct"] - previous["result"]["exceed_share_pct"],
        "tail_delta_pp": result["tail_mean_pct"] - previous["result"]["tail_mean_pct"],
    }


def process_next(db):
    job = db.execute("""
        SELECT * FROM inspections WHERE status = 'queued' ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED
    """).fetchone()
    if not job:
        return False
    if job["vehicle_id"] is not None:
        process_vehicle(db, job)
        return True
    try:
        result = analyze(job["snapshot"], job["parameters"])
        result["comparison"] = _comparison(db, job, result)
    except InsufficientSamples as exc:
        db.execute("""
            UPDATE inspections SET status = 'failed', error = %s, completed_at = now() WHERE id = %s
        """, (str(exc), job["id"]))
        action = "inspection_failed"
    else:
        db.execute("""
            UPDATE inspections SET status = 'succeeded', result = %s, completed_at = now() WHERE id = %s
        """, (Jsonb(result), job["id"]))
        action = "inspection_completed"
    write_event(db, job["lot_id"], None, action, f"V{job['version']:02}")
    return True


def _current_snapshot(db, row):
    if row["vehicle_id"] is not None:
        return vehicle_snapshot(db, row["vehicle_id"]), "车辆成员的干样或复磅吨位已有变化，请重新合算后发布"
    return sample_snapshot(db, row["lot_id"]), "干样台账已有新增，请重新诊断后发布"


def publish(run_id, payload, actor):
    with connect() as db:
        row = get_inspection(db, run_id)
        if row["vehicle_id"] is not None:
            scope_column, scope_id = "vehicle_id", row["vehicle_id"]
            lock_table = "vehicles"
        else:
            scope_column, scope_id = "lot_id", row["lot_id"]
            lock_table = "lots"
        db.execute(f"SELECT 1 FROM {lock_table} WHERE id = %s FOR UPDATE", (scope_id,))
        row = get_inspection(db, run_id)
        latest = db.execute(
            f"SELECT max(version) AS version FROM inspections WHERE {scope_column} = %s", (scope_id,)
        ).fetchone()
        if row["outcome"] or row["status"] != RunStatus.SUCCEEDED or row["version"] != latest["version"]:
            raise HTTPException(409, "仅最新且已算完的待复核版本可发布")
        current, stale_message = _current_snapshot(db, row)
        if row["checksum"] != checksum(current):
            raise HTTPException(409, stale_message)
        db.execute("""
            INSERT INTO decisions (inspection_id, outcome, rationale, reviewer_id) VALUES (%s, %s, %s, %s)
        """, (run_id, payload.outcome, payload.rationale, actor))
        write_event(db, row["lot_id"], actor, "decision_published", f"V{row['version']:02}",
                    vehicle_id=row["vehicle_id"])
        return get_inspection(db, run_id)
