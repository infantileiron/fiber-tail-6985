import json
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from psycopg.types.json import Jsonb

from src.config.runtime import connect
from src.models.ledger import sample_snapshot
from src.schemas.inputs import RunInput
from src.services.weighted_tail import analyze, analyze_vehicle
from src.utils.security import hash_password
from src.utils.snapshot import checksum

USERS = (
    ("analyst", "许青·称重分析", "cotton-scale"),
    ("reviewer", "梁禾·收料复核", "cotton-review"),
    ("observer", "周芜·仓务观察", "cotton-view"),
)
LOTS = (
    ("MD-1121-01", "白檀分拣站", "浅色牛仔边角料", 3200, (700, 550, 600, 500, 650, 700), (7, 11, 9, 5, 13, 14)),
    ("MD-1121-02", "河埠回收点", "混色针织余料", 2800, (800, 700, 600, 650, 500, 600), (12, 14, 15, 26, 20, 12)),
    ("MD-1121-03", "青梭再生料站", "本色棉纺边角料", 3100, (500, 950, 1000, 900, 400, 250), (5, 19, 30, 27, 28, 30)),
    ("MD-1121-04", "江湾纤维集运站", "灰色棉混纺碎料", 2900, (700, 700, 800, 600, 600, 500), (14, 21, 16, 24, 30, 25)),
    ("MD-1121-05", "石滩转运点", "杂色针织碎料", 10, (), ()),
    ("MD-1121-06", "石滩转运点", "浅色涤棉碎料", 1200, (), ()),
)
# V-1121：小缺样批挂在退货基线车上，两极端建议一致（均退货），演示暂定结论可发布；
# V-1122：大缺样批挂在接收基线车上，包络不一致，演示合算失败留痕、补齐后再算。
VEHICLES = (
    ("V-1121", "同车合算 · 缺样暂定", ("MD-1121-03", "MD-1121-05")),
    ("V-1122", "同车合算 · 等待补样", ("MD-1121-01", "MD-1121-02", "MD-1121-06")),
)
LOCATIONS = ("前舱·表层", "前舱·内层", "中舱·表层", "中舱·内层", "后舱·表层", "后舱·内层")
DAY = date(2026, 11, 21)
SHIFT = datetime(2026, 11, 21, 8, 30, tzinfo=timezone(timedelta(hours=8)))


def seed():
    with connect() as db:
        db.execute("SELECT pg_advisory_xact_lock(5201)")
        for username, name, password in USERS:
            if not db.execute("SELECT 1 FROM accounts WHERE username = %s", (username,)).fetchone():
                db.execute("""
                    INSERT INTO accounts (username, display_name, password_hash, role)
                    VALUES (%s, %s, %s, %s) ON CONFLICT (username) DO NOTHING
                """, (username, name, hash_password(password), username))
        users = {row["username"]: row["id"] for row in db.execute("SELECT id, username FROM accounts")}
        lot_ids = {}
        for code, supplier, material, shipment, weights, impurities in LOTS:
            lot = db.execute("""
                INSERT INTO lots (code, supplier, material, received_on, shipment_kg, created_by)
                VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (code) DO NOTHING RETURNING id
            """, (code, supplier, material, DAY, shipment, users["analyst"])).fetchone()
            if not lot:
                lot_ids[code] = db.execute("SELECT id FROM lots WHERE code = %s", (code,)).fetchone()["id"]
                continue
            lot_id = lot["id"]
            lot_ids[code] = lot_id
            _event(db, lot_id, users["analyst"], "lot_created", code, SHIFT)
            for index, (location, dry_g, impurity_g) in enumerate(zip(LOCATIONS, weights, impurities), 1):
                stamp = SHIFT + timedelta(minutes=index * 3)
                sample_code = f"S-{index:02}"
                db.execute("""
                    INSERT INTO samples (lot_id, code, location, dry_g, impurity_g, recorded_by, recorded_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (lot_id, sample_code, location, dry_g, impurity_g, users["analyst"], stamp))
                _event(db, lot_id, users["analyst"], "sample_recorded", sample_code, stamp)
            if code == "MD-1121-03":
                _seed_decision(db, lot_id, users)
        _seed_vehicles(db, users, lot_ids)
        state = {}
        queries = {
            "accounts": "SELECT username, role FROM accounts ORDER BY username",
            "lots": "SELECT code, supplier, material, shipment_kg FROM lots ORDER BY code",
            "samples": "SELECT l.code AS lot, s.code, dry_g, impurity_g FROM samples s JOIN lots l ON l.id=s.lot_id ORDER BY l.code, s.code",
            "vehicles": "SELECT code, note FROM vehicles ORDER BY code",
            "inspections": "SELECT COALESCE(l.code, v.code) AS scope, version, status, provisional FROM inspections i LEFT JOIN lots l ON l.id=i.lot_id LEFT JOIN vehicles v ON v.id=i.vehicle_id ORDER BY scope, version",
            "decisions": "SELECT l.code AS lot, i.version, d.outcome FROM decisions d JOIN inspections i ON i.id=d.inspection_id JOIN lots l ON l.id=i.lot_id ORDER BY l.code, i.version",
            "audit_events": "SELECT id, action, reference FROM audit_events ORDER BY id",
        }
        for entity, sql in queries.items():
            rows = db.execute(sql).fetchall()
            state[entity] = {"count": len(rows), "fingerprint": checksum(rows)}
    print(json.dumps(state, sort_keys=True))
    return state


def _event(db, lot_id, actor, action, reference, stamp=None, vehicle_id=None):
    db.execute("""
        INSERT INTO audit_events (lot_id, vehicle_id, actor_id, action, reference, occurred_at)
        VALUES (%s, %s, %s, %s, %s, COALESCE(%s, now()))
    """, (lot_id, vehicle_id, actor, action, reference, stamp))


def _seed_decision(db, lot_id, users):
    params = RunInput().model_dump(mode="json")
    snapshot = sample_snapshot(db, lot_id)
    result = analyze(snapshot, params) | {"comparison": None}
    requested = SHIFT + timedelta(minutes=30)
    completed = requested + timedelta(seconds=1)
    published = SHIFT + timedelta(minutes=50)
    row = db.execute("""
        INSERT INTO inspections (lot_id, version, parameters, snapshot, checksum, status, result,
                                 requested_by, requested_at, completed_at)
        VALUES (%s, 1, %s, %s, %s, 'succeeded', %s, %s, %s, %s) RETURNING id
    """, (lot_id, Jsonb(params), Jsonb(snapshot), checksum(snapshot), Jsonb(result), users["analyst"], requested, completed)).fetchone()
    db.execute("""
        INSERT INTO decisions (inspection_id, outcome, rationale, reviewer_id, published_at)
        VALUES (%s, 'reject', %s, %s, %s)
    """, (row["id"], "尾部 15% 的平均杂质率超过 8.00%，后舱样封存并通知供货方复核。", users["reviewer"], published))
    _event(db, lot_id, users["analyst"], "inspection_queued", "V01", requested)
    _event(db, lot_id, None, "inspection_completed", "V01", completed)
    _event(db, lot_id, users["reviewer"], "decision_published", "V01", published)


def _vehicle_snapshot(db, vehicle_id):
    from fractions import Fraction

    from src.models.vehicles import vehicle_lots

    members = vehicle_lots(db, vehicle_id)
    total_kg = sum(member["shipment_kg"] for member in members)
    snapshot_lots = []
    for member in members:
        samples = sample_snapshot(db, member["id"])
        snapshot_lots.append({
            "lot_id": member["id"],
            "lot_code": member["code"],
            "supplier": member["supplier"],
            "material": member["material"],
            "shipment_kg": member["shipment_kg"],
            "sample_count": len(samples),
            "weight_factor": str(Fraction(member["shipment_kg"], total_kg)),
            "complete": len(samples) >= 3,
            "samples": samples,
        })
    return {"vehicle_id": vehicle_id, "total_shipment_kg": total_kg, "lots": snapshot_lots}


def _seed_vehicles(db, users, lot_ids):
    params = RunInput().model_dump(mode="json")
    for vehicle_code, note, member_codes in VEHICLES:
        if db.execute("SELECT 1 FROM vehicles WHERE code = %s", (vehicle_code,)).fetchone():
            continue
        vehicle = db.execute("""
            INSERT INTO vehicles (code, note, created_by) VALUES (%s, %s, %s) RETURNING id
        """, (vehicle_code, note, users["analyst"])).fetchone()
        vehicle_id = vehicle["id"]
        _event(db, None, users["analyst"], "vehicle_created", vehicle_code, SHIFT, vehicle_id)
        for code in member_codes:
            lot_id = lot_ids[code]
            db.execute("INSERT INTO vehicle_lots (vehicle_id, lot_id) VALUES (%s, %s)", (vehicle_id, lot_id))
            _event(db, None, users["analyst"], "vehicle_lot_attached", code, SHIFT, vehicle_id)
        snapshot = _vehicle_snapshot(db, vehicle_id)
        requested = SHIFT + timedelta(minutes=40)
        completed = requested + timedelta(seconds=1)
        try:
            from src.services.weighted_tail import InconclusiveProvisional, InsufficientSamples

            result = analyze_vehicle(snapshot, params)
            result["members"] = [{
                "lot_code": member["lot_code"], "shipment_kg": member["shipment_kg"],
                "weight_factor": member["weight_factor"], "sample_count": member["sample_count"],
                "complete": member["complete"],
            } for member in snapshot["lots"]]
            result["comparison"] = None
            db.execute("""
                INSERT INTO inspections (vehicle_id, version, parameters, snapshot, checksum, status, result,
                                         requested_by, idempotency_key, provisional, requested_at, completed_at)
                VALUES (%s, 1, %s, %s, %s, 'succeeded', %s, %s, %s, true, %s, %s)
            """, (vehicle_id, Jsonb(params), Jsonb(snapshot), checksum(snapshot), Jsonb(result),
                  users["analyst"], uuid4(), requested, completed))
            _event(db, None, None, "inspection_completed", "V01", completed, vehicle_id)
        except (InsufficientSamples, InconclusiveProvisional) as exc:
            db.execute("""
                INSERT INTO inspections (vehicle_id, version, parameters, snapshot, checksum, status, error,
                                         requested_by, idempotency_key, provisional, requested_at, completed_at)
                VALUES (%s, 1, %s, %s, %s, 'failed', %s, %s, %s, true, %s, %s)
            """, (vehicle_id, Jsonb(params), Jsonb(snapshot), checksum(snapshot), str(exc),
                  users["analyst"], uuid4(), requested, completed))
            _event(db, None, None, "inspection_failed", "V01", completed, vehicle_id)
        _event(db, None, users["analyst"], "inspection_queued", "V01", requested, vehicle_id)


if __name__ == "__main__":
    seed()
