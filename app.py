from time import perf_counter
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
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


UI_HTML = r"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>UGASHIP</title>
<style>
:root{--bg:#f4f6f8;--card:#fff;--ink:#111827;--muted:#667085;--line:#e5e7eb;--nav:#101828}*{box-sizing:border-box}body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:var(--bg);color:var(--ink)}header{background:var(--nav);color:#fff;padding:18px}header div{max-width:980px;margin:auto}main{max-width:980px;margin:auto;padding:20px}.hero h1{margin:0 0 6px;font-size:30px}.hero p{margin:0;color:var(--muted)}.actions{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:20px 0}.action{background:#fff;border:1px solid var(--line);border-radius:18px;padding:18px;text-align:left;cursor:pointer}.action strong{display:block;font-size:18px;margin-bottom:5px}.card{background:#fff;border:1px solid var(--line);border-radius:18px;padding:18px;margin-top:14px}.hidden{display:none}.row{display:grid;grid-template-columns:1fr 1fr;gap:12px}label{display:grid;gap:6px;font-size:13px;font-weight:700}input,button{font:inherit}input{padding:12px;border:1px solid #d0d5dd;border-radius:10px}button{padding:12px 15px;border:0;border-radius:10px;background:var(--nav);color:#fff;font-weight:800;cursor:pointer}.secondary{background:#eef2f6;color:var(--ink)}.msg{margin-top:12px;white-space:pre-wrap}.muted{color:var(--muted)}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:10px;border-bottom:1px solid var(--line);font-size:13px}@media(max-width:700px){.actions{grid-template-columns:1fr}.row{grid-template-columns:1fr}}</style></head><body>
<header><div><strong>UGASHIP</strong><div style="font-size:12px;color:#d0d5dd">Simple Logistics Console</div></div></header>
<main><section class="hero"><h1>What do you want to do?</h1><p>Validate a destination, record a delivery, or check logistics performance.</p><p id="handoff" class="muted"></p></section>
<div class="actions">
<button class="action secondary" onclick="show('destination')"><strong>Validate Destination</strong><span class="muted">Check routing before shipping</span></button>
<button class="action secondary" onclick="show('delivery')"><strong>Record Delivery</strong><span class="muted">Capture dispatch and delivery performance</span></button>
<button class="action secondary" onclick="show('kpis');loadKpis()"><strong>View KPIs</strong><span class="muted">On-time delivery, freight cost, lead time</span></button>
</div>
<section id="destination" class="card"><h2>Validate Destination</h2><div class="row"><label>Destination ZIP / code<input id="zip"></label><div style="align-self:end"><button onclick="validateZip()">Check destination</button></div></div><div id="destinationMsg" class="msg"></div></section>
<section id="delivery" class="card hidden"><h2>Record Delivery</h2><div class="row"><label>Shipment ID<input id="shipmentId"></label><label>Order ID<input id="orderId"></label><label>Dispatched at<input id="dispatched" type="datetime-local"></label><label>Delivered at<input id="delivered" type="datetime-local"></label><label>Promised at<input id="promised" type="datetime-local"></label><label>Freight cost<input id="freight" type="number" min="0" step="0.01" value="0"></label><label>Order value<input id="orderValue" type="number" min="0" step="0.01" value="0"></label></div><div style="margin-top:14px"><button onclick="recordDelivery()">Save delivery</button></div><div id="deliveryMsg" class="msg"></div></section>
<section id="kpis" class="card hidden"><h2>Logistics KPIs</h2><button onclick="loadKpis()">Refresh</button><div id="kpiBox" class="msg"></div></section>
</main><script>
function show(id){for(const x of ['destination','delivery','kpis'])document.getElementById(x).classList.toggle('hidden',x!==id)}
function friendly(detail,status){const raw=typeof detail==='string'?detail:'';const map={delivered_before_dispatched:'Delivery time cannot be earlier than dispatch time.',destination_not_found:'That destination could not be resolved.',invalid_destination:'Check the destination code and try again.'};if(map[raw])return map[raw];if(status>=500)return 'Shipping service is temporarily unable to complete that action.';return raw?raw.replaceAll('_',' '):'Request failed'}
async function jfetch(path,opt){const r=await fetch(path,opt);let d={};try{d=await r.json()}catch(e){}if(!r.ok)throw Error(friendly(d.detail,r.status));return d}
async function validateZip(){const box=document.getElementById('destinationMsg');box.textContent='Checking…';try{const d=await jfetch('/v1/shipments/validate-destination',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({destination_zip:document.getElementById('zip').value.trim()})});box.textContent=JSON.stringify(d,null,2)}catch(e){box.textContent=e.message}}
function iso(id){const v=document.getElementById(id).value;return v?new Date(v).toISOString():null}
async function recordDelivery(){const box=document.getElementById('deliveryMsg');box.textContent='Saving…';try{const body={shipment_id:shipmentId.value.trim(),order_id:orderId.value.trim(),dispatched_at:iso('dispatched'),delivered_at:iso('delivered'),promised_at:iso('promised'),freight_cost:Number(freight.value||0),order_value:Number(orderValue.value||0),delivered_in_full:true,damage_free:true,documentation_complete:true};const d=await jfetch('/v1/performance/shipments',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});box.textContent='Saved. '+(d.on_time===true?'On time.':d.on_time===false?'Late.':'Delivery recorded.')}catch(e){box.textContent=e.message}}
function applyHandoff(){const q=new URLSearchParams(location.search);const destination=q.get('destination');const shipment=q.get('shipment');const order=q.get('order');if(destination){document.getElementById('zip').value=destination;show('destination')}if(shipment){document.getElementById('shipmentId').value=shipment;show('delivery')}if(order)document.getElementById('orderId').value=order;const parts=[];if(shipment)parts.push('Shipment '+shipment);if(order)parts.push('Order '+order);if(destination)parts.push('Destination '+destination);document.getElementById('handoff').textContent=parts.length?'Opened from warehouse: '+parts.join(' · '):''}
async function loadKpis(){const box=document.getElementById('kpiBox');box.textContent='Loading…';try{const d=await jfetch('/v1/performance/kpis');const rows=(d.observations||[]).map(x=>'<tr><td>'+x.kpi_key.replaceAll('_',' ')+'</td><td>'+((x.value??'—'))+'</td></tr>').join('');box.innerHTML='<table><thead><tr><th>Metric</th><th>Value</th></tr></thead><tbody>'+rows+'</tbody></table>'}catch(e){box.textContent=e.message}}
applyHandoff();</script></body></html>"""

@app.get("/console", response_class=HTMLResponse)
def console():
    return HTMLResponse(UI_HTML, headers={"Cache-Control":"no-store"})

@app.get("/ui", response_class=HTMLResponse)
def ui():
    return HTMLResponse(UI_HTML, headers={"Cache-Control":"no-store"})
