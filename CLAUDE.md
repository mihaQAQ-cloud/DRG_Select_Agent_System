# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

医保 DRG 入组智能体系统 — 多智能体架构平台，以电子病历（EMR）为输入，结合国家医保局 DRG 2.0 分组规则，自动完成 DRG 入组、文档生成、测试用例生成及文档管理。华东理工大学软件工程课程大作业。

## 启动与运行

```bash
# 安装依赖
pip install -r requirements.txt

# 进入venv虚拟环境
venv\Scripts\activate

# 启动全部服务（DRG 智能体 :8000、文档系统 :8001、触发生成任务、打开前端）
python main.py
```

按 Enter 键退出全部服务。启动后浏览器自动打开 `index.html`。

## 技术栈

- **后端**: Python 3.10+ / FastAPI + Uvicorn
- **数据验证**: Pydantic V2
- **存储**: SQLite（`data/results.db`，含 `emr_records`、`drg_results`、`documents` 三张表）
- **LLM**: 兼容 OpenAI API（DeepSeek）和 Ollama 本地部署，通过 `requests.Session` 直接调用，未使用 openai SDK
- **文档生成**: `python-docx`（Word）→ 临时文件 → POST 到文档系统；`openpyxl`（Excel）
- **前端**: 单页 `index.html`，纯 HTML/CSS/JS，通过 CORS 直连后端 API

## 架构

### 多智能体协作模式

`main.py` 是主控编排器：依次以 daemon 线程启动两个 FastAPI 服务，然后调用 `agents/doc_agent.py` 和 `agents/test_agent.py` 中的生成函数触发生成任务。

```
main.py (编排器)
  ├── doc_system.py          → 虚拟文档系统 (端口 8001, FastAPI)
  ├── agents/drg_agent.py    → DRG 入组智能体 (端口 8000, FastAPI)
  ├── agents/doc_agent.py    → 文档生成智能体 (函数式，非服务)
  ├── agents/test_agent.py   → 测试用例生成智能体 (函数式，非服务)
  └── agents/llm_service.py  → 共享 LLM 调用层 (被所有智能体引用)
```

- **DRG 智能体** (`agents/drg_agent.py`)：单文件，内部按五层组织 — 数据模型（Pydantic）→ 数据层（SQLite）→ 规则引擎层（`DRGRuleEngine`）→ LLM 层 → API 层（FastAPI routes）。入组流水线：`match_mdc(ICD前缀) → match_adrg(MDC+手术) → eval_cc_mcc(次诊断) → MDC+ADRG+严重度后缀 = DRG`。
- **文档生成智能体** (`agents/doc_agent.py`)：按章节定义列表逐章调 LLM 生成内容，拼成 `.docx` 后通过临时文件 POST 到文档系统。文档系统负责以 `{doc_id}_{filename}` 格式持久化到 `data/outputs/`。
- **测试用例生成智能体** (`agents/test_agent.py`)：三类用例 — normal（遍历规则程序化生成）、boundary（CC/MCC/排除表边界）、abnormal（LLM 生成或内置模板降级）。内置 `_eval_cc_mcc` 和 `_derive_expected_drg` 与 `DRGRuleEngine` 逻辑完全对齐。
- **LLM 服务** (`agents/llm_service.py`)：`LLMService` 类，`chat()` 方法自动区分 Ollama（`/api/generate`）和 OpenAI 兼容接口（`/v1/chat/completions`）。API key 未配置或调用失败时返回 `[规则引擎模式]` 前缀的降级文本，不抛异常。

### 关键设计模式

- **降级策略**：LLM 不可用时系统自动降级为纯规则引擎，保证核心功能始终可用。
- **规则热更新**：`GET /api/drg/reload` 重新加载 `rules/drg_rules.json`，无需重启服务。
- **孤儿记录清理**：`doc_system.py` 的 list/search 接口在返回前检查物理文件是否存在，自动删除数据库中的孤儿元数据。
- **时间处理**：数据库写入使用 Python `datetime.now()` 计算的本地时间，而非 SQLite 的 `CURRENT_TIMESTAMP`（返回 UTC，在东八区会偏差 8 小时）。
- **双文件消除**：`doc_agent.py` 和 `test_agent.py` 均使用 `tempfile.NamedTemporaryFile` 写临时文件 → POST 到文档系统 → 删除临时文件，避免在 `data/outputs/` 中产生重复文件。
- **ICD 编码匹配**：MCC/CC 列表使用前向前缀索引（按 3 字符大类分桶），支持中国扩展码后缀 `xNNN` 的规范化匹配。

### 数据流

1. 前端（`index.html`）通过 CORS 调用 `localhost:8000` 的 DRG API 和 `localhost:8001` 的文档 API
2. DRG 入组：EMR JSON → Pydantic 校验 → `DRGRuleEngine.classify()` 规则推理 → `llm.chat()` 生成入组说明 → 结果写 SQLite + 返回 JSON
3. 文档流转：智能体生成 `.docx`/`.xlsx` → `requests.post("http://localhost:8001/api/docs/submit")` → 文档系统存储并管理

## 配置

`config.yaml` 结构：
- `llm.base_url` / `llm.api_key` / `llm.model` / `llm.timeout`
- `rules.path`: DRG 规则文件路径（默认 `rules/drg_rules.json`）
- `server.drg_port` / `server.doc_port`: 服务端口

## 重要注意事项

- **`config.yaml` 中包含真实 API Key，切勿提交到版本控制或泄露。** 项目当前无 `.gitignore`，需自行添加。
- `rules/drg_rules.json` 是教学简化版规则，不可用于临床结算。规则文件很大（完整覆盖 26 个 MDC、409 个 ADRG），修改时需要保持 JSON 结构完整。
- 系统启动使用 daemon 线程 + `time.sleep(1.5)` 等待，非生产级做法；端口 8000/8001 被占用会导致启动失败。
- 数据库 schema 变更（如 `drg_agent.py` 中新增 `secondary_ops` 列）需要手动 `ALTER TABLE` 或删除 `data/results.db` 重建。
- 所有智能体文件均有 `from agents.llm_service import LLMService` 并在模块级实例化 `llm = LLMService()`，这意味着 LLM 配置在 import 时读取一次，修改 `config.yaml` 后需重启进程才能生效。
