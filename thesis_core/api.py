"""Read-only HTTP projections of the scientific store.

Importing this module neither connects to PostgreSQL nor loads the legacy site.
Mutation belongs to the local CLI and workers.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path as FilesystemPath
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import FastAPI, HTTPException, Path, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

if TYPE_CHECKING:
    from thesis_core.store import Store

COLLECTIONS = {
    "experiments": "experiment",
    "tasks": "evaluation_task",
    "runs": "forecast_run",
    "proofs": "publication_proof",
    "observations": "observation",
    "resolutions": "resolution",
}
Digest = Annotated[str, Path(pattern=r"^[0-9a-f]{64}$")]
Cursor = Annotated[str | None, Query(pattern=r"^[0-9a-f]{64}$")]
Limit = Annotated[int, Query(ge=1, le=100)]


def configured_store() -> Store:
    from thesis_core.artifacts import LocalArtifactStore
    from thesis_core.store import Store

    dsn = os.environ.get("THESIS_CORE_DSN")
    if not dsn:
        raise HTTPException(503, detail={"code": "core_unconfigured"})
    artifacts = LocalArtifactStore(
        FilesystemPath(
            os.environ.get("THESIS_CORE_ARTIFACTS", ".thesis-core/artifacts")
        )
    )
    return Store(
        dsn, artifacts, schema=os.environ.get("THESIS_CORE_SCHEMA", "thesis_core")
    )


def _timestamp(value: datetime | None) -> str | None:
    return (
        value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        if value
        else None
    )


def record_view(store: Store, record: Any) -> dict[str, Any]:
    """Keep recorded hashes intact; add clearly separate operational metadata."""
    item = {
        "id": record.id,
        "kind": record.kind,
        "payload": record.canonical_payload(),
        "committed_at": _timestamp(store.committed_at(record.id)),
    }
    task = None
    if record.kind == "evaluation_task":
        task = record
    elif record.kind == "forecast_run":
        task = store.get(store.get(record.attempt_id).task_id)
    if task is not None:
        item.update(
            mode=task.mode,
            information_cutoff=_timestamp(task.information_cutoff),
            effective_information_boundary=_timestamp(
                store.committed_at(task.evidence_bundle_id)
            ),
        )
    elif record.kind == "experiment":
        tasks = [store.get(task_id) for task_id in record.task_ids]
        freezes = [store.committed_at(task.evidence_bundle_id) for task in tasks]
        item.update(
            mode=record.mode,
            information_cutoff=_timestamp(tasks[0].information_cutoff)
            if tasks
            else None,
            effective_information_boundary=(
                _timestamp(max(freezes)) if freezes and all(freezes) else None
            ),
        )
    return item


def create_app(store: Store | None = None) -> FastAPI:
    import psycopg

    from .artifacts import ArtifactCorrupt, ArtifactError, ArtifactMissing
    from .service import ExperimentNotFoundError
    from .store import IdentityConflict, RecordMissing, StoreError

    application = FastAPI(title="Thesis core", version="1", docs_url="/docs")

    def current_store() -> Store:
        return store if store is not None else configured_store()

    @application.exception_handler(StarletteHTTPException)
    async def request_failure(_request, error):
        detail = error.detail
        code = detail.get("code") if isinstance(detail, dict) else None
        return JSONResponse(
            {
                "error": {
                    "code": code
                    or {
                        404: "not_found",
                        405: "method_not_allowed",
                    }.get(error.status_code, "invalid_request")
                }
            },
            status_code=error.status_code,
            headers=error.headers,
        )

    @application.exception_handler(RequestValidationError)
    async def invalid_request(_request, _error):
        return JSONResponse({"error": {"code": "invalid_request"}}, status_code=422)

    @application.exception_handler(ExperimentNotFoundError)
    async def missing_experiment(_request, _error):
        return JSONResponse(
            {"error": {"code": "experiment_not_found"}}, status_code=404
        )

    @application.exception_handler(KeyError)
    @application.exception_handler(RecordMissing)
    async def missing_record(_request, _error):
        return JSONResponse({"error": {"code": "record_not_found"}}, status_code=404)

    @application.exception_handler(ArtifactMissing)
    async def missing_artifact(_request, _error):
        return JSONResponse({"error": {"code": "artifact_not_found"}}, status_code=404)

    @application.exception_handler(ArtifactCorrupt)
    @application.exception_handler(IdentityConflict)
    @application.exception_handler(ValueError)
    async def integrity_failure(_request, _error):
        return JSONResponse(
            {"error": {"code": "scientific_integrity_failure"}}, status_code=409
        )

    @application.exception_handler(ArtifactError)
    @application.exception_handler(StoreError)
    @application.exception_handler(psycopg.Error)
    @application.exception_handler(OSError)
    async def unavailable(_request, _error):
        return JSONResponse({"error": {"code": "store_unavailable"}}, status_code=503)

    @application.get("/health")
    def health():
        try:
            state = current_store().health()
            return {"status": "ok", "schema_version": 1, **state}
        except HTTPException:
            raise
        except Exception:
            # A DSN or upstream database error must never reach the browser.
            return JSONResponse(
                {"error": {"code": "store_unavailable"}}, status_code=503
            )

    def collection_endpoint(kind: str):
        def collection(limit: Limit = 20, after: Cursor = None):
            active = current_store()
            page = active.list(kind, limit=limit, after=after)
            return {
                "items": [record_view(active, item) for item in page.items],
                "next_cursor": page.next_cursor,
            }

        return collection

    for route, kind in COLLECTIONS.items():
        application.add_api_route(
            f"/{route}",
            collection_endpoint(kind),
            methods=["GET"],
            name=route,
        )

    @application.get("/records/{record_id}")
    def record(record_id: Digest):
        active = current_store()
        return record_view(active, active.get(record_id))

    @application.get("/artifacts/{artifact_id}")
    def artifact(artifact_id: Digest):
        from thesis_core.artifacts import ArtifactCorrupt, ArtifactMissing

        try:
            payload = current_store().artifacts.read_bytes(artifact_id)
        except ArtifactMissing:
            raise HTTPException(404, detail={"code": "artifact_not_found"}) from None
        except ArtifactCorrupt:
            raise HTTPException(
                409, detail={"code": "artifact_integrity_failure"}
            ) from None
        return Response(
            payload,
            media_type="application/octet-stream",
            headers={"ETag": f'"{artifact_id}"', "Cache-Control": "public, immutable"},
        )

    @application.get("/pending")
    def pending():
        from thesis_core.service import pending_targets

        return {"items": pending_targets(current_store())}

    @application.get("/rewards")
    def rewards(
        experiment_id: Annotated[str | None, Query(pattern=r"^[0-9a-f]{64}$")] = None,
        as_of: str | None = None,
    ):
        from thesis_core.service import reward_rows

        cutoff = None
        if as_of is not None:
            try:
                cutoff = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
                if cutoff.tzinfo is None:
                    raise ValueError("Timezone required")
            except ValueError:
                raise HTTPException(422, detail={"code": "invalid_as_of"}) from None
        return {"items": reward_rows(current_store(), experiment_id, as_of=cutoff)}

    @application.get("/leaderboard")
    def leaderboard(
        experiment_id: Annotated[str | None, Query(pattern=r"^[0-9a-f]{64}$")] = None,
    ):
        from thesis_core.service import leaderboard_rows

        return {"items": leaderboard_rows(current_store(), experiment_id)}

    from .lab import mount_routes

    mount_routes(application, current_store)
    return application


app = create_app()
