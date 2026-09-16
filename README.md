# 录音转写服务 API

一个录音转写与智能摘要后端服务。支持音频上传、异步转写、摘要生成、任务查询、失败重试和录音删除。

服务默认使用 SQLite 和本地文件存储，启动成本低，适合本地验收与接口测试。

## 功能

- 上传录音文件，支持 `wav / mp3 / m4a / aac`
- 校验文件是否存在、大小是否不超过 50MB、扩展名是否合法
- 上传后立即返回 `recording_id`、`task_id` 和初始状态
- 后台异步处理任务，接口不会同步等待处理完成
- 支持任务状态流转：`pending -> transcribing -> summarizing -> done`
- 任一处理阶段失败后自动重试，最多 3 次
- 自动重试耗尽后任务进入 `failed`
- 支持失败任务手动重试，并保证重复 retry 不会重复创建多个任务
- 支持录音列表分页查询，按创建时间倒序返回
- 支持录音详情查询，任务完成后返回 `transcript` 和结构化摘要
- 支持删除录音记录、本地文件和关联任务数据
- 支持上传幂等：同一文件哈希或相同 `Idempotency-Key` 不会重复创建任务
- 支持服务重启恢复：启动时重新入队未完成任务
- 支持并发控制：默认最多 3 个任务同时处理
- 提供统一错误响应和关键路径日志
- 提供 `.http` API 调试文件
- 提供 Windows、macOS、Linux 一键启动脚本

## 项目结构

```text
录音转写服务/
├── app/
│   ├── __init__.py
│   ├── config.py          # 环境变量与运行配置
│   ├── database.py        # SQLite 连接、事务、时间与 JSON 辅助函数
│   ├── errors.py          # 统一错误响应
│   ├── main.py            # FastAPI 入口与 HTTP 接口
│   ├── repository.py      # recordings / tasks 数据访问层
│   ├── schemas.py         # Pydantic 响应模型
│   └── services.py        # 转写、摘要、后台任务队列与状态机
├── migrations/
│   └── 001_init.sql       # SQLite 建表脚本
├── tests/
│   ├── test_repository.py # 幂等上传、失败任务 retry 测试
│   └── test_services.py   # 摘要结构与 todos 规则测试
├── .env.example           # 环境变量示例
├── .gitignore
├── README.md
├── requests.http          # API 调试文件
├── requirements.txt       # Python 依赖
├── run.ps1                # Windows 一键启动脚本
└── run.sh                 # macOS / Linux 一键启动脚本
```

运行后会自动生成：

```text
data/
├── app.db                 # SQLite 数据库文件
└── uploads/               # 上传的录音文件
```

`data/`、`.venv/`、`.env`、缓存文件不会提交到 Git。

## 环境要求

- Python 3.10+
- Windows / macOS / Linux 均可
- 不需要额外安装 PostgreSQL、MySQL、Redis 或对象存储

## 安装依赖

进入项目目录：

```powershell
cd E:\Pycharm_Files\录音转写服务
```

如果使用一键启动脚本，可以跳过手动安装依赖，脚本会自动创建 `.venv` 并安装依赖。

手动安装方式：

```bash
python -m venv .venv
python -m pip install -r requirements.txt
```

Windows 下如果要使用虚拟环境里的 Python：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 配置环境变量

复制 `.env.example` 为 `.env`：

```powershell
copy .env.example .env
```

macOS / Linux：

```bash
cp .env.example .env
```

`.env.example` 示例：

```env
APP_HOST=0.0.0.0
APP_PORT=8000
DATABASE_PATH=./data/app.db
UPLOAD_DIR=./data/uploads
MAX_UPLOAD_MB=50
WORKER_CONCURRENCY=3
TRANSCRIBE_FAIL_RATE=0.2
LLM_PROVIDER=mock
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=
LLM_MODEL=gpt-4o-mini
LLM_TIMEOUT_SECONDS=20
```

说明：

- `DATABASE_PATH`：SQLite 数据库文件路径
- `UPLOAD_DIR`：录音文件本地保存目录
- `MAX_UPLOAD_MB`：上传文件最大大小，默认 50MB
- `WORKER_CONCURRENCY`：后台任务最大并发数，默认 3
- `TRANSCRIBE_FAIL_RATE`：转写阶段失败概率，默认 0.2
- `LLM_PROVIDER`：摘要提供方，默认 `mock`
- `LLM_BASE_URL`：OpenAI-compatible API 地址
- `LLM_API_KEY`：LLM API Key
- `LLM_MODEL`：LLM 模型名
- `LLM_TIMEOUT_SECONDS`：LLM 调用超时时间

如果要调用 OpenAI-compatible API，可修改：

```env
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=your_api_key
LLM_MODEL=gpt-4o-mini
```

## 启动项目

### Windows 一键启动

PowerShell 终端：

```powershell
.\run.ps1
```

如果当前终端是 `cmd`，使用：

```cmd
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

### macOS / Linux 一键启动

```bash
bash run.sh
```

### 手动启动

```bash
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

启动成功后会看到类似：

```text
Uvicorn running on http://0.0.0.0:8000
Application startup complete.
```

本机访问地址：

```text
http://localhost:8000
```

FastAPI 接口文档：

```text
http://localhost:8000/docs
```

健康检查：

```text
http://localhost:8000/health
```

## API 调试

项目提供 [requests.http](./requests.http)，可在 VS Code REST Client 或 JetBrains HTTP Client 中直接运行。

核心接口：

- `POST /v1/recordings`：上传录音，表单字段名为 `file`
- `GET /v1/tasks/{task_id}`：查询任务状态
- `GET /v1/recordings?page=&page_size=`：分页查询录音列表
- `GET /v1/recordings/{id}`：查询录音详情
- `POST /v1/tasks/{task_id}/retry`：重试失败任务
- `DELETE /v1/recordings/{id}`：删除录音和本地文件

## 架构流程

```mermaid
flowchart TD
    Client[Client]

    Client -->|multipart upload<br/>POST /v1/recordings| API[FastAPI API]

    API -->|validate file| Validator[File Validator]
    Validator -->|invalid| Error[Return 422<br/>Validation Error]
    Validator -->|valid| SaveFile[Save File<br/>Local uploads]

    SaveFile --> CreateTask[Create Recording + Task]
    CreateTask -->|insert recording + task| DB[(SQLite)]
    CreateTask -->|enqueue task_id| Queue[asyncio Queue]

    Queue -->|consume task_id| Worker[Background Worker]

    Worker -->|status = transcribing| ASR[Transcription<br/>ASR or Mock]
    ASR -->|save transcript + status| DB

    ASR -->|status = summarizing| LLM[LLM Summary<br/>LLM or Mock]
    LLM -->|save summary + status| DB

    LLM -->|status = done| Done[Task Completed]

    Client -->|poll task/result<br/>GET /v1/tasks/task_id| API
    API -->|read task/status/result| DB
    DB -->|return task/result| API
    API -->|response| Client
```

## 任务流程与并发控制

任务状态机：

```text
pending -> transcribing -> summarizing -> done
                          \-> failed
```

处理流程：

```text
上传录音
-> 校验文件
-> 保存到本地磁盘
-> 创建 recording 记录
-> 创建 pending task
-> 立即返回 recording_id 和 task_id
-> 后台 worker 消费任务
-> 转写
-> 摘要
-> 写入 transcript / summary
-> 标记 done
```

失败处理：

- 任一阶段失败后自动重试
- 最多尝试 3 次
- 指数退避：1 秒、2 秒
- 重试耗尽后任务进入 `failed`
- 只有 `failed` 状态允许手动 retry
- 重复 retry 同一个失败任务会返回同一个重试任务

并发控制：

- 后台任务使用 `asyncio.Queue`
- 通过 `WORKER_CONCURRENCY` 控制同时处理的任务数
- 默认最多 3 个任务并发处理

技术取舍：

- 选择 SQLite 是为了降低本地运行和验收成本，不需要额外安装数据库；当前数据量和并发规模较小，SQLite 足够满足笔试场景。生产环境可迁移到 PostgreSQL / MySQL，以获得更好的并发写入能力和连接池支持。
- 题目不要求对象存储，因此使用本地磁盘保存上传文件，便于一键启动和本地调试。生产环境可迁移到 S3、MinIO、阿里云 OSS 或腾讯云 COS，以支持多实例共享文件和更可靠的文件管理。
- 题目允许转写阶段使用 Mock，因此当前实现重点放在异步任务状态机、失败重试、结果查询和摘要流程上。后续可将 Transcriber 替换为 Whisper、faster-whisper 或云厂商 ASR 服务。
- 摘要阶段使用 OpenAI-compatible 调用方式，便于切换不同低成本 LLM 服务，例如 DeepSeek、智谱、Groq 或本地 Ollama。代码只依赖统一的 `chat/completions` 格式，降低模型供应商切换成本。
- 选择 `asyncio.Queue` 的原因是降低部署复杂度，满足笔试场景一键启动。生产环境可迁移到 Redis + Celery，以支持多 worker 消费、任务持久化和更成熟的重试/超时控制。

服务重启恢复：

- 服务启动时扫描 `pending / transcribing / summarizing` 状态的未删除任务
- 扫描到的任务会重新入队
- 避免任务因为服务重启永久卡在处理中

## 摘要结果

录音详情接口在任务完成后返回：

```json
{
  "transcript": "录音转写文本",
  "summary": {
    "summary": "一句话摘要",
    "key_points": ["关键要点 1", "关键要点 2"],
    "todos": ["待办事项 1"]
  }
}
```

字段说明：

- `transcript`：录音转写文本
- `summary.summary`：根据 `transcript` 生成的一句话摘要
- `summary.key_points`：根据 `transcript` 提炼的关键要点，要求通顺、简洁、完整
- `summary.todos`：根据 `transcript` 提取的待办事项

`todos` 规则：

- 有明确待办事项、后续动作、负责人安排或截止时间时，返回具体待办数组
- 没有明确待办事项时，返回空数组 `[]`
- 提示词要求模型不要编造待办事项
- 真实 LLM 模式下会进行二次校验：第一次生成摘要结果，第二次根据 transcript 删除没有原文依据的 `key_points` 和 `todos`，并在不新增信息的前提下润色保留的 `key_points`

## 数据库说明

项目使用 SQLite。建表 SQL 位于 [migrations/001_init.sql](./migrations/001_init.sql)。

主要数据表：

- `recordings`：录音记录表
- `tasks`：处理任务表

`recordings` 主要字段：

- `id`：录音 ID，格式如 `rec_xxx`
- `original_filename`：原始文件名
- `stored_filename`：本地保存文件名
- `file_path`：本地文件路径
- `content_type`：上传文件 MIME 类型
- `extension`：文件扩展名
- `size_bytes`：文件大小
- `content_hash`：文件 SHA-256 哈希，用于同文件去重
- `transcript`：转写文本
- `summary_json`：摘要 JSON
- `idempotency_key`：客户端幂等键
- `created_at` / `updated_at` / `deleted_at`：时间字段

`tasks` 主要字段：

- `id`：任务 ID，格式如 `task_xxx`
- `recording_id`：关联录音 ID
- `status`：任务状态
- `attempt_count`：当前尝试次数
- `max_attempts`：最大尝试次数
- `error`：失败原因
- `retried_by_task_id`：该失败任务对应的重试任务 ID
- `created_at` / `updated_at` / `started_at` / `finished_at`：时间字段

时间字段说明：

- 所有接口返回的时间字段使用北京时间，ISO 8601 格式，时区偏移为 `+08:00`

表关系：

```text
recordings 1 ---- n tasks
```

列表接口会展示每条录音的最新任务状态。

## 错误响应

统一错误格式：

```json
{
  "error": {
    "code": "recording_not_found",
    "message": "recording not found"
  }
}
```

常见状态码：

- `400`：请求参数或文件不合法
- `404`：录音或任务不存在
- `409`：对非失败任务执行 retry
- `422`：FastAPI 参数校验失败

## 基本使用流程

1. 启动服务。
2. 打开 `http://localhost:8000/docs`。
3. 调用 `POST /v1/recordings` 上传录音文件。
4. 复制返回的 `task_id`。
5. 调用 `GET /v1/tasks/{task_id}` 查询任务状态。
6. 等待状态变为 `done`。
7. 复制返回的 `recording_id`。
8. 调用 `GET /v1/recordings/{recording_id}` 查看 `transcript` 和 `summary`。
9. 如需删除，调用 `DELETE /v1/recordings/{recording_id}`。

示例返回：

```json
{
  "recording_id": "rec_71f43d8a8dd7458d98a9e0cae5d9c461",
  "task_id": "task_9c7e228a118d41fd9e5050a6975042f3",
  "status": "pending"
}
```

## 测试

运行测试：

```bash
pytest
```

当前测试覆盖：

- 上传按文件哈希幂等
- 失败任务 retry 幂等
- 摘要结果结构
- 没有待办事项时 `todos` 返回 `[]`
- 有明确待办事项时 `todos` 返回待办数组

## 注意事项

- 上传接口只校验文件存在、大小和扩展名。
- 任务处理是异步的，上传成功后需要通过 `task_id` 查询状态。
- `retry` 接口只适用于 `failed` 状态任务。
- 删除录音会同时删除本地文件和关联数据。
- `0.0.0.0` 是服务监听地址，本机浏览器访问请使用 `localhost` 或 `127.0.0.1`。
- 提交到 GitHub / Gitee 前建议分多次 commit，保留开发过程历史。
