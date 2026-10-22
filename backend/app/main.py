import logging

from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db import engine
from app.routers import beam_model  # noqa: E402
from app.routers import (
    access_reviews,
    catalogue,
    catalogue_mapping,
    extensions as extensions_router,
    intake as intake_router,
    field as field_router,
    ai,
    asset_subresources,
    assets,
    attachments,
    attribute_values,
    documents,
    equipment,
    export,
    global_values,
    glpi,
    graph,
    groups,
    hub,
    ledger,
    icons,
    import_configs,
    imports,
    issues,
    spreadsheet_import,
    labels,
    legacy_migration,
    retirement,
    mcp,
    roles,
    schemas,
    sync,
    transfers,
    uploads,
    workflows,
    workspaces,
)

logging.basicConfig(level=logging.INFO)

from app.auth import bind_grants  # noqa: E402
import app.ledger.audit  # noqa: E402,F401  (append-only guards on create_all)
from app import idempotency, problems  # noqa: E402
from app import log_redaction  # noqa: E402,F401  (redacts capability tokens from access logs)
from app.services import api_policy, legacy_hosts  # noqa: E402

# Every request carries the viewer's restricted-class grants (I-ACL-1).
app = FastAPI(
    title="ARGUS Knowledge Hub API", version="1.0.0", dependencies=[Depends(bind_grants)],
    contact={"name": "Andrea Michelotti", "email": "andrea.michelotti@infn.it"},
    license_info={"name": "EUPL-1.2", "identifier": "EUPL-1.2"},
)
problems.install(app)

# Auth is a Bearer token per request (no cookies), so a wildcard origin here
# carries none of the usual CSRF-adjacent risk of credentialed CORS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    # Content-Disposition: the file name of an export, read by the web from another origin.
    expose_headers=["X-ARGUS-API-Version", "Deprecation", "Sunset", "Link", "ETag", "Content-Disposition"],
)

@app.middleware("http")
async def api_policy_and_legacy_hosts(request: Request, call_next):
    """The retired Jira host redirects to the lookup page (§19 item 11);
    every response names the API version, and a deprecated endpoint says
    so, until its sunset (§19 item 8)."""
    host = request.headers.get("host")
    if legacy_hosts.is_legacy(host):
        return RedirectResponse(legacy_hosts.target(host, request.url.path, request.url.query,
                                                    request.headers.get("x-forwarded-proto", "https")),
                                status_code=301)
    too_old = api_policy.client_too_old(request.headers.get("x-argus-client"))
    if too_old is not None:
        return problems.response(426, too_old, {"X-ARGUS-API-Version": api_policy.API_VERSION})
    device = request.headers.get("x-argus-device")
    if device:
        from app.db import SessionLocal
        from app.routers.field import device_refusal
        db = SessionLocal()
        try:
            refusal = device_refusal(db, device)
        finally:
            db.close()
        if refusal is not None:
            return problems.response(401, refusal, {"X-ARGUS-API-Version": api_policy.API_VERSION})
    deprecated = api_policy.find(request.method, request.url.path)
    if deprecated is not None and api_policy.is_past_sunset(deprecated):
        response = problems.response(410, {
            "error": f"{request.method} {deprecated.path} was retired on {deprecated.sunset}",
            "successor": deprecated.successor})
    else:
        response = await idempotency.run(request, call_next)
    if deprecated is not None:
        response.headers.update(api_policy.headers(deprecated))
    response.headers["X-ARGUS-API-Version"] = api_policy.API_VERSION
    return response


@app.middleware("http")
async def usage_counts(request: Request, call_next):
    """Counts the request, anonymously, for the Statistics page (services/usage.py)."""
    from app.services import usage
    if not usage.counted(request.method, request.url.path):
        return await call_next(request)
    holder = usage.begin(request.headers, request.url.path)
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        route = request.scope.get("route")
        usage.end(holder, f"{request.method} {getattr(route, 'path', None) or '(no route)'}", status)


@app.exception_handler(DBAPIError)
async def database_refusal(request: Request, exc: DBAPIError):
    """The database's own refusals: an append-only audit table, or a
    ledger-only workspace written around the ledger (§19 item 2, §13 S5)."""
    code = getattr(exc.orig, "pgcode", None)
    if code == "42501":
        message = str(exc.orig).splitlines()[0]
        return problems.response(409, {
            "error": message, "invariant": "ledger-only" if "ledger-only" in message else "append-only"})
    raise exc


@app.get("/v1/meta/version", tags=["meta"])
def version_meta():
    """Which release is running: its version, commit and build time (set when the image is built), and the API
    contract version. Public, like /health, so a deployment can be checked without signing in."""
    import os
    return {"version": os.environ.get("ARGUS_VERSION") or "dev", "commit": os.environ.get("ARGUS_COMMIT") or None,
            "built_at": os.environ.get("ARGUS_BUILT_AT") or None, "api_version": api_policy.API_VERSION}


@app.get("/v1/meta/api", tags=["meta"])
def api_meta():
    """The API version, its deprecation policy and what is deprecated now."""
    return api_policy.describe()


@app.get("/legacy/jira/{path:path}", include_in_schema=False)
def legacy_jira(path: str, request: Request):
    """For a proxy that forwards the retired Jira host here rather than by
    host name: the same redirect as the host itself."""
    hosts = sorted(legacy_hosts.legacy_hosts())
    forwarded = request.headers.get("x-forwarded-host")
    host = forwarded if legacy_hosts.is_legacy(forwarded) else (hosts[0] if hosts else "jira")
    return RedirectResponse(legacy_hosts.target(host, "/" + path, request.url.query,
                                                request.headers.get("x-forwarded-proto", "https")),
                            status_code=301)


app.include_router(schemas.router)
app.include_router(assets.router)
app.include_router(assets.relations_router)
app.include_router(issues.router)
app.include_router(glpi.router)
app.include_router(spreadsheet_import.router)
# Before the documents' own routes: /v1/documents/reshape is not a document's uid.
from app.routers import document_templates as document_templates_router  # noqa: E402
app.include_router(document_templates_router.documents_router)
app.include_router(documents.router)
app.include_router(document_templates_router.router)
app.include_router(document_templates_router.ai_router)
app.include_router(asset_subresources.router)
app.include_router(attachments.router)
app.include_router(global_values.router)
app.include_router(graph.router)
app.include_router(hub.router)
app.include_router(ledger.router)
app.include_router(ledger.installations_router)
app.include_router(ledger.access_points_router)
app.include_router(ledger.domains_router)
app.include_router(ledger.lookup_router)
app.include_router(export.router)
app.include_router(equipment.router)
app.include_router(equipment.bulk_router)
app.include_router(workflows.router)
app.include_router(workflows.notifications_router)
app.include_router(access_reviews.router)
app.include_router(retirement.router)
app.include_router(catalogue.router)
app.include_router(extensions_router.router)
app.include_router(intake_router.router)
app.include_router(field_router.devices_router)
app.include_router(field_router.links_router)
app.include_router(legacy_migration.router)
app.include_router(attribute_values.router)
app.include_router(ai.router)
app.include_router(ai.admin_router)
from app.routers import tokens as tokens_router  # noqa: E402
app.include_router(tokens_router.router)
from app.routers import logbook as logbook_router  # noqa: E402
app.include_router(logbook_router.router)
from app.routers import jql as jql_router  # noqa: E402
app.include_router(jql_router.router)
from app.routers import packages as packages_router  # noqa: E402
app.include_router(packages_router.router)
from app.routers import spatial as spatial_router  # noqa: E402
app.include_router(spatial_router.router)


from app.packages.requirements import MissingPrerequisite  # noqa: E402


@app.exception_handler(MissingPrerequisite)
async def _missing_package(_request, exc: MissingPrerequisite):
    """An import a workspace is not ready for: said as what to install, wherever the import runs."""
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=422, content={"detail": {
        "error": str(exc), "code": exc.code, "capability": exc.capability, "install": exc.offered_by}})
app.include_router(mcp.router)
app.include_router(groups.router)
app.include_router(icons.router)
app.include_router(import_configs.router)
app.include_router(imports.router)
app.include_router(labels.router)
app.include_router(roles.router)
app.include_router(sync.router)
app.include_router(transfers.router)
app.include_router(catalogue_mapping.router)
app.include_router(catalogue.types_router)
for _r in beam_model.ROUTERS:
    app.include_router(_r)
from app.routers import portability as portability_router  # noqa: E402
from app.routers import help as help_router  # noqa: E402
from app.routers import statistics as statistics_router  # noqa: E402

app.include_router(help_router.router)
app.include_router(statistics_router.router)
from app.routers import activities as activities_router  # noqa: E402

app.include_router(activities_router.router)
for _r in portability_router.ROUTERS:
    app.include_router(_r)


@app.on_event("startup")
def _default_workspace() -> None:
    """A new installation starts with one workspace, so nobody signs in to an empty hub."""
    from app.db import SessionLocal
    from app.routers.workspaces import ensure_default_workspace
    db = SessionLocal()
    try:
        made = ensure_default_workspace(db)
        if made:
            logging.getLogger(__name__).info("created the default workspace %s", made)
        # Workspaces made before packages were recorded: what each evidently has, recorded once.
        from app.packages.install import detect
        found = detect(db)
        db.commit()
        if found:
            logging.getLogger(__name__).info("recorded %s template packages already in place", found)
    except Exception:  # noqa: BLE001 — a database not yet migrated must not stop the API
        db.rollback()
        logging.getLogger(__name__).warning("default workspace skipped", exc_info=True)
    finally:
        db.close()


@app.on_event("startup")
def _recover_portability_jobs() -> None:
    """Portability jobs left running by a previous process were interrupted: say so."""
    from app.db import SessionLocal
    from app.portability import jobs as portability_jobs
    try:
        portability_jobs.recover(SessionLocal)
    except Exception:  # noqa: BLE001 — a database not yet migrated must not stop the API
        logging.getLogger(__name__).warning("portability job recovery skipped", exc_info=True)
@app.on_event("startup")
def _knowledge_schedule() -> None:
    """Keeps Ask ARGUS's index of the written knowledge up to date on each workspace's timer."""
    from app.services import knowledge_schedule
    knowledge_schedule.start_scheduler()


app.include_router(uploads.router)
app.include_router(workspaces.router)


@app.get("/health")
def health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}
