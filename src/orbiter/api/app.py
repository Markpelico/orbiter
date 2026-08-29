"""ORBITER API: job submission and status.

Submission is idempotent (Idempotency-Key header, Stripe semantics) and
admission-controlled (429 + Retry-After past capacity, see admission.py).
The submit transaction writes the job, its first two events, and the outbox
row atomically — the dual-write problem is solved here or nowhere.
"""

# NOTE: no `from __future__ import annotations` here. Stringified annotations
# break FastAPI's dependency resolution for closures defined inside
# create_app: `Depends(get_pool)` lives in the factory's local scope, which
# get_type_hints cannot see, and the params silently degrade to query params.

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

import asyncpg
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from orbiter.api.admission import AdmissionController
from orbiter.config import Settings
from orbiter.db import repo


class SubmitRequest(BaseModel):
    duration_ms: int = Field(ge=0, le=600_000)
    failure_rate: float = Field(default=0.0, ge=0.0, le=1.0)


class SubmitResponse(BaseModel):
    id: str
    state: str
    created: bool


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        pool = await repo.create_pool(cfg.database_url)
        await repo.apply_schema(pool)
        app.state.pool = pool
        app.state.admission = AdmissionController(
            capacity=cfg.admission_capacity, retry_after_s=cfg.admission_retry_after_s
        )
        try:
            yield
        finally:
            await pool.close()

    app = FastAPI(title="ORBITER", version="0.1.0", lifespan=lifespan)

    def get_pool(request: Request) -> asyncpg.Pool:
        pool: asyncpg.Pool = request.app.state.pool
        return pool

    def get_admission(request: Request) -> AdmissionController:
        admission: AdmissionController = request.app.state.admission
        return admission

    @app.post("/jobs", response_model=SubmitResponse)
    async def submit(
        body: SubmitRequest,
        response: Response,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        admission: Annotated[AdmissionController, Depends(get_admission)],
    ) -> SubmitResponse:
        if not admission.try_acquire():
            raise HTTPException(
                status_code=429,
                detail="submission capacity exceeded; retry later",
                headers={"Retry-After": str(admission.retry_after_s)},
            )
        try:
            job_id, created = await repo.submit_job(
                pool,
                idempotency_key=idempotency_key,
                payload=body.model_dump(),
                subject=cfg.subject_jobs,
            )
        finally:
            admission.release()
        response.status_code = 201 if created else 200
        return SubmitResponse(id=str(job_id), state="queued", created=created)

    @app.get("/jobs/{job_id}")
    async def status(
        job_id: str, pool: Annotated[asyncpg.Pool, Depends(get_pool)]
    ) -> dict[str, Any]:
        try:
            parsed = uuid.UUID(job_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="job_id must be a UUID") from exc
        job = await repo.get_job(pool, parsed)
        if job is None:
            raise HTTPException(status_code=404, detail="no such job")
        return job

    @app.get("/healthz")
    async def healthz(pool: Annotated[asyncpg.Pool, Depends(get_pool)]) -> dict[str, str]:
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return {"status": "ok"}

    return app
