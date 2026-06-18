# 🏥 医保 DRG 入组智能体系统 (Medical Insurance DRG Agent System)

> **华东理工大学 · 软件工程课程大作业**  
> **开发语言**: Python 3.10+

## 📖 项目简介

本项目是一个面向医疗机构的智能化 **DRG (Diagnosis Related Groups)** 分组辅助平台。系统以电子病历 (EMR) 为核心输入，结合国家医疗保障局发布的 DRG 分组规则（2.0 版），借助大语言模型 (LLM) 的自然语言理解与推理能力，自动完成 **DRG 入组**、**文档生成**、**测试用例生成** 及 **文档全生命周期管理**。

系统采用 **多智能体 (Multi-Agent)** 架构，由主控编排器 `main.py` 统一调度四个核心智能体子系统，实现从数据输入到结果输出、文档归档的全流程自动化。

## ✨ 核心功能

### 1. 🧠 DRG 入组智能体 (Port: 8000)

- **自动入组**：基于 ICD-10 诊断编码和手术操作编码，自动执行 MDC → ADRG → DRG 三层入组流水线。
- **并发症评估**：智能识别 CC (并发症) 和 MCC (严重并发症)，排除互斥诊断，支持中国扩展码（xNNN 后缀）的前向前缀匹配。
- **双引擎模式**：
  - **规则引擎**：基于 `rules/drg_rules.json` 进行确定性逻辑分组。
  - **LLM 增强**：调用大模型生成详细的入组依据和推理说明。
- **热更新支持**：通过 `GET /api/drg/reload` 动态加载最新分组规则，无需重启服务。
- **批量处理**：支持单条和批量病历入组。
- **降级保障**：LLM 不可用时自动降级为纯规则引擎模式，核心功能始终可用。

### 2. 📝 文档自动生成智能体

- **SRS 生成**：自动生成软件需求规格说明书（`.docx`）。
- **架构设计**：生成系统总体架构、模块划分、接口设计及数据库设计文档（`.docx`）。
- **测试文档**：生成测试策略、用例模板及覆盖度要求文档（`.docx`）。
- **格式规范**：输出标准 `.docx` 格式，包含封面、版本记录及章节排版。

### 3. 🧪 测试用例生成智能体

- **三类用例**：
  - 正常场景 — 遍历规则库程序化生成标准入组用例。
  - 边界场景 — 覆盖 CC/MCC 有无、排除表边界、手术编码命中等。
  - 异常场景 — LLM 生成或内置模板（非法编码、缺失字段、极端值）。
- **覆盖度统计**：自动计算测试用例对全部 ADRG 分组的覆盖率，标识未覆盖项。
- **Excel 导出**：生成带样式的标准测试用例 Excel 文件（含覆盖度汇总 sheet）。

### 4. 🗄️ 虚拟文档系统 (Port: 8001)

- **集中存储**：统一管理所有智能体生成的文档和测试用例。
- **RESTful API**：提供文档提交、列表查询、关键词搜索、下载及删除接口。
- **元数据管理**：记录文档类型、版本、创建时间及状态。
- **孤儿记录自动清理**：检测文件缺失并同步清理数据库元数据。

## 🛠️ 技术栈

| 类别 | 技术 |
|------|------|
| 后端框架 | FastAPI + Uvicorn |
| 数据验证 | Pydantic V2 |
| 数据库 | SQLite（`data/results.db`） |
| LLM 集成 | DeepSeek API（OpenAI 兼容）/ Ollama 本地部署 |
| 文档处理 | `python-docx`（Word）、`openpyxl`（Excel） |
| 前端 | 单页 HTML/CSS/JS（`index.html`），通过 CORS 直连后端 |
| 配置 | `config.yaml`（YAML） |

## 📂 项目结构

```text
project-v3/
├── main.py                 # 🚀 主控入口：一键启动所有服务并触发初始化任务
├── config.yaml             # ⚙️ 配置文件：LLM地址、模型名称、规则路径、端口
├── requirements.txt        # 📦 Python 依赖包列表
├── index.html              # 🌐 前端交互界面（单页应用，含侧边栏导航）
├── doc_system.py           # 🗄️ 虚拟文档系统服务（Port 8001, FastAPI）
├── agents/
│   ├── __init__.py
│   ├── llm_service.py      # 🤖 LLM 调用封装层（自动区分 Ollama/OpenAI 接口，支持降级）
│   ├── drg_agent.py        # 🏥 DRG 入组智能体（Port 8000, FastAPI）
│   ├── doc_agent.py        # 📝 文档生成智能体（函数式调用）
│   └── test_agent.py       # 🧪 测试用例生成智能体（函数式调用）
├── rules/
│   └── drg_rules.json      # 📜 DRG 分组规则库（MDC/ADRG映射, CC/MCC列表, 排除表等）
└── data/                   # 💾 数据存储目录（自动创建）
    ├── results.db          # SQLite 数据库（emr_records / drg_results / documents）
    └── outputs/            # 生成的文档和测试用例存放处
```

## 🚀 快速开始

### 1. 环境准备

确保已安装 Python 3.10 或更高版本。

```bash
# 进入项目目录
cd project-v3

# 创建虚拟环境（推荐）
python -m venv venv
source venv/bin/activate   # Linux/Mac
# venv\Scripts\activate    # Windows

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置 LLM 服务

编辑 `config.yaml` 文件，配置 LLM 服务地址。

**使用 DeepSeek API（OpenAI 兼容）**
```yaml
llm:
  base_url: "https://api.deepseek.com"
  api_key: "sk-xxxxxxxxxxxxxxxx"   # 填入您的 API Key
  model: "deepseek-chat"
  timeout: 20
```

**使用本地 Ollama**
```yaml
llm:
  base_url: "http://localhost:11434"
  api_key: ""                       # Ollama 无需 API Key
  model: "qwen2.5:7b"
  timeout: 60
```

### 3. 启动系统

```bash
python main.py
```

**启动流程：**
1. 启动虚拟文档系统（Port 8001）
2. 启动 DRG 入组智能体（Port 8000）
3. 触发文档智能体生成 SRS、架构设计及测试文档
4. 触发测试智能体生成测试用例（正常/边界/异常三类）
5. **自动打开浏览器加载 `index.html` 界面**

按 `Enter` 键退出全部服务。

## 💻 界面使用指南

启动后浏览器自动打开综合平台界面，左侧边栏包含四个模块：

1. **DRG 入组智能体**：输入患者信息、主诊断 ICD 编码、次诊断、手术编码等，点击"执行 DRG 入组"查看分组结果及 LLM 生成的入组理由。支持查看历史入组记录。
2. **文档生成智能体**：点击按钮即可生成各类型 Word 文档，并在虚拟文档系统中查看下载。
3. **测试用例智能体**：查看自动生成的测试用例 Excel 文件及其 ADRG 覆盖度统计。
4. **虚拟文档系统**：管理所有上传和生成的文档，支持按类型过滤、关键词搜索和下载。

## 🔌 API 文档

服务启动后，可通过 Swagger UI 查看完整接口文档：

- **DRG 智能体**: http://localhost:8000/docs
- **文档系统**: http://localhost:8001/docs

### 核心接口示例

**DRG 入组（单条）：**
```bash
curl -X POST http://localhost:8000/api/drg/classify \
     -H "Content-Type: application/json" \
     -d '{
       "patient_id": "P001",
       "main_diagnosis": {"icd_code": "J44.1", "name": "COPD急性加重"},
       "secondary_diagnoses": [],
       "main_op_code": null,
       "secondary_ops": [],
       "age": 65,
       "gender": "M"
     }'
```

**批量 DRG 入组：**
```bash
curl -X POST http://localhost:8000/api/drg/batch \
     -H "Content-Type: application/json" \
     -d '[
       {"patient_id":"P001","main_diagnosis":{"icd_code":"J44.1"},"secondary_diagnoses":[],"age":65,"gender":"M"},
       {"patient_id":"P002","main_diagnosis":{"icd_code":"I21.9"},"secondary_diagnoses":[{"icd_code":"I50.0"}],"age":72,"gender":"F"}
     ]'
```

**热更新规则：**
```bash
curl http://localhost:8000/api/drg/reload
```

**查询历史记录：**
```bash
curl "http://localhost:8000/api/drg/results?limit=20&offset=0"
```

**查询文档列表：**
```bash
curl "http://localhost:8001/api/docs/list?doc_type=SRS"
```

**下载文档：**
```bash
curl -O http://localhost:8001/api/docs/{doc_id}/download
```

## ⚠️ 注意事项

1. **规则文件**：`rules/drg_rules.json` 是基于国家医保局 DRG 2.0 版整理的简化规则集（覆盖 26 个 MDC、409 个 ADRG），仅供教学和演示使用，不可直接用于临床结算。
2. **LLM 降级**：LLM 不可用时系统自动降级为纯规则引擎模式，入组结果仍可正常返回，只是推理说明会标注 `[规则引擎模式]` 前缀。
3. **端口占用**：请确保本地 **8000** 和 **8001** 端口未被其他程序占用。
4. **配置文件**：`config.yaml` 中包含 API Key 等敏感信息，请勿提交到版本控制系统。建议添加 `.gitignore` 忽略该文件。
5. **数据库迁移**：若修改了数据模型（如新增字段），需手动执行 `ALTER TABLE` 或删除 `data/results.db` 让系统重建。

## 📄 许可证

本项目仅用于华东理工大学软件工程课程教学与交流，未经许可不得用于商业用途。
