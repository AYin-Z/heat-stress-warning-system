from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from .schemas import EstimateRequest, HeartRateWindowRequest, WatchUpload
from .service import ThermalService, alert_for
from .settings import settings
from .state import StateRepository


repository = StateRepository(settings.redis_url, settings.state_ttl_seconds)
thermal_service = ThermalService(settings, repository)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await repository.connect()
    yield
    await repository.close()


app = FastAPI(title="Heat Stress Model Gateway", version="1.1.0", lifespan=lifespan)


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/readyz")
async def readyz():
    return {"ok": True, "models": thermal_service.status()}


@app.post("/v1/core-temperature/estimate")
def estimate(request: HeartRateWindowRequest):
    try:
        result = thermal_service.estimate_hr_window(request.heart_rates, request.timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "ok": True,
        "device_id": request.device_id,
        **result,
    }


@app.post("/v1/core-temperature/estimate-samples", deprecated=True)
async def estimate_samples(request: EstimateRequest):
    result = None
    for sample in request.samples:
        upload = WatchUpload(
            timestamp=sample.timestamp, heart_rate=sample.heart_rate,
            core_temperature=sample.core_temperature, skin_temperature=sample.skin_temperature,
            skin_temperatures=sample.skin_temperatures,
        )
        result = await thermal_service.process(request.device_id, upload)
    if result is None:
        raise HTTPException(status_code=400, detail="samples must not be empty")
    return {"ok": True, "thermal": result.model_dump(mode="json")}


@app.post("/api/watch/upload/")
async def watch_upload(payload: WatchUpload, x_device_id: str | None = Header(default=None)):
    if not x_device_id:
        return JSONResponse(status_code=401, content={"error": "缺少 X-Device-ID 请求头", "code": "MISSING_DEVICE_ID"})

    thermal = await thermal_service.process(x_device_id, payload)
    upstream_data = None
    upstream_status = 200
    if settings.forward_upload and settings.upstream_watch_api:
        url = f"{settings.upstream_watch_api}/api/watch/upload/"
        try:
            upstream_payload = payload.model_dump(mode="json", exclude_none=True)
            # watch-api.md defaults a missing core_temperature to 37.0. Always
            # forward the measured/estimated value so that its alert rules use
            # the same canonical temperature as this gateway.
            upstream_payload.setdefault("core_temperature", thermal.current_core_temperature)
            async with httpx.AsyncClient(timeout=settings.upstream_timeout_seconds) as client:
                response = await client.post(
                    url, headers={"X-Device-ID": x_device_id},
                    json=upstream_payload,
                )
            upstream_status = response.status_code
            upstream_data = response.json()
            if upstream_status >= 400:
                return JSONResponse(status_code=upstream_status, content=upstream_data)
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(status_code=502, detail=f"upstream watch-api unavailable: {type(exc).__name__}") from exc

    result = upstream_data if isinstance(upstream_data, dict) else {"ok": True, "server_time": datetime.now(timezone.utc).isoformat()}
    # Keep watch-api.md's canonical field name.  Consumers do not need to know
    # whether the value came from Kalman warm-up or the HR-only Informer.
    result["core_temperature"] = thermal.current_core_temperature
    result["thermal"] = thermal.model_dump(mode="json")
    if not result.get("alert"):
        result["alert"] = alert_for(thermal)
    if result.get("alert") is None:
        result.pop("alert", None)
    return JSONResponse(status_code=upstream_status, content=result)


@app.api_route("/api/watch/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy_watch(path: str, request: Request):
    if not settings.upstream_watch_api:
        raise HTTPException(status_code=404, detail="upstream watch-api is not configured")
    url = f"{settings.upstream_watch_api}/api/watch/{path}"
    headers = {key: value for key, value in request.headers.items() if key.lower() not in {"host", "content-length"}}
    async with httpx.AsyncClient(timeout=settings.upstream_timeout_seconds) as client:
        response = await client.request(request.method, url, params=request.query_params, headers=headers, content=await request.body())
    excluded = {"content-encoding", "transfer-encoding", "connection", "content-length", "content-type"}
    response_headers = {key: value for key, value in response.headers.items() if key.lower() not in excluded}
    return Response(content=response.content, status_code=response.status_code, headers=response_headers, media_type=response.headers.get("content-type"))
