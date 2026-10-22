"""Authenticated API tests without contacting live JANUS."""
import pytest
import janus_gate

@pytest.fixture(autouse=True)
def mock_janus_identity(monkeypatch):
    monkeypatch.setattr(janus_gate, "_principal", lambda token: {"sub": "test-user"} if token == "test-token" else None)
