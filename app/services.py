import asyncio
import json
import logging
import random
from typing import Any

import httpx
from pydantic import ValidationError

from app.config import Settings
from app.repository import Repository
from app.schemas import SummaryResult

logger = logging.getLogger(__name__)


class PipelineError(Exception):
    pass


class Transcriber:
    samples = [
        "今天的会议主要讨论了录音转写服务的接口设计、异步任务状态机和失败重试策略。团队决定先完成上传、查询和删除接口，再接入摘要能力。",
        "客户反馈希望摘要结果包含一句话总结、关键要点和待办事项。产品侧要求接口尽快返回任务编号，处理进度通过任务查询接口获取。",
        "后端方案采用本地文件存储和 SQLite 数据库。服务启动后会恢复未完成任务，并限制后台并发数，避免一次性处理过多录音。",
    ]

    def __init__(self, settings: Settings):
        self.settings = settings

    async def transcribe(self, recording_id: str) -> str:
        delay = random.uniform(5, 15)
        logger.info("recording=%s transcribe mock delay=%.2fs", recording_id, delay)
        await asyncio.sleep(delay)
        if random.random() < self.settings.transcribe_fail_rate:
            raise PipelineError("mock transcription failed")
        return random.choice(self.samples)


class Summarizer:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def summarize(self, transcript: str) -> dict[str, Any]:
        if self.settings.llm_provider.lower() == "mock" or not self.settings.llm_api_key:
            return self._mock_summary(transcript)
        return await self._llm_summary(transcript)

    def _mock_summary(self, transcript: str) -> dict[str, Any]:
        todos = []
        todo_keywords = ("请", "负责", "完成", "跟进", "确认", "补充", "下周", "明天", "截止", "待办")
        if any(keyword in transcript for keyword in todo_keywords):
            todos = ["根据录音中的要求跟进相关事项。"]
        return {
            "summary": "录音讨论了转写服务的后端实现与任务处理流程。",
            "key_points": [
                "上传接口需要立即返回 recording_id 和 task_id。",
                "后台任务按 pending、transcribing、summarizing、done 流转。",
                "需要处理失败、重试和服务重启恢复。",
            ],
            "todos": todos,
        }

    async def _llm_summary(self, transcript: str) -> dict[str, Any]:
        prompt = (
            "请根据下面录音转写文本生成 JSON，且只输出 JSON。\n"
            "字段要求：\n"
            "1. summary：用一句话概括录音核心内容。\n"
            "2. key_points：提炼录音中的关键要点。\n"
            "3. todos：只提取录音中明确出现的待办事项、后续动作、负责人安排或截止时间。\n"
            "4. 不要编造待办事项；如果录音中没有明确待办事项，todos 必须返回空数组 []。\n"
            '格式必须为 {"summary":"一句话摘要","key_points":["要点"],"todos":["待办"]}。\n\n'
            f"转写文本：{transcript}"
        )
        url = self.settings.llm_base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self.settings.llm_model,
            "messages": [
                {
                    "role": "system",
                    "content": "你是严谨的会议摘要助手，只返回可解析 JSON。不要编造 transcript 中没有出现的待办事项。",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {self.settings.llm_api_key}"}
        try:
            async with httpx.AsyncClient(timeout=self.settings.llm_timeout_seconds) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise PipelineError("LLM request timed out") from exc
        except httpx.HTTPError as exc:
            raise PipelineError(f"LLM request failed: {exc}") from exc

        try:
            content = response.json()["choices"][0]["message"]["content"]
            data = json.loads(content)
            return SummaryResult.model_validate(data).model_dump()
        except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValidationError) as exc:
            raise PipelineError("LLM response is not valid summary JSON") from exc


class TaskWorker:
    def __init__(self, repo: Repository, settings: Settings):
        self.repo = repo
        self.settings = settings
        self.transcriber = Transcriber(settings)
        self.summarizer = Summarizer(settings)
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.semaphore = asyncio.Semaphore(settings.worker_concurrency)
        self._runner: asyncio.Task | None = None
        self._scheduled: set[str] = set()
        self._closed = False

    async def start(self) -> None:
        self._closed = False
        self._runner = asyncio.create_task(self._run(), name="task-worker")
        for task_id in self.repo.recoverable_task_ids():
            await self.enqueue(task_id)
        logger.info("worker started concurrency=%s", self.settings.worker_concurrency)

    async def stop(self) -> None:
        self._closed = True
        if self._runner:
            self._runner.cancel()
            try:
                await self._runner
            except asyncio.CancelledError:
                pass

    async def enqueue(self, task_id: str) -> None:
        if task_id in self._scheduled:
            return
        self._scheduled.add(task_id)
        await self.queue.put(task_id)
        logger.info("task=%s queued", task_id)

    async def _run(self) -> None:
        while not self._closed:
            task_id = await self.queue.get()
            self._scheduled.discard(task_id)
            asyncio.create_task(self._guarded_process(task_id))

    async def _guarded_process(self, task_id: str) -> None:
        async with self.semaphore:
            try:
                await self._process(task_id)
            except Exception:
                logger.exception("task=%s crashed unexpectedly", task_id)
                self.repo.mark_status(task_id, "failed", "internal worker error", finished=True)

    async def _process(self, task_id: str) -> None:
        task = self.repo.get_task(task_id)
        if not task or task["status"] in {"done", "failed"}:
            return
        attempt = self.repo.increment_attempt(task_id)
        logger.info("task=%s recording=%s attempt=%s started", task_id, task["recording_id"], attempt)
        try:
            self.repo.mark_status(task_id, "transcribing")
            transcript = await self.transcriber.transcribe(task["recording_id"])
            self.repo.save_transcript(task["recording_id"], transcript)

            self.repo.mark_status(task_id, "summarizing")
            summary = await self.summarizer.summarize(transcript)
            self.repo.save_summary(task["recording_id"], summary)

            self.repo.mark_status(task_id, "done", finished=True)
            logger.info("task=%s recording=%s done", task_id, task["recording_id"])
        except PipelineError as exc:
            await self._handle_failure(task_id, task["recording_id"], attempt, task["max_attempts"], str(exc))

    async def _handle_failure(
        self,
        task_id: str,
        recording_id: str,
        attempt: int,
        max_attempts: int,
        error: str,
    ) -> None:
        if attempt < max_attempts:
            delay = 2 ** (attempt - 1)
            logger.warning(
                "task=%s recording=%s attempt=%s failed error=%s retry_in=%ss",
                task_id,
                recording_id,
                attempt,
                error,
                delay,
            )
            self.repo.mark_status(task_id, "pending", error)
            await asyncio.sleep(delay)
            await self.enqueue(task_id)
            return
        logger.error("task=%s recording=%s failed after %s attempts error=%s", task_id, recording_id, attempt, error)
        self.repo.mark_status(task_id, "failed", error, finished=True)
