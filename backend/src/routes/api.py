from fastapi import APIRouter, Depends, HTTPException

from src.config.runtime import connect, queue
from src.constants.domain import Role
from src.controllers import records
from src.controllers.access import allow, current_user, login
from src.models.ledger import list_lots
from src.models.vehicles import list_vehicles
from src.schemas.inputs import (
    DecisionInput,
    Login,
    LotInput,
    ReweighInput,
    RunInput,
    SampleInput,
    VehicleInput,
    VehicleRunInput,
)
from src.services.inspections import enqueue, publish
from src.services.ledger import add_lot, add_sample
from src.services.vehicles import create_vehicle, enqueue_vehicle, reweigh_lot

router = APIRouter()
analyst = Depends(allow(Role.ANALYST))
reviewer = Depends(allow(Role.REVIEWER))
authenticated = Depends(current_user)


@router.get("/health")
def health():
    with connect() as db:
        db.execute("SELECT 1 FROM inspections LIMIT 1")
    queue.ping()
    return {"status": "ok", "database": "postgresql", "queue": "redis"}


@router.post("/auth/login")
def sign_in(payload: Login):
    return login(payload)


@router.get("/auth/me")
def me(user=authenticated):
    return user


@router.get("/lots")
def lots(_=authenticated):
    with connect() as db:
        return list_lots(db)


@router.post("/lots", status_code=201)
def create_lot(payload: LotInput, user=analyst):
    return add_lot(payload, user["id"])


@router.get("/lots/{lot_id}")
def lot_workspace(lot_id: int, user=authenticated):
    return records.lot_workspace(lot_id, user)


@router.post("/lots/{lot_id}/samples", status_code=201)
def create_sample(lot_id: int, payload: SampleInput, user=analyst):
    return add_sample(lot_id, payload, user["id"])


@router.post("/lots/{lot_id}/reweigh", status_code=200)
def reweigh(lot_id: int, payload: ReweighInput, user=analyst):
    return reweigh_lot(lot_id, payload, user["id"])


@router.get("/lots/{lot_id}/audit")
def audit(lot_id: int, user=authenticated):
    if user["role"] == Role.OBSERVER:
        raise HTTPException(403, "仅称重和复核岗位可查询操作记录")
    return records.audit_trail(lot_id)


@router.post("/lots/{lot_id}/inspections", status_code=202)
def run_inspection(lot_id: int, payload: RunInput, user=analyst):
    return enqueue(lot_id, payload, user["id"])


@router.get("/vehicles")
def vehicles(_=authenticated):
    with connect() as db:
        return list_vehicles(db)


@router.post("/vehicles", status_code=201)
def create_vehicle_record(payload: VehicleInput, user=analyst):
    return create_vehicle(payload, user["id"])


@router.get("/vehicles/{vehicle_id}")
def vehicle_workspace(vehicle_id: int, user=authenticated):
    return records.vehicle_workspace(vehicle_id, user)


@router.get("/vehicles/{vehicle_id}/audit")
def vehicle_audit(vehicle_id: int, user=authenticated):
    if user["role"] == Role.OBSERVER:
        raise HTTPException(403, "仅称重和复核岗位可查询操作记录")
    return records.vehicle_audit_trail(vehicle_id)


@router.post("/vehicles/{vehicle_id}/inspections", status_code=202)
def run_vehicle_inspection(vehicle_id: int, payload: VehicleRunInput, user=analyst):
    return enqueue_vehicle(vehicle_id, payload, user["id"])


@router.get("/inspections/{run_id}")
def inspection(run_id: int, user=authenticated):
    return records.inspection_detail(run_id, user)


@router.post("/inspections/{run_id}/decision", status_code=201)
def release_decision(run_id: int, payload: DecisionInput, user=reviewer):
    return publish(run_id, payload, user["id"])


@router.get("/inspections/{run_id}/export")
def export(run_id: int, user=authenticated):
    return records.download_inspection(run_id, user)
