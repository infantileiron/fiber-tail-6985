import json

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response

from src.config.runtime import connect
from src.constants.domain import Role, RunStatus
from src.models.inspections import get_inspection, list_inspections
from src.models.ledger import get_lot, list_samples
from src.models.vehicles import get_vehicle, vehicle_lots, weighing_history


def lot_workspace(lot_id, user):
    with connect() as db:
        lot = get_lot(db, lot_id)
        readings = list_samples(db, lot_id)
        runs = list_inspections(db, lot_id=lot_id, published_only=user["role"] == Role.OBSERVER)
    return {"lot": lot, "samples": readings, "inspections": runs}


def vehicle_workspace(vehicle_id, user):
    with connect() as db:
        vehicle = get_vehicle(db, vehicle_id)
        members = vehicle_lots(db, vehicle_id)
        for member in members:
            member["weighings"] = weighing_history(db, member["id"])
        runs = list_inspections(db, vehicle_id=vehicle_id, published_only=user["role"] == Role.OBSERVER)
    return {"vehicle": vehicle, "members": members, "inspections": runs}


def audit_trail(lot_id):
    with connect() as db:
        get_lot(db, lot_id)
        return db.execute("""
            SELECT e.action, e.reference, e.occurred_at, a.display_name AS actor
            FROM audit_events e LEFT JOIN accounts a ON a.id = e.actor_id
            WHERE lot_id = %s ORDER BY e.id DESC LIMIT 100
        """, (lot_id,)).fetchall()


def vehicle_audit_trail(vehicle_id):
    with connect() as db:
        get_vehicle(db, vehicle_id)
        return db.execute("""
            SELECT e.action, e.reference, e.occurred_at, a.display_name AS actor
            FROM audit_events e LEFT JOIN accounts a ON a.id = e.actor_id
            WHERE e.vehicle_id = %s ORDER BY e.id DESC LIMIT 100
        """, (vehicle_id,)).fetchall()


def _hide_unpublished_comparison(db, report):
    result = report["result"]
    comparison = result.get("comparison")
    if not comparison:
        return
    scope_column = "vehicle_id" if report["vehicle_id"] is not None else "lot_id"
    visible = db.execute(f"""
        SELECT 1 FROM decisions d JOIN inspections i ON i.id = d.inspection_id
        WHERE i.{scope_column} = %s AND i.version = %s
    """, (report["vehicle_id"] if report["vehicle_id"] is not None else report["lot_id"],
          comparison["previous_version"])).fetchone()
    if not visible:
        result["comparison"] = None


def inspection_detail(run_id, user):
    with connect() as db:
        published_only = user["role"] == Role.OBSERVER
        report = get_inspection(db, run_id, published_only)
        if published_only:
            # A comparison may refer to an unpublished parameter version.
            _hide_unpublished_comparison(db, report)
        return report


def download_inspection(run_id, user):
    report = inspection_detail(run_id, user)
    if report["status"] != RunStatus.SUCCEEDED:
        raise HTTPException(409, "验收单尚未产生可导出的结果")
    code = report["vehicle_code"] or report["lot_code"]
    return Response(
        json.dumps(jsonable_encoder(report), ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{code}-V{report["version"]:02}.json"'},
    )
