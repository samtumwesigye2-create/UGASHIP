from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/shipments", tags=["shipment-execution"])

SHIPMENTS: dict[str, dict] = {}
EVENTS: list[dict] = []

STATE_ORDER = {
    "planned": 0,
    "booked": 1,
    "manifested": 2,
    "dispatched": 3,
    "in_transit": 4,
    "arrived": 5,
    "delivered": 6,
    "pod_confirmed": 7,
    "closed": 8,
}

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def _event(shipment_id: str, event_type: str, payload: dict | None = None):
    row = {
        "event_id": str(uuid4()),
        "shipment_id": shipment_id,
        "event_type": event_type,
        "occurred_at": now_iso(),
        "payload": payload or {},
    }
    EVENTS.append(row)
    return row

def _get(shipment_id: str):
    row = SHIPMENTS.get(shipment_id)
    if not row:
        raise HTTPException(404, "shipment_not_found")
    return row

def _transition(shipment_id: str, target: str, event_type: str, payload: dict | None = None):
    row = _get(shipment_id)
    current = row["status"]
    if target not in STATE_ORDER:
        raise HTTPException(422, "invalid_shipment_state")
    if STATE_ORDER[target] != STATE_ORDER[current] + 1:
        raise HTTPException(409, f"invalid_transition:{current}->{target}")
    row["status"] = target
    row["updated_at"] = now_iso()
    ev = _event(shipment_id, event_type, payload)
    return {"shipment": row, "event": ev}

class ShipmentCreateIn(BaseModel):
    order_reference: str = Field(min_length=1, max_length=120)
    origin: str = Field(min_length=1, max_length=160)
    destination: str = Field(min_length=1, max_length=160)
    carrier_code: str | None = Field(default=None, max_length=64)
    service_code: str | None = Field(default=None, max_length=64)
    package_count: int = Field(gt=0)
    total_weight_kg: float = Field(ge=0)
    freight_cost: float = Field(default=0, ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)

class BookingIn(BaseModel):
    carrier_code: str = Field(min_length=1, max_length=64)
    service_code: str = Field(min_length=1, max_length=64)
    booking_reference: str = Field(min_length=1, max_length=120)

class ManifestIn(BaseModel):
    manifest_reference: str = Field(min_length=1, max_length=120)

class DispatchIn(BaseModel):
    dispatch_reference: str = Field(min_length=1, max_length=120)

class TrackingIn(BaseModel):
    milestone: str = Field(min_length=1, max_length=64)
    location: str | None = Field(default=None, max_length=160)
    note: str = Field(default="", max_length=500)

class PODIn(BaseModel):
    recipient: str = Field(min_length=1, max_length=160)
    proof_reference: str = Field(min_length=1, max_length=160)

@router.post("", status_code=201)
def create_shipment(body: ShipmentCreateIn):
    shipment_id = str(uuid4())
    t = now_iso()
    row = {
        "id": shipment_id,
        "order_reference": body.order_reference,
        "origin": body.origin,
        "destination": body.destination,
        "carrier_code": body.carrier_code,
        "service_code": body.service_code,
        "booking_reference": None,
        "manifest_reference": None,
        "dispatch_reference": None,
        "package_count": body.package_count,
        "total_weight_kg": body.total_weight_kg,
        "freight_cost": body.freight_cost,
        "currency": body.currency.upper(),
        "status": "planned",
        "created_at": t,
        "updated_at": t,
    }
    SHIPMENTS[shipment_id] = row
    return {"shipment": row, "event": _event(shipment_id, "shipment.created")}

@router.post("/{shipment_id}/book")
def book_shipment(shipment_id: str, body: BookingIn):
    row = _get(shipment_id)
    row["carrier_code"] = body.carrier_code
    row["service_code"] = body.service_code
    row["booking_reference"] = body.booking_reference
    return _transition(shipment_id, "booked", "shipment.booked", body.model_dump())

@router.post("/{shipment_id}/manifest")
def manifest_shipment(shipment_id: str, body: ManifestIn):
    row = _get(shipment_id)
    row["manifest_reference"] = body.manifest_reference
    return _transition(shipment_id, "manifested", "shipment.manifested", body.model_dump())

@router.post("/{shipment_id}/dispatch")
def dispatch_shipment(shipment_id: str, body: DispatchIn):
    row = _get(shipment_id)
    row["dispatch_reference"] = body.dispatch_reference
    result = _transition(shipment_id, "dispatched", "shipment.dispatched", body.model_dump())
    return result

@router.post("/{shipment_id}/tracking")
def add_tracking(shipment_id: str, body: TrackingIn):
    row = _get(shipment_id)
    milestone = body.milestone.strip().lower()
    mapping = {
        "in_transit": "in_transit",
        "arrived": "arrived",
        "delivered": "delivered",
    }
    if milestone not in mapping:
        raise HTTPException(422, "unsupported_tracking_milestone")
    return _transition(shipment_id, mapping[milestone], f"shipment.{milestone}", body.model_dump())

@router.post("/{shipment_id}/pod")
def confirm_pod(shipment_id: str, body: PODIn):
    return _transition(shipment_id, "pod_confirmed", "pod.recorded", body.model_dump())

@router.post("/{shipment_id}/close")
def close_shipment(shipment_id: str):
    return _transition(shipment_id, "closed", "shipment.closed")

@router.get("/{shipment_id}")
def get_shipment(shipment_id: str):
    row = _get(shipment_id)
    events = [e for e in EVENTS if e["shipment_id"] == shipment_id]
    return {"shipment": row, "events": events}

@router.get("")
def list_shipments(status: str | None = None):
    rows = list(SHIPMENTS.values())
    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows
