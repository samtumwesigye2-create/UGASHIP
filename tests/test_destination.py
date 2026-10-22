import io
import json
import urllib.error

import pytest

import destination
from destination import DestinationError, normalize_zip, resolve_destination_zip


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def destination_payload():
    return {
        "code": "10034",
        "district": "Kampala",
        "name": "Kampala",
        "area_type": "urban",
        "population_covered": 3768,
        "latitude": 0.49729955933456793,
        "longitude": 32.667045285449205,
    }


def ugamap_payload():
    return {
        "ok": True,
        "source": "UNG-ZIPPER",
        "destination": destination_payload(),
    }


def test_normalize_zip_pads_numeric_code():
    assert normalize_zip("34") == "00034"


def test_normalize_zip_preserves_five_digits():
    assert normalize_zip("10034") == "10034"


def test_normalize_zip_rejects_non_numeric():
    with pytest.raises(DestinationError) as exc:
        normalize_zip("ABC")
    assert (exc.value.status_code, exc.value.detail) == (422, "destination_zip_must_be_numeric")


def test_normalize_zip_rejects_more_than_five_digits():
    with pytest.raises(DestinationError) as exc:
        normalize_zip("123456")
    assert (exc.value.status_code, exc.value.detail) == (422, "destination_zip_must_be_1_to_5_digits")


def test_resolve_destination_maps_nested_ugamap_response(monkeypatch):
    monkeypatch.setattr(destination.urllib.request, "urlopen", lambda *a, **k: FakeResponse(ugamap_payload()))
    assert resolve_destination_zip("10034") == {
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


def test_resolve_destination_translates_404(monkeypatch):
    error = urllib.error.HTTPError("url", 404, "not found", {}, io.BytesIO(b"{}"))
    monkeypatch.setattr(destination.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(error))
    with pytest.raises(DestinationError) as exc:
        resolve_destination_zip("99999")
    assert (exc.value.status_code, exc.value.detail) == (404, "destination_zip_not_found")


def test_resolve_destination_translates_upstream_5xx(monkeypatch):
    error = urllib.error.HTTPError("url", 503, "down", {}, io.BytesIO(b"{}"))
    monkeypatch.setattr(destination.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(error))
    with pytest.raises(DestinationError) as exc:
        resolve_destination_zip("10034")
    assert (exc.value.status_code, exc.value.detail) == (502, "ugamap_upstream_error")


def test_resolve_destination_translates_network_failure(monkeypatch):
    monkeypatch.setattr(destination.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(TimeoutError()))
    with pytest.raises(DestinationError) as exc:
        resolve_destination_zip("10034")
    assert (exc.value.status_code, exc.value.detail) == (503, "ugamap_unavailable")


def test_resolve_destination_rejects_malformed_nested_payload(monkeypatch):
    payload = ugamap_payload()
    payload["destination"]["latitude"] = None
    monkeypatch.setattr(destination.urllib.request, "urlopen", lambda *a, **k: FakeResponse(payload))
    with pytest.raises(DestinationError) as exc:
        resolve_destination_zip("10034")
    assert (exc.value.status_code, exc.value.detail) == (502, "ugamap_destination_invalid")
