# UGASHIP

UGASHIP destination-resolution service. ZIP data is not duplicated here: UGASHIP resolves destinations through UGAMAP, backed by UNG-ZIPPER.

## Run

```bash
pip install -r requirements.txt
pytest -v
uvicorn app:app --host 0.0.0.0 --port 8080
```

Railway start command:

```text
uvicorn app:app --host 0.0.0.0 --port $PORT
```

## Configuration

`UGAMAP_BASE_URL` defaults to `https://uganda-grid-api-clean-production.up.railway.app` and can be overridden by environment variable.

## API

- `GET /health`
- `GET /v1/destinations/zip/{code}`
- `POST /v1/shipments/validate-destination` with JSON `{"destination_zip":"10034"}`

Version 0.1.0 validates destinations only. It does not persist shipments.
