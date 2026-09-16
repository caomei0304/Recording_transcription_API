import asyncio

from app.config import Settings
from app.services import Summarizer


def test_mock_summarizer_returns_required_shape():
    summarizer = Summarizer(Settings(llm_provider="mock"))

    result = asyncio.run(summarizer.summarize("讨论上传、转写、摘要和重试。"))

    assert isinstance(result["summary"], str)
    assert isinstance(result["key_points"], list)
    assert isinstance(result["todos"], list)


def test_mock_summarizer_returns_empty_todos_without_action_items():
    summarizer = Summarizer(Settings(llm_provider="mock"))

    result = asyncio.run(summarizer.summarize("本次录音介绍了产品背景、接口设计和数据结构。"))

    assert result["todos"] == []


def test_mock_summarizer_returns_todos_when_action_items_exist():
    summarizer = Summarizer(Settings(llm_provider="mock"))

    result = asyncio.run(summarizer.summarize("请后端同学补充接口文档，并在明天完成上传接口测试。"))

    assert result["todos"]
