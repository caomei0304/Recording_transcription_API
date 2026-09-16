from app.config import Settings
from app.database import Database
from app.repository import Repository


def make_repo(tmp_path):
    settings = Settings(database_path=tmp_path / "test.db", upload_dir=tmp_path / "uploads")
    db = Database(settings)
    db.init()
    return Repository(db)


def test_upload_is_idempotent_by_hash(tmp_path):
    repo = make_repo(tmp_path)

    first, created = repo.create_recording_with_task(
        original_filename="a.mp3",
        stored_filename="a.mp3",
        file_path=str(tmp_path / "a.mp3"),
        content_type="audio/mpeg",
        extension="mp3",
        size_bytes=3,
        content_hash="same-hash",
        idempotency_key=None,
    )
    second, duplicated = repo.create_recording_with_task(
        original_filename="b.mp3",
        stored_filename="b.mp3",
        file_path=str(tmp_path / "b.mp3"),
        content_type="audio/mpeg",
        extension="mp3",
        size_bytes=3,
        content_hash="same-hash",
        idempotency_key=None,
    )

    assert created is True
    assert duplicated is False
    assert second == first


def test_retry_failed_task_is_idempotent(tmp_path):
    repo = make_repo(tmp_path)
    upload, _ = repo.create_recording_with_task(
        original_filename="a.wav",
        stored_filename="a.wav",
        file_path=str(tmp_path / "a.wav"),
        content_type="audio/wav",
        extension="wav",
        size_bytes=3,
        content_hash="hash",
        idempotency_key=None,
    )
    repo.mark_status(upload["task_id"], "failed", "boom", finished=True)

    retry_task, accepted = repo.retry_task(upload["task_id"])
    retry_task_again, accepted_again = repo.retry_task(upload["task_id"])

    assert accepted is True
    assert accepted_again is True
    assert retry_task_again["task_id"] == retry_task["task_id"]
    assert retry_task["status"] == "pending"
