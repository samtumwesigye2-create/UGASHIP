from fastapi.testclient import TestClient

import app as app_module
from destination import DestinationError

client = TestClient(app_module.app)

DESTINATION = {
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


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "UGASHIP", "version": "0.1.0"}


def test_destination_lookup(monkeypatch):
    monkeypatch.setattr(app_module, "resolve_destination_zip", lambda code: DESTINATION)
    response = client.get("/v1/destinations/zip/10034")
    assert response.status_code == 200
    assert response.json() == DESTINATION


def test_validate_destination(monkeypatch):
    monkeypatch.setattr(app_module, "resolve_destination_zip", lambda code: DESTINATION)
    response = client.post("/v1/shipments/validate-destination", json={"destination_zip": "10034"})
    assert response.status_code == 200
    assert response.json() == DESTINATION


def test_lookup_propagates_destination_error(monkeypatch):
    def fail(code):
        raise DestinationError(404, "destination_zip_not_found")
    monkeypatch.setattr(app_module, "resolve_destination_zip", fail)
    response = client.get("/v1/destinations/zip/99999")
    assert response.status_code == 404
    assert response.json()["detail"] == "destination_zip_not_found"


def test_validation_propagates_upstream_unavailable(monkeypatch):
    def fail(code):
        raise DestinationError(503, "ugamap_unavailable")
    monkeypatch.setattr(app_module, "resolve_destination_zip", fail)
    response = client.post("/v1/shipments/validate-destination", json={"destination_zip": "10034"})
    assert response.status_code == 503
    assert response.json()["detail"] == "ugamap_unavailable"
