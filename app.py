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
