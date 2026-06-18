
"""
DRG 入组智能体（单文件实现）
内部按五个区块组织：数据模型 → 数据层 → 规则引擎层 → LLM 层 → API 层
端口: 8000
"""
import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Literal, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, field_validator

from agents.llm_service import LLMService

from fastapi.middleware.cors import CORSMiddleware  #new

app = FastAPI(title="DRG 入组智能体", version="1.0.0", description="医保 DRG 自动入组服务")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有来源，开发环境用这个就够了
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)                         #new

llm = LLMService()

# ── 数据模型 ──────────────────────────────────────────────────────────────────


class DiagnosisInput(BaseModel):
    icd_code: str
    name: Optional[str] = None

    @field_validator("icd_code")
    @classmethod
    def validate_icd(cls, v: str) -> str:
        v = v.strip().upper()
        if not re.match(r"^[A-Z]\d{2}(\.\d+)?(X\d+)?$", v):
            raise ValueError(
                f"ICD-10 编码格式无效: {v!r}（正确格式：字母+两位数字，如 J44.1）"
            )
        return v


class EMRInput(BaseModel):
    patient_id: str
    main_diagnosis: DiagnosisInput
    secondary_diagnoses: List[DiagnosisInput] = []
    main_op_code: Optional[str] = None
    # [修改1] 新增其他手术列表
    secondary_ops: List[str] = [] 
    age: int
    gender: Literal["M", "F"]
    # [修改2] 移除 los 字段

class DRGResult(BaseModel):
    emr_id: Optional[int] = None
    patient_id: str
    mdc_code: str
    mdc_name: str
    adrg_code: str
    adrg_name: str
    drg_code: str
    drg_name: str
    cc_mcc_status: str
    reasoning: str
    engine_mode: str
    created_at: str


# ── 数据层 ────────────────────────────────────────────────────────────────────

DB = "data/results.db"


def init_db() -> None:
    os.makedirs("data", exist_ok=True)
    with sqlite3.connect(DB) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS emr_records (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id      TEXT    NOT NULL,
                main_diag_code  TEXT    NOT NULL,
                main_op_code    TEXT,
                secondary_diags TEXT,
                age             INTEGER,
                gender          TEXT,
                secondary_ops   TEXT,
                created_at      DATETIME DEFAULT (datetime('now', 'localtime'))
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS drg_results (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                emr_id       INTEGER REFERENCES emr_records(id),
                mdc_code     TEXT,
                adrg_code    TEXT,
                drg_code     TEXT,
                cc_mcc_status TEXT,
                reasoning    TEXT,
                engine_mode  TEXT,
                created_at   DATETIME DEFAULT (datetime('now', 'localtime'))
            )"""
        )
        conn.commit()


def save_emr_and_result(emr: EMRInput, result: dict) -> int:
    secondary_json = json.dumps(
        [d.icd_code for d in emr.secondary_diagnoses], ensure_ascii=False
    )
    # [修改3] 序列化其他手术编码
    secondary_ops_json = json.dumps(emr.secondary_ops or [], ensure_ascii=False)
    
    # 显式计算一次本机本地时间，两条 INSERT 共用，避免依赖 SQLite 的 CURRENT_TIMESTAMP
    # （它返回的是 UTC 时间，在东八区会比真实创建时间早 8 小时）
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with sqlite3.connect(DB) as conn:
        # 注意：如果数据库已存在，可能需要 ALTER TABLE 添加 secondary_ops 列，
        # 或者为了简单起见，我们暂时只存主要信息，或者更新表结构。
        # 这里假设我们更新插入语句以适配新字段（需先执行 ALTER TABLE）
        
        # 简易处理：如果不想改数据库结构，可以将 secondary_ops 拼接到 secondary_diags 或单独存
        # 但为了规范，建议在 init_db 中添加列。此处展示逻辑变更：
        
        cur = conn.execute(
            "INSERT INTO emr_records "
            "(patient_id, main_diag_code, main_op_code, secondary_diags, secondary_ops, age, gender, created_at) " # 移除 los, 增加 secondary_ops
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                emr.patient_id,
                emr.main_diagnosis.icd_code,
                emr.main_op_code,
                secondary_json,
                secondary_ops_json,
                emr.age,
                emr.gender,
                # emr.los 移除
                created_at,
            ),
        )
        emr_id = cur.lastrowid
        conn.execute(
            "INSERT INTO drg_results "
            "(emr_id, mdc_code, adrg_code, drg_code, cc_mcc_status, reasoning, engine_mode, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                emr_id,
                result["mdc_code"],
                result["adrg_code"],
                result["drg_code"],
                result["cc_mcc_status"],
                result["reasoning"],
                result["engine_mode"],
                created_at,
            ),
        )
        conn.commit()
    return emr_id


def list_results(limit: int = 20, offset: int = 0) -> list:
    with sqlite3.connect(DB) as conn:
        rows = conn.execute(
            "SELECT r.id, r.emr_id, r.mdc_code, r.adrg_code, r.drg_code, "
            "r.cc_mcc_status, r.engine_mode, r.created_at, e.patient_id "
            "FROM drg_results r JOIN emr_records e ON r.emr_id = e.id "
            "ORDER BY r.id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    return [
        {
            "id": r[0],
            "emr_id": r[1],
            "mdc_code": r[2],
            "adrg_code": r[3],
            "drg_code": r[4],
            "cc_mcc_status": r[5],
            "engine_mode": r[6],
            "created_at": r[7],
            "patient_id": r[8],
        }
        for r in rows
    ]


# ── 规则引擎层 ────────────────────────────────────────────────────────────────


class DRGRuleEngine:
    def __init__(self) -> None:
        self.rules: dict = {}

    def load_rules(self, path: str) -> None:
        with open(path, encoding="utf-8") as f:
            self.rules = json.load(f)

    # FA-01-02
    def match_mdc(self, icd_code: str) -> Optional[str]:
        """ICD-10 前缀匹配 MDC 大类，优先匹配最长前缀。"""
        mdc_map: dict = self.rules.get("mdc_mapping", {})
        for prefix in sorted(mdc_map.keys(), key=len, reverse=True):
            if icd_code.upper().startswith(prefix.upper()):
                return mdc_map[prefix]
        return None

    # FA-01-03
    def match_adrg(self, mdc_code: str, main_op_code: Optional[str], secondary_ops: List[str], main_icd: str = "") -> str:
        """
        MDC + 手术编码前缀匹配 ADRG 核心分组。
        策略：收集所有有效手术编码（主手术 + 其他手术），尝试匹配最具体的 ADRG。
        """
        adrg_map: dict = self.rules.get("adrg_mapping", {})
        
        # 收集所有候选手术编码
        all_ops = []
        if main_op_code:
            all_ops.append(main_op_code)
        if secondary_ops:
            all_ops.extend([op for op in secondary_ops if op]) # 过滤空字符串
        
        best_adrg: Optional[str] = None
        best_len: int = 0
        fallback_adrg: Optional[str] = None

        # 遍历规则映射
        for key, adrg in adrg_map.items():
            if "," not in key:
                continue
            key_mdc, key_op = key.split(",", 1)
            if key_mdc != mdc_code:
                continue
            
            if key_op == "none":
                fallback_adrg = adrg
                continue
                
            # 检查当前规则的手术前缀是否匹配任意一个候选手术
            for op in all_ops:
                if op.startswith(key_op):
                    print(f"[DEBUG] Matched Op: {op} with Rule Prefix: {key_op} -> ADRG: {adrg}") # 新增调试日志
                    if len(key_op) > best_len:
                        best_len = len(key_op)
                        best_adrg = adrg
                    break # 找到一个匹配即可，继续寻找更长的前缀

        if best_adrg:
            return best_adrg

        # 无手术匹配时：先用诊断前缀覆盖表精细选 ADRG
        if not all_ops and main_icd:
            diag_map: dict = self.rules.get("diag_adrg_mapping", {})
            for prefix in sorted(diag_map.keys(), key=len, reverse=True):
                if main_icd.upper().startswith(prefix.upper()):
                    return diag_map[prefix]

        if not all_ops and fallback_adrg:
            return fallback_adrg
        
        # 如果有手术但没匹配到具体 ADRG，且有 fallback，通常回退到内科组或特定未匹配组
        return fallback_adrg or f"{mdc_code[3:]}99"

    # FA-01-04
    def eval_cc_mcc(
        self,
        secondary_codes: List[str],
        mdc_code: str,
        main_diag_code: str,
    ) -> str:
        """评估次诊断 CC/MCC 状态，支持中国扩展码前向前缀匹配。

        匹配规则：规则表中的编码（去掉 xNNN 扩展后）以临床编码为前缀时命中。
        例：临床 J96.0 命中规则 J96.000；临床 E11.9 不命中规则 E11.000（兄弟码）。
        """
        excl_table: dict = self.rules.get("exclusion_table", {})
        excluded: set = set(excl_table.get(f"{mdc_code},{main_diag_code}", []))

        _ext = re.compile(r'[xX]\d+$')

        def _normalize(code: str) -> str:
            """去掉中国扩展后缀 xNNN/XNNN，保留基础 ICD 编码。"""
            return _ext.sub('', code).rstrip('.')

        def _build_forward_index(raw_list: list) -> dict:
            """按 3 字符大类索引，加速前向前缀查找。"""
            idx: dict = {}
            for c in raw_list:
                base = _normalize(c)
                cat = base[:3]
                if cat not in idx:
                    idx[cat] = []
                idx[cat].append(base)
            return idx

        mcc_idx: dict = _build_forward_index(self.rules.get("mcc_list", []))
        cc_idx: dict = _build_forward_index(self.rules.get("cc_list", []))

        def _matches(code: str, forward_idx: dict) -> bool:
            """规则表中是否存在以 code 为前缀的条目（单向：规则码是临床码的子码或相等）。"""
            norm = _normalize(code)
            if len(norm) < 3:
                return False
            cat = norm[:3]
            return any(entry.startswith(norm) for entry in forward_idx.get(cat, []))

        has_mcc = False
        has_cc = False
        for code in secondary_codes:
            if code in excluded:
                continue
            if _matches(code, mcc_idx):
                has_mcc = True
                break
            if _matches(code, cc_idx):
                has_cc = True

        if has_mcc:
            return "MCC"
        if has_cc:
            return "CC"
        return "无"

    # [修改5] 更新 classify 方法签名和调用
    def classify(self, emr: EMRInput) -> dict:
        """执行 MDC → ADRG → DRG 三层入组"""
        main_icd = emr.main_diagnosis.icd_code

        mdc_code = self.match_mdc(main_icd)
        if not mdc_code:
            raise ValueError(
                f"主诊断编码 {main_icd} 未匹配到任何 MDC 大类"
            )

        # 传入 secondary_ops
        adrg_code = self.match_adrg(mdc_code, emr.main_op_code, emr.secondary_ops, main_icd)

        secondary_codes = [d.icd_code for d in emr.secondary_diagnoses]
        cc_mcc = self.eval_cc_mcc(secondary_codes, mdc_code, main_icd)

        severity = {"MCC": "1", "CC": "3", "无": "5"}[cc_mcc]
        drg_code = adrg_code + severity

        mdc_name = self.rules.get("mdc_info", {}).get(mdc_code, {}).get("name", mdc_code)
        adrg_name = self.rules.get("adrg_info", {}).get(adrg_code, {}).get("name", adrg_code)
        suffix_map = {"MCC": "伴严重并发症", "CC": "伴并发症", "无": "无并发症"}
        drg_name = f"{adrg_name}-{suffix_map[cc_mcc]}"

        return {
            "mdc_code": mdc_code,
            "mdc_name": mdc_name,
            "adrg_code": adrg_code,
            "adrg_name": adrg_name,
            "drg_code": drg_code,
            "drg_name": drg_name,
            "cc_mcc_status": cc_mcc,
        }


engine = DRGRuleEngine()

# ── LLM 层：生成入组说明 ──────────────────────────────────────────────────────


def _build_reasoning_prompt(emr: EMRInput, result: dict) -> str:
    secondary = (
        "、".join(
            f"{d.icd_code}({d.name or ''})" for d in emr.secondary_diagnoses
        )
        or "无"
    )
    # [修改6] 移除 los，增加 secondary_ops 展示
    sec_ops_str = "、".join(emr.secondary_ops) if emr.secondary_ops else "无"
    
    return (
        "请为以下 DRG 入组结果生成简洁的中文入组说明（不超过 200 字），"
        "逐步说明 MDC 匹配、ADRG 分组、CC/MCC 评估的逻辑：\n"
        f"患者 ID: {emr.patient_id}，年龄: {emr.age}，"
        f"性别: {'男' if emr.gender == 'M' else '女'}\n" # 移除住院天数
        f"主诊断: {emr.main_diagnosis.icd_code}"
        f"（{emr.main_diagnosis.name or ''}）\n"
        f"次诊断: {secondary}\n"
        f"主手术编码: {emr.main_op_code or '无'}\n"
        f"其他手术编码: {sec_ops_str}\n" # 新增
        f"→ MDC: {result['mdc_code']} {result['mdc_name']}\n"
        f"→ ADRG: {result['adrg_code']} {result['adrg_name']}\n"
        f"→ 并发症状态: {result['cc_mcc_status']}\n"
        f"→ DRG 组号: {result['drg_code']} {result['drg_name']}"
    )


def _do_classify(emr: EMRInput) -> DRGResult:
    if not engine.rules:
        raise HTTPException(status_code=503, detail="DRG 规则文件未加载，请检查 rules/drg_rules.json")
    try:
        result = engine.classify(emr)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    prompt = _build_reasoning_prompt(emr, result)
    reasoning = llm.chat(prompt)
    engine_mode = "rule" if reasoning.startswith("[规则引擎模式]") else "llm"

    emr_id = save_emr_and_result(
        emr, {**result, "reasoning": reasoning, "engine_mode": engine_mode}
    )
    return DRGResult(
        emr_id=emr_id,
        patient_id=emr.patient_id,
        **result,
        reasoning=reasoning,
        engine_mode=engine_mode,
        created_at=datetime.now().isoformat(),
    )


# ── API 层 ────────────────────────────────────────────────────────────────────


@app.on_event("startup")
def startup() -> None:
    init_db()
    rules_path = "rules/drg_rules.json"
    if Path(rules_path).exists():
        engine.load_rules(rules_path)
        print(f"[DRGAgent] 规则文件已加载: {rules_path}")
    else:
        print(f"[DRGAgent] 警告：规则文件不存在 {rules_path}")


@app.get("/api/health", summary="健康检查")
def health_check():
    return {"status": "healthy", "rules_loaded": bool(engine.rules)}


@app.post("/api/drg/classify", response_model=DRGResult, summary="单条病历 DRG 入组")
def classify(emr: EMRInput):
    """
    输入电子病历，自动执行 MDC → ADRG → DRG 三层入组，
    并调用 LLM 生成入组说明（LLM 不可用时降级为规则引擎模式）。
    """
    return _do_classify(emr)


@app.post("/api/drg/batch", summary="批量病历 DRG 入组")
def batch_classify(emrs: List[EMRInput]):
    """批量入组，返回每条病历对应的 DRGResult 列表。"""
    results = []
    errors = []
    for emr in emrs:
        try:
            results.append(_do_classify(emr))
        except HTTPException as exc:
            errors.append({"patient_id": emr.patient_id, "error": exc.detail})
    return {"results": results, "errors": errors, "total": len(emrs)}


@app.get("/api/drg/reload", summary="热更新规则文件")
def reload_rules():
    """重新从磁盘加载 drg_rules.json，无需重启服务。"""
    rules_path = "rules/drg_rules.json"
    if not Path(rules_path).exists():
        raise HTTPException(status_code=404, detail="规则文件不存在")
    engine.load_rules(rules_path)
    return {"status": "ok", "message": "规则文件已重新加载"}


@app.get("/api/drg/results", summary="查询历史入组记录")
def get_results(limit: int = 20, offset: int = 0):
    return {"records": list_results(limit, offset)}
