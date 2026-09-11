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
            raise DestinationError(404, "destination_zip_not_found") from exc
        if exc.code >= 500:
            raise DestinationError(502, "ugamap_upstream_error") from exc
        raise DestinationError(exc.code, "ugamap_request_rejected") from exc
    except Exception as exc:
        raise DestinationError(503, "ugamap_unavailable") from exc

    destination = payload.get("destination") if isinstance(payload, dict) else None
    if not isinstance(destination, dict):
        raise DestinationError(502, "ugamap_destination_invalid")
    if any(destination.get(key) is None for key in ("code", "latitude", "longitude")):
        raise DestinationError(502, "ugamap_destination_invalid")

    return {
        "ok": True,
        "code": str(destination["code"]).zfill(5),
        "district": destination.get("district"),
        "name": destination.get("name") or destination.get("district"),
        "area_type": destination.get("area_type"),
        "population_covered": destination.get("population_covered"),
        "latitude": destination["latitude"],
        "longitude": destination["longitude"],
        "route_ready": True,
        "source": "UNG-ZIPPER->UGAMAP",
    }
