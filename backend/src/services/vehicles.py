import logging
from fractions import Fraction
from uuid import UUID

from fastapi import HTTPException
from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb
from redis.exceptions import RedisError

from src.config.runtime import WAKE_KEY, connect, queue
from src.constants.domain import MIN_SAMPLES, RunStatus
from src.models.inspections import get_inspection
from src.models.ledger import get_lot, sample_snapshot, write_event
from src.models.vehicles import add_weighing, get_vehicle, vehicle_lots
from src.services.weighted_tail import InconclusiveProvisional, InsufficientSamples, analyze_vehicle
from src.utils.snapshot import checksum

log = logging.getLogger(__name__)


def vehicle_snapshot(db, vehicle_id):
    """锁定合算口径：各批到货吨位、折算系数、齐套状态与按样号排序的称重。"""
    members = vehicle_lots(db, vehicle_id)
    total_kg = sum(member["shipment_kg"] for member in members)
    snapshot_lots = []
    for member in members:
        samples = sample_snapshot(db, member["id"])
        factor = Fraction(member["shipment_kg"], total_kg) if total_kg else None
        snapshot_lots.append({
            "lot_id": member["id"],
            "lot_code": member["code"],
            "supplier": member["supplier"],
            "material": member["material"],
            "shipment_kg": member["shipment_kg"],
            "sample_count": len(samples),
            "weight_factor": str(factor),
            "complete": len(samples) >= MIN_SAMPLES,
            "samples": samples,
        })
    return {"vehicle_id": vehicle_id, "total_shipment_kg": total_kg, "lots": snapshot_lots}


def create_vehicle(payload, actor):
    lot_ids = list(dict.fromkeys(payload.lot_ids))
    if len(lot_ids) < 2:
        raise HTTPException(422, "同车合算至少选择两个供货批")
    with connect() as db:
        rows = db.execute("SELECT id, code FROM lots WHERE id = ANY(%s) ORDER BY code", (lot_ids,)).fetchall()
        if len(rows) != len(lot_ids):
            raise HTTPException(404, "存在未登记的供货批号，无法建车")
        occupied = db.execute("""
            SELECT l.code FROM vehicle_lots vl JOIN lots l ON l.id = vl.lot_id
            WHERE vl.lot_id = ANY(%s)
        """, (lot_ids,)).fetchall()
        if occupied:
            raise HTTPException(409, f"以下批号已挂在其他车辆上：{'、'.join(row['code'] for row in occupied)}")
        try:
            vehicle = db.execute("""
                INSERT INTO vehicles (code, note, created_by) VALUES (%s, %s, %s) RETURNING *
            """, (payload.code, payload.note, actor)).fetchone()
            for lot_id in lot_ids:
                db.execute(
                    "INSERT INTO vehicle_lots (vehicle_id, lot_id) VALUES (%s, %s)",
                    (vehicle["id"], lot_id),
                )
        except UniqueViolation as exc:
            raise HTTPException(409, "这个车号已经登记") from exc
        write_event(db, None, actor, "vehicle_created", vehicle["code"], vehicle_id=vehicle["id"])
        for row in rows:
            write_event(db, None, actor, "vehicle_lot_attached", row["code"], vehicle_id=vehicle["id"])
        return get_vehicle(db, vehicle["id"])


def enqueue_vehicle(vehicle_id, payload, actor):
    key = str(payload.idempotency_key)
    with connect() as db:
        get_vehicle(db, vehicle_id, lock=True)
        existing = db.execute(
            "SELECT id, version, status, vehicle_id FROM inspections WHERE idempotency_key = %s", (key,)
        ).fetchone()
        if existing:
            # 原单重试：直接取回同一张验收单，不新增版本。
            if existing["vehicle_id"] != vehicle_id:
                raise HTTPException(409, "该请求编号已用于其他验收单，不能复用")
            write_event(db, None, actor, "inspection_retried", f"V{existing['version']:02}", vehicle_id=vehicle_id)
            return get_inspection(db, existing["id"])

        snapshot = vehicle_snapshot(db, vehicle_id)
        provisional = any(not member["complete"] for member in snapshot["lots"])
        version = db.execute("""
            SELECT COALESCE(max(version), 0) + 1 AS next FROM inspections WHERE vehicle_id = %s
        """, (vehicle_id,)).fetchone()["next"]
        try:
            row = db.execute("""
                INSERT INTO inspections (vehicle_id, version, parameters, snapshot, checksum, status,
                                         requested_by, idempotency_key, provisional)
                VALUES (%s, %s, %s, %s, %s, 'queued', %s, %s, %s)
                RETURNING id, version, status
            """, (vehicle_id, version, Jsonb(payload.model_dump(mode="json", exclude={"idempotency_key"})),
                  Jsonb(snapshot), checksum(snapshot), actor, UUID(key), provisional)).fetchone()
        except UniqueViolation as exc:
            # 并发重试：幂等键已落库，取回原单。
            winner = db.execute(
                "SELECT id FROM inspections WHERE idempotency_key = %s AND vehicle_id = %s", (key, vehicle_id)
            ).fetchone()
            if winner:
                return get_inspection(db, winner["id"])
            raise HTTPException(409, "该请求编号已用于其他验收单，不能复用") from exc
        write_event(db, None, actor, "inspection_queued", f"V{version:02}", vehicle_id=vehicle_id)
    try:
        with queue.pipeline() as pipeline:
            pipeline.lpush(WAKE_KEY, row["id"]).ltrim(WAKE_KEY, 0, 0).execute()
    except RedisError:
        log.warning("Redis wake signal unavailable; worker will poll the durable queue")
    return row


def _comparison(db, job, result):
    previous = db.execute("""
        SELECT version, checksum, parameters, result FROM inspections
        WHERE vehicle_id = %s AND version < %s AND status = 'succeeded'
        ORDER BY version DESC LIMIT 1
    """, (job["vehicle_id"], job["version"])).fetchone()
    if not previous:
        return None
    return {
        "previous_version": previous["version"],
        "same_snapshot": previous["checksum"] == job["checksum"],
        "previous_parameters": previous["parameters"],
        "exceed_delta_pp": result["exceed_share_pct"] - previous["result"]["exceed_share_pct"],
        "tail_delta_pp": result["tail_mean_pct"] - previous["result"]["tail_mean_pct"],
    }


def process_vehicle(db, job):
    try:
        result = analyze_vehicle(job["snapshot"], job["parameters"])
        result["members"] = [{
            "lot_code": member["lot_code"],
            "shipment_kg": member["shipment_kg"],
            "weight_factor": member["weight_factor"],
            "sample_count": member["sample_count"],
            "complete": member["complete"],
        } for member in job["snapshot"]["lots"]]
        result["comparison"] = _comparison(db, job, result)
    except (InsufficientSamples, InconclusiveProvisional) as exc:
        db.execute("""
            UPDATE inspections SET status = 'failed', error = %s, completed_at = now() WHERE id = %s
        """, (str(exc), job["id"]))
        write_event(db, None, None, "inspection_failed", f"V{job['version']:02}", vehicle_id=job["vehicle_id"])
        return
    db.execute("""
        UPDATE inspections SET status = 'succeeded', result = %s, completed_at = now() WHERE id = %s
    """, (Jsonb(result), job["id"]))
    write_event(db, None, None, "inspection_completed", f"V{job['version']:02}", vehicle_id=job["vehicle_id"])


def reweigh_lot(lot_id, payload, actor):
    with connect() as db:
        lot = get_lot(db, lot_id, lock=True)
        if lot["shipment_kg"] == payload.shipment_kg:
            raise HTTPException(409, "复磅吨位与当前到货重量相同，无需改写配重")
        previous = lot["shipment_kg"]
        add_weighing(db, lot, payload.reason, actor)
        updated = db.execute("""
            UPDATE lots SET shipment_kg = %s WHERE id = %s RETURNING *
        """, (payload.shipment_kg, lot_id)).fetchone()
        write_event(db, lot_id, actor, "lot_reweighed", f"{previous} kg → {payload.shipment_kg} kg")
        return updated
