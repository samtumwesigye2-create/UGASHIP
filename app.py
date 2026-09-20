from time import perf_counter
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from destination import DestinationError, resolve_destination_zip

VERSION = "0.2.0"
app = FastAPI(title="UGASHIP", version=VERSION)


class DestinationValidationIn(BaseModel):
    destination_zip: str = Field(min_length=1, max_length=6)


class LoadTestTransaction(BaseModel):
    transaction_id: str = Field(min_length=1, max_length=64)
    order_id: str = Field(min_length=1, max_length=64)
    customer_id: str = Field(min_length=1, max_length=64)
    product_name: str = Field(min_length=1, max_length=128)
    quantity: int = Field(ge=0)
    sales: float
    profit: float
    order_status: str = Field(min_length=1, max_length=64)
    delivery_status: str = Field(min_length=1, max_length=64)
    shipping_mode: str = Field(min_length=1, max_length=64)
    city: str = Field(min_length=1, max_length=128)
    country: str = Field(min_length=1, max_length=128)
    market: str = Field(min_length=1, max_length=128)
    late_delivery_risk: int = Field(ge=0, le=1)
    actual_shipping_days: int = Field(ge=0)
    scheduled_shipping_days: int = Field(ge=0)
    test_run_id: str | None = None
    batch_id: int | None = None
    sequence: int | None = None
    test_mode: bool = True
    synthetic: bool = True


class LoadTestBatch(BaseModel):
    transactions: list[LoadTestTransaction] = Field(min_length=1, max_length=12000)


class ShipmentPerformanceIn(BaseModel):
    shipment_id: str = Field(min_length=1, max_length=120)
    order_id: str = Field(min_length=1, max_length=120)
    dispatched_at: str
    delivered_at: str | None = None
    promised_at: str | None = None
    freight_cost: float = Field(default=0, ge=0)
    order_value: float = Field(default=0, ge=0)
    delivered_in_full: bool = True
    damage_free: bool = True
    documentation_complete: bool = True
    service_level_target_minutes: float | None = Field(default=None, ge=0)


SHIPMENT_PERFORMANCE: list[dict[str, Any]] = []


def resolve_or_http_error(code: str) -> dict:
    try:
        return resolve_destination_zip(code)
    except DestinationError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


@app.get("/")
def root():
    return {"system": "UGASHIP", "status": "online", "version": VERSION}


@app.get("/health")
def health():
    return {"status": "ok", "service": "UGASHIP", "version": VERSION}


@app.get("/v1/destinations/zip/{code}")
def destination_lookup(code: str):
    return resolve_or_http_error(code)


@app.post("/v1/shipments/validate-destination")
def validate_destination(body: DestinationValidationIn):
    return resolve_or_http_error(body.destination_zip)


@app.post("/v1/load-test/transactions")
def ingest_load_test(body: LoadTestBatch) -> dict[str, Any]:
    started = perf_counter()
    rows = body.transactions

    transaction_ids = [row.transaction_id for row in rows]
    unique_transaction_ids = len(set(transaction_ids))
    duplicate_transaction_ids = len(rows) - unique_transaction_ids

    late_delivery_count = sum(row.late_delivery_risk for row in rows)
    late_delivery_mismatches = sum(
        int((row.actual_shipping_days > row.scheduled_shipping_days) != bool(row.late_delivery_risk))
        for row in rows
    )

    total_sales = sum(row.sales for row in rows)
    total_profit = sum(row.profit for row in rows)
    total_units = sum(row.quantity for row in rows)

    elapsed = perf_counter() - started
    processing_ms = elapsed * 1000
    records_per_second = len(rows) / elapsed if elapsed > 0 else float("inf")

    return {
        "ok": duplicate_transaction_ids == 0 and late_delivery_mismatches == 0,
        "service": "UGASHIP",
        "version": VERSION,
        "test_run_id": rows[0].test_run_id,
        "records_received": len(rows),
        "unique_transaction_ids": unique_transaction_ids,
        "duplicate_transaction_ids": duplicate_transaction_ids,
        "late_delivery_count": late_delivery_count,
        "late_delivery_rate": late_delivery_count / len(rows),
        "late_delivery_logic_mismatches": late_delivery_mismatches,
        "total_sales": round(total_sales, 2),
        "total_profit": round(total_profit, 2),
        "total_units": total_units,
        "processing_ms": round(processing_ms, 3),
        "records_per_second": round(records_per_second, 2),
        "mode": "synthetic-load-test",
        "persisted": False,
    }


@app.post("/v1/performance/shipments", status_code=201)
def record_shipment_performance(body: ShipmentPerformanceIn):
    from datetime import datetime
    def dt(v):
        if not v: return None
        return datetime.fromisoformat(v.replace("Z","+00:00"))
    dispatched=dt(body.dispatched_at); delivered=dt(body.delivered_at); promised=dt(body.promised_at)
    if delivered and delivered < dispatched: raise HTTPException(422,"delivered_before_dispatched")
    row=body.model_dump()
    row["delivery_lead_minutes"]=((delivered-dispatched).total_seconds()/60.0) if delivered else None
    row["on_time"]=(delivered<=promised) if delivered and promised else None
    row["perfect_order"]=bool(delivered and row["on_time"] is not False and body.delivered_in_full and body.damage_free and body.documentation_complete)
    SHIPMENT_PERFORMANCE.append(row)
    if len(SHIPMENT_PERFORMANCE)>10000: del SHIPMENT_PERFORMANCE[:len(SHIPMENT_PERFORMANCE)-10000]
    return row

@app.get("/v1/performance/kpis")
def shipment_kpis():
    rows=SHIPMENT_PERFORMANCE
    delivered=[r for r in rows if r.get("delivered_at")]
    timed=[r for r in delivered if r.get("on_time") is not None]
    total_freight=sum(float(r.get("freight_cost") or 0) for r in rows)
    total_value=sum(float(r.get("order_value") or 0) for r in rows)
    leads=[float(r["delivery_lead_minutes"]) for r in delivered if r.get("delivery_lead_minutes") is not None]
    perfect=sum(1 for r in delivered if r.get("perfect_order"))
    service=[r for r in delivered if r.get("service_level_target_minutes") is not None and r.get("delivery_lead_minutes") is not None]
    return {"source_system":"UGASHIP","observations":[
      {"kpi_key":"on_time_delivery_rate","value":round(100*sum(1 for r in timed if r["on_time"])/len(timed),4) if timed else None},
      {"kpi_key":"freight_cost_per_shipment","value":round(total_freight/len(rows),4) if rows else None},
      {"kpi_key":"logistics_cost_ratio","value":round(100*total_freight/total_value,4) if total_value>0 else None},
      {"kpi_key":"delivery_lead_time","value":round(sum(leads)/len(leads),4) if leads else None},
      {"kpi_key":"perfect_order_fulfillment","value":round(100*perfect/len(delivered),4) if delivered else None},
      {"kpi_key":"service_level_achievement","value":round(100*sum(1 for r in service if r["delivery_lead_minutes"]<=r["service_level_target_minutes"])/len(service),4) if service else None}
    ],"records":len(rows)}
