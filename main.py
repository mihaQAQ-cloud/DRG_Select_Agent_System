"""
主控入口：一键启动全部服务并触发各智能体任务。
运行方式：python main.py
"""
import sys
import threading
import time
import os       # <--- 新增导入
import webbrowser # <--- 新增导入

import uvicorn

import doc_system
from agents.drg_agent import app as drg_app
from agents.doc_agent import generate as gen_doc, generate_arch, generate_test_doc
from agents.test_agent import run_all as gen_tests

DRG_PORT = 8000
DOC_PORT = 8001

SYSTEM_DESC = (
    "医保DRG入组智能体系统是面向医疗机构的智能化分组辅助平台。"
    "系统以电子病历作为核心输入，结合国家标准DRG分组规则，"
    "借助大语言模型的自然语言理解与推理能力，"
    "自动完成DRG入组、文档生成、测试用例生成及文档管理等全流程任务。"
    "技术栈：Python 3.10+ / FastAPI / SQLite / DeepSeek API。"
)


def _start_server(app, port: int, name: str) -> None:
    print(f"[Main] 启动 {name}，端口 {port} ...")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")


def main() -> None:
    print("=" * 60)
    print("  医保 DRG 入组智能体系统  启动中...")
    print("=" * 60)

    # 步骤1: 启动虚拟文档系统（端口 8001）
    t_doc_sys = threading.Thread(
        target=_start_server,
        args=(doc_system.app, DOC_PORT, "虚拟文档系统"),
        daemon=True,
    )
    t_doc_sys.start()
    time.sleep(1.5)

    # 步骤2: 启动 DRG 入组智能体（端口 8000）
    t_drg = threading.Thread(
        target=_start_server,
        args=(drg_app, DRG_PORT, "DRG入组智能体"),
        daemon=True,
    )
    t_drg.start()
    time.sleep(1.5)

    print("\n[Main] 两个服务已在后台运行，开始触发智能体任务...\n")

    # 步骤3: 文档自动生成智能体
    try:
        doc_id_srs = gen_doc(SYSTEM_DESC)
        print(f"[Main] SRS 文档已生成并提交，doc_id={doc_id_srs}")

        doc_id_arch = generate_arch(SYSTEM_DESC)
        print(f"[Main] 架构设计文档已生成并提交，doc_id={doc_id_arch}")

        doc_id_test = generate_test_doc(SYSTEM_DESC)
        print(f"[Main] 测试文档已生成并提交，doc_id={doc_id_test}")
    except Exception as exc:
        print(f"[Main] 文档生成失败（{exc}）")

    # 步骤4: 测试用例生成智能体
    try:
        cases = gen_tests()
        print(f"[Main] 测试用例生成完成，共 {len(cases)} 条")
    except Exception as exc:
        print(f"[Main] 测试用例生成失败（{exc}）")

    # 汇总
    print("\n" + "=" * 60)
    print("  全部服务已就绪")
    print(f"  DRG 入组智能体  →  http://localhost:{DRG_PORT}/docs")
    print(f"  虚拟文档系统    →  http://localhost:{DOC_PORT}/docs")
    print("=" * 60)
    print("\n快速测试（curl 示例）：")
    print(f"""  curl -X POST http://localhost:{DRG_PORT}/api/drg/classify \\
       -H "Content-Type: application/json" \\
       -d '{{"patient_id":"P001","main_diagnosis":{{"icd_code":"J44.1"}},"secondary_diagnoses":[],"age":65,"gender":"M","los":7}}'""")
    print(f"\n  curl http://localhost:{DOC_PORT}/api/docs/list")
    
    # --- 新增逻辑：打开 index.html ---
    # 获取当前脚本所在目录
    base_dir = os.path.dirname(os.path.abspath(__file__))
    index_path = os.path.join(base_dir, "index.html")
    
    if os.path.exists(index_path):
        print(f"\n[Main] 正在打开界面: {index_path}")
        # file:// 协议用于打开本地文件
        webbrowser.open('file://' + os.path.realpath(index_path))
    else:
        print(f"\n[Main] 警告: 未找到 index.html 文件 ({index_path})")
    # -----------------------------

    print("\n按 Enter 退出...")

    try:
        input()
    except (EOFError, KeyboardInterrupt):
        pass

    print("[Main] 系统已关闭。")
    sys.exit(0)


if __name__ == "__main__":
    main()