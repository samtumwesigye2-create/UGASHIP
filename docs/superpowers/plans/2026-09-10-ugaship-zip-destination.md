# UGASHIP ZIP Destination Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build UGASHIP's first production-ready ZIP destination-resolution flow using the existing UGAMAP -> UNG-ZIPPER chain.

**Architecture:** UGASHIP remains stateless for ZIP data. A focused `destination.py` module normalizes ZIP input, calls UGAMAP, maps the destination payload, and fails closed on upstream errors; `app.py` exposes health and destination-validation endpoints that reuse this resolver.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, urllib.request, pytest, FastAPI TestClient

**Spec:** `docs/superpowers/specs/2026-09-10-ugaship-zip-destination-design.md`

## Global Constraints

- UNG-ZIPPER remains the authoritative ZIP source through UGAMAP.
- Do not create a ZIP table or duplicate registry inside UGASHIP.
- `UGAMAP_BASE_URL` defaults to `https://uganda-grid-api-clean-production.up.railway.app` and remains environment-configurable.
- ZIP inputs are numeric and normalized to exactly five digits.
- UGASHIP must fail closed when a destination cannot be resolved.
- Version 1 does not create or persist shipments.
- Known-good acceptance ZIPs are `10000`, `10034`, `10427`, `10521`, and `10689`.

---

## File Structure

- `app.py` — FastAPI app, health endpoint, destination lookup endpoint, destination validation endpoint.
- `destination.py` — ZIP normalization, UGAMAP client, response mapping, upstream error translation.
- `tests/test_destination.py` — resolver unit tests.
- `tests/test_api.py` — endpoint behavior tests.
- `requirements.txt` — runtime/test dependencies.
- `README.md` — local run instructions, API examples, environment variable, Railway start command.

### Task 1: Destination resolver

**Files:**
- Create: `destination.py`
- Create: `tests/test_destination.py`

**Interfaces:**
- Produces: `normalize_zip(code: str) -> str`
- Produces: `resolve_destination_zip(code: str) -> dict`
- Consumes: `UGAMAP_BASE_URL` environment variable

- [ ] **Step 1: Write failing normalization tests**

```python
from destination import normalize_zip


def test_normalize_zip_pads_numeric_code():
    assert normalize_zip("34") == "00034"


def test_normalize_zip_preserves_five_digits():
    assert normalize_zip("10034") == "10034"
```

- [ ] **Step 2: Run the normalization tests and verify failure**

Run:

```bash
pytest tests/test_destination.py::test_normalize_zip_pads_numeric_code tests/test_destination.py::test_normalize_zip_preserves_five_digits -v
```

Expected: FAIL because `destination.py`/`normalize_zip` does not exist.

- [ ] **Step 3: Implement ZIP normalization and typed resolver errors**

```python
import json
import os
import urllib.error
import urllib.request

UGAMAP_BASE_URL = os.getenv(
    "UGAMAP_BASE_URL",
    "https://uganda-grid-api-clean-production.up.railway.app",
).rstrip("/")


class DestinationError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def normalize_zip(code: str) -> str:
    value = str(code or "").strip()
    if not value.isdigit():
        raise DestinationError(422, "destination_zip_must_be_numeric")
    if len(value) > 5:
        raise DestinationError(422, "destination_zip_must_be_1_to_5_digits")
    return value.zfill(5)
```

- [ ] **Step 4: Add resolver tests with a mocked upstream**

Append tests that monkeypatch `urllib.request.urlopen` and assert the resolver returns:

```python
{
    "ok": True,
    "code": "10034",
    "district": "Kampala",
    "name": "Kampala",
    "area_type": "urban",
    "population_covered": 3768,
    "latitude": 0.49729955933456793,
    "longitude": 32.667045285449205,
    "route_ready": True,
    "source": "UNG-ZIPPER->UGAMAP",
}
```

Use an upstream fixture shaped as:

```python
{
    "code": "10034",
    "district": "Kampala",
    "name": "Kampala",
    "area_type": "urban",
    "population_covered": 3768,
    "latitude": 0.49729955933456793,
    "longitude": 32.667045285449205,
}
```

- [ ] **Step 5: Implement `resolve_destination_zip()`**

```python
def resolve_destination_zip(code: str) -> dict:
    normalized = normalize_zip(code)
    req = urllib.request.Request(
        f"{UGAMAP_BASE_URL}/destination/zip/{normalized}",
        headers={"Accept": "application/json", "User-Agent": "UGASHIP/0.1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise DestinationError(404, "destination_zip_not_found")
        if exc.code >= 500:
            raise DestinationError(502, "ugamap_upstream_error")
        raise DestinationError(exc.code, "ugamap_request_rejected")
    except Exception:
        raise DestinationError(503, "ugamap_unavailable")

    required = ("code", "latitude", "longitude")
    if any(payload.get(key) is None for key in required):
        raise DestinationError(502, "ugamap_destination_invalid")

    return {
        "ok": True,
        "code": str(payload["code"]).zfill(5),
        "district": payload.get("district"),
        "name": payload.get("name") or payload.get("district"),
        "area_type": payload.get("area_type"),
        "population_covered": payload.get("population_covered"),
        "latitude": payload["latitude"],
        "longitude": payload["longitude"],
        "route_ready": True,
        "source": "UNG-ZIPPER->UGAMAP",
    }
```

- [ ] **Step 6: Add explicit failure tests**

Add tests asserting:
- `normalize_zip("ABC")` raises `DestinationError(422, "destination_zip_must_be_numeric")`.
- six-digit input raises `destination_zip_must_be_1_to_5_digits`.
- mocked HTTP 404 becomes `DestinationError(404, "destination_zip_not_found")`.
- mocked HTTP 503 becomes `DestinationError(502, "ugamap_upstream_error")`.
- mocked timeout/network exception becomes `DestinationError(503, "ugamap_unavailable")`.
- missing latitude becomes `DestinationError(502, "ugamap_destination_invalid")`.

- [ ] **Step 7: Run resolver tests**

```bash
pytest tests/test_destination.py -v
```

Expected: all resolver tests PASS.

- [ ] **Step 8: Commit**

```bash
git add destination.py tests/test_destination.py
git commit -m "feat: add UGASHIP ZIP destination resolver"
```

### Task 2: Public API endpoints

**Files:**
- Create: `app.py`
- Create: `tests/test_api.py`

**Interfaces:**
- Consumes: `resolve_destination_zip(code: str) -> dict`
- Produces: `GET /health`
- Produces: `GET /v1/destinations/zip/{code}`
- Produces: `POST /v1/shipments/validate-destination`

- [ ] **Step 1: Write failing health and lookup endpoint tests**

```python
from fastapi.testclient import TestClient
import app as app_module

client = TestClient(app_module.app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "UGASHIP",
        "version": "0.1.0",
    }


def test_destination_lookup(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "resolve_destination_zip",
        lambda code: {
            "ok": True,
            "code": "10034",
            "district": "Kampala",
            "name": "Kampala",
            "area_type": "urban",
            "population_covered": 3768,
            "latitude": 0.49729955933456793,
            "longitude": 32.667045285449205,
            "route_ready": True,
            "source": "UNG-ZIPPER->UGAMAP",
        },
    )
    response = client.get("/v1/destinations/zip/10034")
    assert response.status_code == 200
    assert response.json()["code"] == "10034"
```

- [ ] **Step 2: Run API tests and verify failure**

```bash
pytest tests/test_api.py -v
```

Expected: FAIL because `app.py` does not exist.

- [ ] **Step 3: Implement FastAPI app and lookup endpoint**

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from destination import DestinationError, resolve_destination_zip

VERSION = "0.1.0"
app = FastAPI(title="UGASHIP", version=VERSION)


class DestinationValidationIn(BaseModel):
    destination_zip: str = Field(min_length=1, max_length=6)


def resolve_or_http_error(code: str) -> dict:
    try:
        return resolve_destination_zip(code)
    except DestinationError as exc:
        raise HTTPException(exc.status_code, exc.detail)


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
```

- [ ] **Step 4: Add validation endpoint and error propagation tests**

Add tests asserting:
- POST body `{"destination_zip":"10034"}` returns the same destination object as GET.
- resolver `DestinationError(404, "destination_zip_not_found")` becomes HTTP 404.
- resolver `DestinationError(503, "ugamap_unavailable")` becomes HTTP 503.

- [ ] **Step 5: Run API tests**

```bash
pytest tests/test_api.py -v
```

Expected: all API tests PASS.

- [ ] **Step 6: Commit**

```bash
git add app.py tests/test_api.py
git commit -m "feat: expose UGASHIP ZIP destination API"
```

### Task 3: Runtime packaging and documentation

**Files:**
- Create: `requirements.txt`
- Create: `README.md`

**Interfaces:**
- Produces a Railway-startable FastAPI service.

- [ ] **Step 1: Add runtime dependencies**

`requirements.txt`:

```text
fastapi>=0.116,<1
uvicorn[standard]>=0.35,<1
pydantic>=2.11,<3
pytest>=8.4,<9
httpx>=0.28,<1
```

- [ ] **Step 2: Add README with exact local and Railway commands**

Document:

```bash
pip install -r requirements.txt
pytest -v
uvicorn app:app --host 0.0.0.0 --port 8080
```

Railway start command:

```text
uvicorn app:app --host 0.0.0.0 --port $PORT
```

Document `UGAMAP_BASE_URL` and the three public endpoints.

- [ ] **Step 3: Run the full local test suite**

```bash
pytest -v
```

Expected: all tests PASS.

- [ ] **Step 4: Import/start smoke test**

```bash
python -c "from app import app; print(app.title, app.version)"
```

Expected:

```text
UGASHIP 0.1.0
```

- [ ] **Step 5: Commit**

```bash
git add requirements.txt README.md
git commit -m "chore: package UGASHIP destination service"
```

### Task 4: Railway deployment and production acceptance

**Files:**
- No source changes expected unless deployment reveals a verified defect.

**Interfaces:**
- Consumes repository `samtumwesigye2-create/UGASHIP` main branch.
- Produces live UGASHIP Railway service URL.

- [ ] **Step 1: Create a standalone Railway project named `UGASHIP`**

Use the connected repository `samtumwesigye2-create/UGASHIP`, branch `main`.

- [ ] **Step 2: Configure runtime**

Set start command:

```text
uvicorn app:app --host 0.0.0.0 --port $PORT
```

Set healthcheck path:

```text
/health
```

Set environment variable:

```text
UGAMAP_BASE_URL=https://uganda-grid-api-clean-production.up.railway.app
```

- [ ] **Step 3: Wait for deployment success and verify health**

Expected:
- Deployment status `SUCCESS`.
- `GET /health` returns HTTP 200.

- [ ] **Step 4: Production destination acceptance**

For each code below, call `GET /v1/destinations/zip/{code}`:

```text
10000
10034
10427
10521
10689
```

Expected for every code:
- HTTP 200.
- response `ok == true`.
- returned `code` equals requested code.
- district/latitude/longitude are non-null.
- `route_ready == true`.
- `source == "UNG-ZIPPER->UGAMAP"`.

- [ ] **Step 5: Production rejection acceptance**

Call:

```text
GET /v1/destinations/zip/ABCDE
```

Expected: HTTP 422.

Call a verified unassigned numeric ZIP discovered from ZIPPER validation.
Expected: HTTP 404.

- [ ] **Step 6: Validate shipment-destination endpoint without creating shipments**

For `10034`:

```http
POST /v1/shipments/validate-destination
Content-Type: application/json

{"destination_zip":"10034"}
```

Expected: HTTP 200 with the same normalized destination fields as the GET lookup.

- [ ] **Step 7: Record production acceptance result**

Acceptance passes only when health, all five known-good ZIPs, invalid-input rejection, unknown-ZIP rejection, and POST validation all match the spec. Do not claim completion before these checks are observed live.
