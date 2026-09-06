import hashlib
import hmac
import secrets
import tempfile
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import unquote

from anyio import to_thread
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, func, select
from starlette.background import BackgroundTask

from stacks.backup import backup
from stacks.collections import Collections
from stacks.config import Settings
from stacks.curation import Curation
from stacks.epub import InvalidBook
from stacks.inspection import FORMATS
from stacks.intake import Intake
from stacks.library import Library
from stacks.models import Asset, ImportOperation, LoginSession, Representation, Work, WorkRedirect
from stacks.operations import CatalogOperations
from stacks.reading import Reading
from stacks.schemas import (
    AssetAvailability,
    CandidatePage,
    CatalogPage,
    CollectionChange,
    CollectionEdit,
    CollectionNextPage,
    CollectionOut,
    CollectionPage,
    CollectionWorksPage,
    ContinuePage,
    FollowEdit,
    GroupCommit,
    GroupPreview,
    GroupRequest,
    ImportResult,
    JobChange,
    JobOut,
    JobPage,
    Login,
    NextPage,
    OperationOut,
    OperationPage,
    PersonalEdit,
    PlaybackOut,
    ProgressEdit,
    ProgressOut,
    RecordEdit,
    RecordOut,
    RecordPage,
    RunPage,
    RunWorksPage,
    ScanRequest,
    SeriesEdit,
    SeriesOut,
    SeriesPage,
    SourceOut,
    SourceRegistration,
    StatusOut,
    WorkEdit,
    WorkOut,
)
from stacks.series import SeriesCatalog
from stacks.sources import Sources

COOKIE = "stacks_session"
SESSION_SECONDS = 7 * 86400


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    password_hasher = PasswordHasher()
    password_hash = password_hasher.hash(settings.password.get_secret_value())
    attempts = deque(maxlen=10)
    attempts_lock = threading.Lock()

    @asynccontextmanager
    async def lifespan(app):
        app.state.library = await to_thread.run_sync(Library, settings.data_dir, settings.sources)
        app.state.intake = Intake(app.state.library)
        app.state.intake.start()
        try:
            yield
        finally:
            await to_thread.run_sync(app.state.intake.close)
            app.state.library.close()

    app = FastAPI(
        title="Stacks",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.middleware("http")
    async def protect_mutations(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            # Browser cross-origin requests cannot set this header without a CORS preflight.
            # No CORS origins are allowed. Also blocks cross-site HTML form submissions.
            if request.headers.get("x-stacks-request") != "1":
                return JSONResponse(
                    {"detail": "Missing request protection header."}, status_code=403
                )
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse(
                    {"detail": "Cross-site requests are not allowed."}, status_code=403
                )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def library(request: Request) -> Library:
        return request.app.state.library

    def authenticated(request: Request, lib: Annotated[Library, Depends(library)]):
        token = request.cookies.get(COOKIE, "")
        digest = hmac.new(
            settings.password.get_secret_value().encode(), token.encode(), hashlib.sha256
        ).hexdigest()
        with lib.sessions() as session:
            entry = session.get(LoginSession, digest)
            if entry is None or entry.expires_at < time.time():
                raise HTTPException(401, "Please sign in.")
        return lib

    Auth = Annotated[Library, Depends(authenticated)]

    @app.exception_handler(KeyError)
    async def missing(_request, _exc):
        return JSONResponse({"detail": "Book not found."}, status_code=404)

    @app.exception_handler(FileNotFoundError)
    async def unavailable(_request, _exc):
        return JSONResponse(
            {"detail": "The original file is unavailable. Check your storage."}, status_code=409
        )

    @app.get("/health/live")
    def live():
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready(lib: Annotated[Library, Depends(library)]):
        with lib.engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
        if not lib.managed.is_dir():
            raise HTTPException(503, "Managed storage unavailable.")
        return {"status": "ready"}

    @app.post("/api/login", status_code=204)
    def login(body: Login, response: Response, lib: Annotated[Library, Depends(library)]):
        with attempts_lock:
            if len(attempts) == 10 and attempts[0] > time.monotonic() - 60:
                raise HTTPException(429, "Too many sign-in attempts. Try again in a minute.")
            attempts.append(time.monotonic())
        try:
            password_hasher.verify(password_hash, body.password)
        except VerifyMismatchError:
            raise HTTPException(401, "Incorrect password.") from None
        with attempts_lock:
            attempts.clear()
        token = secrets.token_urlsafe(32)
        with lib.sessions.begin() as session:
            session.execute(delete(LoginSession).where(LoginSession.expires_at < int(time.time())))
            session.add(
                LoginSession(
                    digest=hmac.new(
                        settings.password.get_secret_value().encode(),
                        token.encode(),
                        hashlib.sha256,
                    ).hexdigest(),
                    expires_at=int(time.time()) + SESSION_SECONDS,
                )
            )
        response.set_cookie(
            COOKIE,
            token,
            httponly=True,
            samesite="strict",
            secure=settings.secure_cookie,
            max_age=SESSION_SECONDS,
        )

    @app.get("/api/session", status_code=204)
    def session(_lib: Auth):
        return Response(status_code=204)

    @app.post("/api/logout", status_code=204)
    def logout(request: Request, response: Response, lib: Auth):
        digest = hmac.new(
            settings.password.get_secret_value().encode(),
            request.cookies[COOKIE].encode(),
            hashlib.sha256,
        ).hexdigest()
        with lib.sessions.begin() as session:
            session.execute(delete(LoginSession).where(LoginSession.digest == digest))
        response.delete_cookie(COOKIE)

    @app.get("/api/catalog", response_model=CatalogPage)
    def catalog(
        lib: Auth,
        q: str = Query(default="", max_length=300),
        limit: int = Query(default=60, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        scope: Literal["all", "library", "archive"] = "all",
        medium: Literal["ebook", "comic", "audio"] | None = None,
        unassigned: bool = False,
    ):
        return lib.list(q, limit, offset, scope=scope, medium=medium, unassigned=unassigned)

    @app.get("/api/works/{work_id}", response_model=WorkOut)
    def work(work_id: str, lib: Auth):
        return lib.get(work_id)

    @app.patch("/api/works/{work_id}", response_model=WorkOut)
    def edit(work_id: str, body: WorkEdit, lib: Auth):
        try:
            return lib.edit(work_id, body)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.patch("/api/works/{work_id}/personal", response_model=WorkOut)
    def personal(work_id: str, body: PersonalEdit, lib: Auth):
        try:
            return Curation(lib).edit(work_id, body)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get("/api/works/{work_id}/records", response_model=RecordPage)
    def records(
        work_id: str, lib: Auth, limit: int = Query(24, ge=1, le=100), offset: int = Query(0, ge=0)
    ):
        try:
            return Curation(lib).records(work_id, limit, offset)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.post("/api/works/{work_id}/records", response_model=RecordOut)
    def add_record(work_id: str, body: RecordEdit, lib: Auth):
        try:
            return Curation(lib).save_record(work_id, body)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.patch("/api/works/{work_id}/records/{record_id}", response_model=RecordOut)
    def edit_record(work_id: str, record_id: str, body: RecordEdit, lib: Auth):
        try:
            return Curation(lib).save_record(work_id, body, record_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.delete("/api/works/{work_id}/records/{record_id}", status_code=204)
    def remove_record(work_id: str, record_id: str, lib: Auth, revision: int = Query(ge=1)):
        try:
            Curation(lib).delete_record(work_id, record_id, revision)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get("/api/sources", response_model=list[SourceOut])
    def sources(lib: Auth):
        return Sources(lib).list()

    @app.post("/api/sources/register", response_model=ImportResult)
    def register_source(body: SourceRegistration, lib: Auth):
        try:
            return lib.register_files(body.root, body.paths)
        except InvalidBook as error:
            raise HTTPException(422, str(error)) from error
        except OSError as error:
            raise HTTPException(
                409,
                "The source is unavailable, changed, or could not be registered. "
                "Check it before retrying.",
            ) from error

    @app.get("/api/works/{work_id}/availability", response_model=list[AssetAvailability])
    def original_availability(work_id: str, lib: Auth):
        return Sources(lib).availability(work_id)

    @app.get("/api/collections", response_model=CollectionPage)
    def collections(
        lib: Auth,
        q: str = Query(default="", max_length=1024),
        limit: int = Query(default=24, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ):
        return Collections(lib).list(q, limit, offset)

    @app.post("/api/collections", response_model=CollectionOut)
    def create_collection(body: CollectionEdit, lib: Auth):
        return Collections(lib).save(body)

    @app.patch("/api/collections/{collection_id}", response_model=CollectionOut)
    def edit_collection(collection_id: str, body: CollectionEdit, lib: Auth):
        try:
            return Collections(lib).save(body, collection_id)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    @app.post("/api/collections/{collection_id}/entries", response_model=CollectionOut)
    def change_collection(collection_id: str, body: CollectionChange, lib: Auth):
        try:
            return Collections(lib).change(collection_id, body)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    @app.get("/api/collections/{collection_id}/works", response_model=CollectionWorksPage)
    def collection_works(
        collection_id: str,
        lib: Auth,
        limit: int = Query(default=24, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ):
        return Collections(lib).works(collection_id, limit, offset)

    @app.get("/api/home/collections", response_model=CollectionNextPage)
    def collection_next(
        lib: Auth,
        limit: int = Query(default=12, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ):
        return Collections(lib).next(limit, offset)

    @app.get("/api/browse/series", response_model=RunPage)
    def browse_series(
        lib: Auth,
        q: str = Query("", max_length=300),
        scope: Literal["all", "library", "archive"] = "all",
        medium: Literal["ebook", "comic", "audio"] | None = None,
        following: bool = False,
        limit: int = Query(24, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ):
        return SeriesCatalog(lib).browse(q, scope, medium, following, limit, offset)

    @app.get("/api/home/next", response_model=NextPage)
    def next_followed(
        lib: Auth, limit: int = Query(12, ge=1, le=100), offset: int = Query(0, ge=0)
    ):
        return SeriesCatalog(lib).next(limit, offset)

    @app.get("/api/series/{series_id}", response_model=SeriesOut)
    def get_series(series_id: str, lib: Auth):
        return SeriesCatalog(lib).get(series_id)

    @app.patch("/api/series/{series_id}/following", response_model=SeriesOut)
    def follow_series(series_id: str, body: FollowEdit, lib: Auth):
        try:
            return SeriesCatalog(lib).follow(series_id, body)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get("/api/series", response_model=SeriesPage)
    def series(
        lib: Auth,
        q: str = Query(default="", max_length=300),
        limit: int = Query(default=60, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ):
        return lib.series(q, limit, offset)

    @app.post("/api/series", response_model=SeriesOut)
    def create_series(body: SeriesEdit, lib: Auth):
        return lib.save_series(body)

    @app.patch("/api/series/{series_id}", response_model=SeriesOut)
    def edit_series(series_id: str, body: SeriesEdit, lib: Auth):
        try:
            return lib.save_series(body, series_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get("/api/series/{series_id}/works", response_model=RunWorksPage)
    def series_works(
        series_id: str,
        lib: Auth,
        limit: int = Query(default=60, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        scope: Literal["all", "library", "archive"] = "all",
        medium: Literal["ebook", "comic", "audio"] | None = None,
    ):
        return SeriesCatalog(lib).works(series_id, limit, offset, scope, medium)

    @app.post("/api/operations/preview", response_model=GroupPreview)
    def preview_group(body: GroupRequest, lib: Auth):
        try:
            return CatalogOperations(lib).preview(body)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.post("/api/operations/{operation_id}/commit", response_model=OperationOut)
    def commit_group(operation_id: str, body: GroupCommit, lib: Auth):
        try:
            return CatalogOperations(lib).commit(operation_id, body.resolutions)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.post("/api/operations/{operation_id}/undo", response_model=OperationOut)
    def undo_group(operation_id: str, lib: Auth):
        try:
            return CatalogOperations(lib).undo(operation_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get("/api/operations", response_model=OperationPage)
    def operations(
        lib: Auth,
        work_id: str | None = Query(default=None, max_length=36),
        limit: int = Query(default=60, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ):
        return CatalogOperations(lib).list(limit, offset, work_id)

    @app.post("/api/intake/scans", response_model=JobOut)
    def start_scan(body: ScanRequest, request: Request, lib: Auth):
        try:
            return request.app.state.intake.scan(body)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        except OSError:
            raise HTTPException(409, "The source folder is inaccessible.") from None

    @app.get("/api/intake/jobs", response_model=JobPage)
    def intake_jobs(
        request: Request,
        lib: Auth,
        limit: int = Query(24, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ):
        return request.app.state.intake.jobs(limit, offset)

    @app.post("/api/intake/jobs/{job_id}", response_model=JobOut)
    def change_job(job_id: str, body: JobChange, request: Request, lib: Auth):
        try:
            return request.app.state.intake.change(job_id, body)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get("/api/intake/candidates", response_model=CandidatePage)
    def inbox_candidates(
        request: Request,
        lib: Auth,
        q: str = Query("", max_length=300),
        state: str = Query("", max_length=20),
        root: str = Query("", max_length=64),
        job_id: str = Query("", max_length=36),
        limit: int = Query(24, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ):
        return request.app.state.intake.candidates(q, state, root, job_id, limit, offset)

    @app.post(
        "/api/import",
        response_model=ImportResult,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
                },
            }
        },
    )
    async def import_book(request: Request, lib: Auth):
        name = (
            unquote(request.headers.get("x-filename", "book.epub"))
            .replace("\\", "/")
            .split("/")[-1]
        )
        if (
            Path(name).suffix.lower().lstrip(".") not in FORMATS
            or len(name) > 255
            or any(ord(c) < 32 for c in name)
        ):
            raise HTTPException(400, "Choose a supported publication with a valid filename.")
        content_length = request.headers.get("content-length")
        if content_length and (
            not content_length.isdigit() or int(content_length) > settings.max_upload_bytes
        ):
            raise HTTPException(413, "This file exceeds the upload limit.")
        with tempfile.NamedTemporaryFile(
            dir=lib.uploads, prefix="upload-", suffix=Path(name).suffix
        ) as temporary:
            size = 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise HTTPException(413, "This file exceeds the upload limit.")
                await to_thread.run_sync(temporary.write, chunk)
            temporary.flush()
            try:
                return await to_thread.run_sync(lib.import_file, Path(temporary.name), name)
            except InvalidBook as exc:
                raise HTTPException(422, str(exc)) from None
            except OSError:
                raise HTTPException(
                    503, "Import could not finish. Check storage and restart to recover."
                ) from None

    @app.get("/api/assets/{asset_id}/download")
    def download(asset_id: str, lib: Auth):
        with lib.sessions() as session:
            asset = session.get(Asset, asset_id)
            if asset is None:
                raise HTTPException(404, "File not found.")
            return FileResponse(
                lib.resolve_asset(asset),
                filename=asset.original_name,
                media_type=FORMATS.get(
                    Path(asset.original_name).suffix.lower().lstrip("."),
                    ("", "application/octet-stream"),
                )[1],
            )

    @app.get("/api/representations/{representation_id}/playback", response_model=PlaybackOut)
    def playback(representation_id: str, lib: Auth):
        try:
            return Reading(lib).playback(representation_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.patch("/api/representations/{representation_id}/progress", response_model=ProgressOut)
    def progress(representation_id: str, body: ProgressEdit, lib: Auth):
        try:
            return Reading(lib).update(representation_id, body)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.head("/api/assets/{asset_id}/stream", include_in_schema=False)
    @app.get("/api/assets/{asset_id}/stream")
    def stream(asset_id: str, lib: Auth):
        try:
            path, name = Reading(lib).stream(asset_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        return FileResponse(
            path,
            filename=name,
            content_disposition_type="inline",
            media_type=FORMATS[Path(name).suffix.lower().lstrip(".")][1],
        )

    @app.get("/api/home/continue", response_model=ContinuePage)
    def continue_list(
        lib: Auth,
        limit: int = Query(default=24, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ):
        return Reading(lib).continue_list(limit, offset)

    @app.get("/api/representations/{representation_id}/cover")
    def cover(representation_id: str, lib: Auth):
        with lib.sessions() as session:
            representation = session.get(Representation, representation_id)
            if representation is None or not representation.cover_path:
                raise HTTPException(404, "Cover not found.")
            return FileResponse(lib.resolve(representation.cover_path), media_type="image/jpeg")

    @app.get("/api/status", response_model=StatusOut)
    def status(lib: Auth):
        with lib.sessions() as session:
            return StatusOut(
                books=session.scalar(
                    select(func.count())
                    .select_from(Work)
                    .where(
                        ~select(WorkRedirect.source_id)
                        .where(WorkRedirect.source_id == Work.id)
                        .exists()
                    )
                ),
                import_errors=session.scalar(
                    select(func.count())
                    .select_from(ImportOperation)
                    .where(ImportOperation.state == "error")
                ),
            )

    @app.get("/api/export")
    def export(lib: Auth):
        return JSONResponse(
            lib.export(),
            headers={"Content-Disposition": 'attachment; filename="stacks-catalog.json"'},
        )

    @app.post("/api/backup")
    def create_backup(lib: Auth):
        directory = Path(tempfile.mkdtemp(prefix="stacks-backup-"))
        path = directory / "stacks.backup.zip"
        import shutil

        try:
            backup(lib, path)
        except ValueError as exc:
            shutil.rmtree(directory)
            raise HTTPException(409, str(exc)) from None
        except Exception:
            shutil.rmtree(directory)
            raise
        return FileResponse(
            path,
            filename="stacks.backup.zip",
            media_type="application/zip",
            background=BackgroundTask(shutil.rmtree, directory),
        )

    @app.get("/api/openapi.json")
    def schema(_lib: Auth):
        return app.openapi()

    if settings.frontend_dir.is_dir():
        static = settings.frontend_dir.resolve()
        app.mount("/_app", StaticFiles(directory=static / "_app"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def frontend(path: str):
            if path.startswith(("api/", "health/")):
                raise HTTPException(404)
            return FileResponse(static / "index.html")

    return app
