import hashlib
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, Query, Response, UploadFile, status

from app.config import Settings, get_settings
from app.database import Database
from app.errors import ApiError, register_error_handlers
from app.repository import Repository
from app.schemas import RecordingDetail, RecordingListOut, TaskOut, UploadOut
from app.services import TaskWorker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".aac"}

settings = get_settings()
db = Database(settings)
repo = Repository(db)
worker = TaskWorker(repo, settings)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    db.init()
    await worker.start()
    try:
        yield
    finally:
        await worker.stop()


tags_metadata = [
    {"name": "系统检查", "description": "用于确认服务是否正常运行。"},
    {"name": "录音管理", "description": "上传、查询和删除录音文件。"},
    {"name": "任务处理", "description": "查询异步处理任务状态，并对失败任务发起重试。"},
]

app = FastAPI(
    title="录音转写与智能摘要服务",
    description="上传录音文件后，服务会异步完成 Mock 转写和智能摘要生成。",
    version="1.0.0",
    lifespan=lifespan,
    openapi_tags=tags_metadata,
    docs_url="/docs",
    redoc_url="/redoc",
)
register_error_handlers(app)


def get_repo() -> Repository:
    return repo


def get_worker() -> TaskWorker:
    return worker


def validate_extension(filename: str) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ApiError(400, "invalid_file_type", "file extension must be one of wav/mp3/m4a/aac")
    return ext


async def save_upload(file: UploadFile, ext: str, settings: Settings) -> tuple[Path, int, str]:
    temp_name = f"upload_{os.urandom(16).hex()}{ext}"
    temp_path = settings.upload_dir / temp_name
    hasher = hashlib.sha256()
    size = 0
    try:
        with temp_path.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise ApiError(400, "file_too_large", f"file size must be <= {settings.max_upload_mb}MB")
                hasher.update(chunk)
                out.write(chunk)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    if size == 0:
        temp_path.unlink(missing_ok=True)
        raise ApiError(400, "empty_file", "file must not be empty")
    return temp_path, size, hasher.hexdigest()


@app.get("/health", tags=["系统检查"], summary="健康检查", description="返回服务是否正常运行。")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/v1/recordings",
    response_model=UploadOut,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["录音管理"],
    summary="上传录音",
    description="上传 wav、mp3、m4a 或 aac 文件。接口会立即返回 recording_id 和 task_id，后台异步处理。",
)
async def upload_recording(
    response: Response,
    file: UploadFile | None = File(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    repository: Repository = Depends(get_repo),
    task_worker: TaskWorker = Depends(get_worker),
) -> UploadOut:
    if file is None or not file.filename:
        raise ApiError(400, "missing_file", "multipart field 'file' is required")
    ext = validate_extension(file.filename)
    temp_path, size, content_hash = await save_upload(file, ext, settings)
    created = False
    try:
        result, created = repository.create_recording_with_task(
            original_filename=file.filename,
            stored_filename=temp_path.name,
            file_path=str(temp_path),
            content_type=file.content_type,
            extension=ext.lstrip("."),
            size_bytes=size,
            content_hash=content_hash,
            idempotency_key=idempotency_key,
        )
    finally:
        if not created:
            temp_path.unlink(missing_ok=True)

    if not created:
        response.status_code = status.HTTP_200_OK
    else:
        await task_worker.enqueue(result["task_id"])
        logger.info("recording=%s task=%s created", result["recording_id"], result["task_id"])
    return UploadOut(**result)


@app.get(
    "/v1/tasks/{task_id}",
    response_model=TaskOut,
    tags=["任务处理"],
    summary="查询任务状态",
    description="根据 task_id 查询异步处理任务的当前状态。",
)
async def get_task(task_id: str, repository: Repository = Depends(get_repo)) -> TaskOut:
    task = repository.get_task(task_id)
    if task is None:
        raise ApiError(404, "task_not_found", "task not found")
    return TaskOut(**task)


@app.get(
    "/v1/recordings",
    response_model=RecordingListOut,
    tags=["录音管理"],
    summary="查询录音列表",
    description="分页查询录音记录，按创建时间倒序返回，并包含每条录音的最新任务状态。",
)
async def list_recordings(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    repository: Repository = Depends(get_repo),
) -> RecordingListOut:
    total, items = repository.list_recordings(page, page_size)
    return RecordingListOut(page=page, page_size=page_size, total=total, items=items)


@app.get(
    "/v1/recordings/{recording_id}",
    response_model=RecordingDetail,
    tags=["录音管理"],
    summary="查询录音详情",
    description="根据 recording_id 查询录音详情。任务完成后会返回 transcript 和 summary。",
)
async def get_recording(recording_id: str, repository: Repository = Depends(get_repo)) -> RecordingDetail:
    recording = repository.get_recording_detail(recording_id)
    if recording is None:
        raise ApiError(404, "recording_not_found", "recording not found")
    return RecordingDetail(**recording)


@app.post(
    "/v1/tasks/{task_id}/retry",
    response_model=TaskOut,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["任务处理"],
    summary="重试失败任务",
    description="仅 failed 状态的任务可以重试。重复请求同一个失败任务会返回同一个重试任务。",
)
async def retry_task(
    task_id: str,
    repository: Repository = Depends(get_repo),
    task_worker: TaskWorker = Depends(get_worker),
) -> TaskOut:
    result = repository.retry_task(task_id)
    if result is None:
        raise ApiError(404, "task_not_found", "task not found")
    task, accepted = result
    if not accepted:
        raise ApiError(409, "task_not_failed", "only failed tasks can be retried")
    await task_worker.enqueue(task["task_id"])
    return TaskOut(**task)


@app.delete(
    "/v1/recordings/{recording_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["录音管理"],
    summary="删除录音",
    description="删除录音记录、本地文件和关联任务数据。",
)
async def delete_recording(recording_id: str, repository: Repository = Depends(get_repo)) -> Response:
    row = repository.delete_recording(recording_id)
    if row is None:
        raise ApiError(404, "recording_not_found", "recording not found")
    Path(row["file_path"]).unlink(missing_ok=True)
    logger.info("recording=%s deleted", recording_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
