# UGASHIP ZIP Destination Resolution Design

## Goal
Build UGASHIP's first production-ready destination-resolution flow so shipment destinations can be validated against the working national ZIPPER/UGAMAP routing chain before shipment creation.

## Approved Architecture

UGASHIP does not maintain its own ZIP registry. It resolves destination ZIPs through UGAMAP, which in turn uses UNG-ZIPPER as the source of truth:

`UGASHIP -> UGAMAP /routing/to-zip -> UNG-ZIPPER`

This preserves one authoritative ZIP source and avoids duplicated ZIP data inside UGASHIP.

## Scope

Version 1 contains only:

1. A health/root endpoint for service verification.
2. A ZIP destination lookup endpoint.
3. Shipment destination validation using the same resolver.
4. Clear fail-safe handling when ZIPPER/UGAMAP is unavailable or returns an unknown ZIP.
5. Production configuration through an environment variable for the UGAMAP base URL.
6. Acceptance tests against known-good ZIPs: `10000`, `10034`, `10427`, `10521`, `10689`.

VECTOR, NEXUS, PULSAR, JANUS, payment, tracking, inventory, and shipment persistence are explicitly outside this first slice.

## API

### GET `/health`
Returns service readiness metadata.

Example:

```json
{
  "status": "ok",
  "service": "UGASHIP",
  "version": "0.1.0"
}
```

### GET `/v1/destinations/zip/{code}`

Purpose: validate and resolve a 5-digit ZIP before a shipment uses it.

Behavior:
- Accept numeric input from 1 to 5 digits.
- Normalize by left-padding to exactly 5 digits.
- Reject non-numeric input with HTTP 422.
- Call UGAMAP `GET /destination/zip/{code}`.
- Return HTTP 404 when UGAMAP reports an unknown ZIP.
- Return HTTP 502 for upstream HTTP failures >=500.
- Return HTTP 503 when UGAMAP is unreachable or times out.

Successful response fields:

```json
{
  "ok": true,
  "code": "10034",
  "district": "Kampala",
  "name": "Kampala",
  "area_type": "urban",
  "population_covered": 3768,
  "latitude": 0.49729955933456793,
  "longitude": 32.667045285449205,
  "route_ready": true,
  "source": "UNG-ZIPPER->UGAMAP"
}
```

### POST `/v1/shipments/validate-destination`

Request:

```json
{
  "destination_zip": "10034"
}
```

Purpose: provide the exact validation operation future shipment creation will call before accepting a destination.

Response: the same normalized destination object returned by `GET /v1/destinations/zip/{code}`.

No shipment record is created in this version.

## Components

### `app.py`
FastAPI application and public endpoints only.

### `destination.py`
Owns ZIP normalization, upstream UGAMAP HTTP calls, response normalization, and upstream error translation. This isolates destination logic from the API layer.

### `tests/test_destination.py`
Unit tests for ZIP normalization, success mapping, invalid input, unknown ZIP, and upstream failure behavior.

### `tests/test_api.py`
Endpoint-level tests using dependency/HTTP mocking so tests do not depend on production services.

## Configuration

`UGAMAP_BASE_URL` defaults to:

`https://uganda-grid-api-clean-production.up.railway.app`

The value is overrideable in Railway without changing code.

## Error Handling

- Unknown ZIP: 404 with `destination_zip_not_found`.
- Non-numeric ZIP: 422 with `destination_zip_must_be_numeric`.
- Upstream 4xx other than 404: preserve the meaningful status where safe.
- Upstream 5xx: translate to 502 `ugamap_upstream_error`.
- Network/timeout failure: 503 `ugamap_unavailable`.
- Malformed upstream payload missing destination coordinates/code: 502 `ugamap_destination_invalid`.

UGASHIP must fail closed: an unresolved destination cannot be accepted as valid.

## Acceptance Criteria

1. Service starts successfully on Railway.
2. `/health` returns HTTP 200.
3. `/v1/destinations/zip/{code}` resolves each known-good ZIP: `10000`, `10034`, `10427`, `10521`, `10689`.
4. Returned code, district, coordinates, area type, and population match the upstream ZIPPER/UGAMAP response.
5. Non-numeric ZIP input is rejected.
6. A known-invalid ZIP returns 404.
7. Upstream outage produces a fail-safe 503/502 rather than a false successful destination.
8. No duplicate ZIP table or ZIP database is created inside UGASHIP.

## Future Extension Boundary

After this slice passes production acceptance, shipment creation may consume `resolve_destination_zip()` and then hand off validated shipment data to VECTOR, NEXUS, PULSAR, and JANUS. Those integrations must not bypass this resolver.