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
