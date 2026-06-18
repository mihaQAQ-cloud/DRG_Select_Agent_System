"""
虚拟文档系统（单文件实现）
FastAPI 服务，端口 8001。
提供文档的接收、存储、检索、下载功能。SQLite 数据库自动创建。

修复说明（v1.3）：
  1. 增加文件存在性校验：在 list 和 search 接口返回前，检查物理文件是否存在。
  2. 自动清理孤儿记录：若文件被手动删除，自动从数据库中移除对应元数据，
     确保前端列表与本地文件系统同步。
"""
import os
import shutil
import sqlite3
import uuid
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from fastapi.middleware.cors import CORSMiddleware  #new

app = FastAPI(title="虚拟文档系统", version="1.0.0", description="智能体文档管理服务，端口 8001")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有来源，开发环境用这个就够了
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)                         #new

DB = "data/results.db"
OUT_DIR = "data/outputs"


# ── 数据层 ────────────────────────────────────────────────────────────────────


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


@app.on_event("startup")
def startup() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs("data", exist_ok=True)
    with _get_conn() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS documents (
                id          TEXT    PRIMARY KEY,
                doc_type    TEXT    NOT NULL,
                title       TEXT,
                version     TEXT    DEFAULT '1.0',
                file_path   TEXT    NOT NULL,
                status      TEXT    DEFAULT 'submitted',
                created_at  DATETIME DEFAULT (datetime('now', 'localtime'))
            )"""
        )
        conn.commit()
    print("[DocSystem] 虚拟文档系统已启动，端口 8001")


# ── REST 接口 ─────────────────────────────────────────────────────────────────


@app.get("/api/health", summary="健康检查")
def health():
    return {"status": "healthy", "service": "doc_system"}


@app.post("/api/docs/submit", summary="提交文档（FA-04-01）")
async def submit(
    file: UploadFile = File(...),
    doc_type: str = Form("SRS"),
    title: str = Form(""),
    version: str = Form("1.0"),
):
    """
    接收其他智能体上传的文件，校验后存储到 data/outputs/，写入数据库。
    支持的文件类型：.docx / .xlsx / .pdf / .txt
    """
    allowed_extensions = {".docx", ".xlsx", ".pdf", ".txt", ".json"}
    _, ext = os.path.splitext(file.filename or "")
    if ext.lower() not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型 {ext}，允许: {', '.join(allowed_extensions)}",
        )

    doc_id = str(uuid.uuid4())[:8]
    safe_name = f"{doc_id}_{file.filename}"
    file_path = os.path.join(OUT_DIR, safe_name)

    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # 显式写入本机本地时间，避免依赖 SQLite 的 CURRENT_TIMESTAMP（它返回的是 UTC 时间，
    # 在东八区会比真实创建时间早 8 小时）
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO documents (id, doc_type, title, version, file_path, status, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (doc_id, doc_type, title or file.filename, version, file_path, "submitted", created_at),
        )
        conn.commit()

    return {
        "doc_id": doc_id,
        "status": "submitted",
        "doc_type": doc_type,
        "title": title or file.filename,
        "version": version,
        "created_at": created_at,
    }


@app.get("/api/docs/list", summary="列出已提交文档（FA-04-02 / FA-04-03）")
def list_docs(
    doc_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    """按文档类型过滤，支持分页。并在返回前清理已丢失文件的孤儿记录。"""
    with _get_conn() as conn:
        if doc_type:
            rows = conn.execute(
                "SELECT id, doc_type, title, version, status, created_at, file_path "
                "FROM documents WHERE doc_type=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (doc_type, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, doc_type, title, version, status, created_at, file_path "
                "FROM documents ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
    
    valid_rows = []
    ids_to_delete = []

    for r in rows:
        row_dict = dict(r)
        file_path = row_dict.pop('file_path') # 取出路径用于校验，不返回给前端
        
        # 【核心修改】检查文件是否真实存在
        if not os.path.exists(file_path):
            print(f"[DocSystem] 检测到孤儿记录: {row_dict['id']}, 文件缺失: {file_path}")
            ids_to_delete.append(row_dict['id'])
        else:
            valid_rows.append(row_dict)

    # 批量删除孤儿记录
    if ids_to_delete:
        with _get_conn() as conn:
            conn.execute("DELETE FROM documents WHERE id IN ({})".format(",".join(["?"]*len(ids_to_delete))), ids_to_delete)
            conn.commit()
        print(f"[DocSystem] 已清理 {len(ids_to_delete)} 条孤儿记录")

    return valid_rows


@app.get("/api/docs/search", summary="关键词搜索文档（FA-04-03）")
def search_docs(
    keyword: str = "",
    doc_type: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    """按标题关键词、类型、日期范围检索文档。同样增加清理逻辑。"""
    conditions = []
    params: list = []

    if keyword:
        conditions.append("title LIKE ?")
        params.append(f"%{keyword}%")
    if doc_type:
        conditions.append("doc_type = ?")
        params.append(doc_type)
    if date_from:
        conditions.append("created_at >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("created_at <= ?")
        params.append(date_to)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    
    with _get_conn() as conn:
        # 查询时带上 file_path
        rows = conn.execute(
            f"SELECT id, doc_type, title, version, status, created_at, file_path "
            f"FROM documents {where} ORDER BY created_at DESC LIMIT 100",
            params,
        ).fetchall()

    valid_rows = []
    ids_to_delete = []

    for r in rows:
        row_dict = dict(r)
        file_path = row_dict.pop('file_path')
        
        if not os.path.exists(file_path):
            ids_to_delete.append(row_dict['id'])
        else:
            valid_rows.append(row_dict)

    if ids_to_delete:
        with _get_conn() as conn:
             conn.execute("DELETE FROM documents WHERE id IN ({})".format(",".join(["?"]*len(ids_to_delete))), ids_to_delete)
             conn.commit()

    return {"results": valid_rows, "count": len(valid_rows)}


@app.get("/api/docs/{doc_id}", summary="查询文档元数据（FA-04-04）")
def get_doc_meta(doc_id: str):
    """按 doc_id 查询单个文档的元数据。"""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT id, doc_type, title, version, file_path, status, created_at "
            "FROM documents WHERE id=?",
            (doc_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"文档 {doc_id} 不存在")
    return dict(row)


@app.get("/api/docs/{doc_id}/download", summary="下载文档文件（FA-04-03）")
def download(doc_id: str):
    """按 doc_id 返回文件下载响应。"""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT file_path, title FROM documents WHERE id=?", (doc_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"文档 {doc_id} 不存在")
    file_path, title = row["file_path"], row["title"]
    if not os.path.exists(file_path):
        raise HTTPException(status_code=410, detail="文件已从存储中移除")
    return FileResponse(
        file_path,
        filename=os.path.basename(file_path),
        media_type="application/octet-stream",
    )


@app.delete("/api/docs/{doc_id}", summary="删除文档记录")
def delete_doc(doc_id: str):
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT file_path FROM documents WHERE id=?", (doc_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="文档不存在")
        conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        conn.commit()
    file_path = row["file_path"]
    if os.path.exists(file_path):
        os.remove(file_path)
    return {"status": "deleted", "doc_id": doc_id}