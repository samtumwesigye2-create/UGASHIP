"""JANUS sign-in gate for UNG systems.

Every page and API call requires a signed-in UNG account (JANUS). People sign
in on /login with their JANUS email and password; the JANUS session token is
kept in a secure cookie. Other UNG services can still call the API with
"Authorization: Bearer <JANUS token>". Only /health and the sign-in pages are
open.

Use it by adding two lines right after the FastAPI app is created:

    import janus_gate
    janus_gate.install(app, "UNG-TAX")
"""
import html
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from fastapi import Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

JANUS_URL = os.environ.get("JANUS_URL", "https://ung-iam-production.up.railway.app").rstrip("/")
COOKIE = "ung_sso"
OPEN_PATHS = {"/health", "/ready", "/login", "/logout", "/favicon.ico"}
_cache: dict = {}


def _janus(path, body=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    data = json.dumps(body).encode() if body is not None else b""
    req = urllib.request.Request(JANUS_URL + path, data=data, method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read(65536))


def _principal(token):
    now = time.time()
    hit = _cache.get(token)
    if hit and hit[0] > now:
        return hit[1]
    try:
        res = _janus("/v1/auth/introspect", token=token)
    except Exception:
        return None
    p = res.get("principal") if isinstance(res, dict) and res.get("active") else None
    if len(_cache) > 2000:
        _cache.clear()
    if p:
        _cache[token] = (now + 60, p)
    else:
        _cache.pop(token, None)
    return p


def _safe_next(value):
    value = value or "/"
    return value if value.startswith("/") and not value.startswith("//") else "/"


def _page(system, error="", next_path="/", email=""):
    err = f'<p class="err" role="alert">{html.escape(error)}</p>' if error else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Sign in · {html.escape(system)}</title>
<style>
body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#f2f4f3;font:16px/1.5 -apple-system,"Segoe UI",Roboto,Arial,sans-serif;color:#1c2a26}}
main{{width:min(92vw,400px);background:#fff;border:1px solid #d7ddd9;border-radius:14px;padding:28px}}
small{{color:#5d6b66}}h1{{font-size:24px;margin:4px 0 16px}}
label{{display:block;font-weight:600;margin-top:12px}}
input{{width:100%;box-sizing:border-box;padding:12px;font-size:16px;border:1px solid #b9c3be;border-radius:8px;margin-top:4px}}
button{{width:100%;margin-top:18px;padding:12px;font-size:16px;border:0;border-radius:8px;background:#1f3b57;color:#fff}}
.err{{color:#b3261e;margin:12px 0 0}}
</style></head><body><main>
<small>{html.escape(system)}</small><h1>Sign in with your UNG account</h1>
<form method="post" action="/login"><input type="hidden" name="next" value="{html.escape(next_path)}">
<label for="e">Email</label><input id="e" name="email" type="email" autocomplete="username" required value="{html.escape(email)}">
<label for="p">Password</label><input id="p" name="password" type="password" autocomplete="current-password" required>
<button>Sign in</button>{err}</form>
<p><small>Same account and password as JANUS.</small></p></main></body></html>"""


def install(app, system_name="UNG system"):
    @app.middleware("http")
    async def janus_gate(request: Request, call_next):
        path = request.url.path
        if path in OPEN_PATHS or request.method == "OPTIONS":
            return await call_next(request)
        auth = request.headers.get("authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else request.cookies.get(COOKIE)
        principal = await run_in_threadpool(_principal, token) if token else None
        if not principal:
            if request.method == "GET" and "text/html" in request.headers.get("accept", ""):
                q = urllib.parse.quote(path + (("?" + request.url.query) if request.url.query else ""))
                return RedirectResponse("/login?next=" + q, status_code=303)
            return JSONResponse({"detail": "Sign in with your UNG (JANUS) account"}, status_code=401)
        request.state.principal = principal
        return await call_next(request)

    @app.get("/login", include_in_schema=False)
    def login_page(next: str = "/"):
        return HTMLResponse(_page(system_name, next_path=_safe_next(next)), headers={"Cache-Control": "no-store"})

    @app.post("/login", include_in_schema=False)
    async def login_submit(request: Request):
        form = urllib.parse.parse_qs((await request.body()).decode("utf-8", "replace"))
        email = (form.get("email") or [""])[0].strip().lower()
        password = (form.get("password") or [""])[0]
        next_path = _safe_next((form.get("next") or ["/"])[0])
        try:
            res = await run_in_threadpool(_janus, "/v1/auth/login", {"email": email, "password": password})
            token = res["access_token"]
            max_age = int(res.get("expires_in") or 28800)
        except urllib.error.HTTPError as e:
            msg = "Email or password is wrong." if e.code in (400, 401, 403, 422) else "JANUS sign-in is unavailable right now. Try again shortly."
            return HTMLResponse(_page(system_name, msg, next_path, email), status_code=401)
        except Exception:
            return HTMLResponse(_page(system_name, "JANUS sign-in is unavailable right now. Try again shortly.", next_path, email), status_code=503)
        resp = RedirectResponse(next_path, status_code=303)
        resp.set_cookie(COOKIE, token, max_age=max_age, httponly=True, secure=True, samesite="lax")
        return resp

    @app.get("/logout", include_in_schema=False)
    def logout():
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie(COOKIE)
        return resp
