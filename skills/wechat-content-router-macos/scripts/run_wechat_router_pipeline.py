#!/usr/bin/env python3

import importlib
import json
import subprocess
import sys
from pathlib import Path


CONFIG_PATH = Path(__file__).with_name("config.json")
IMPORT_SCRIPT = Path(__file__).with_name("import_latest_wechat_links.py")
SCRIPT_DIR = Path(__file__).resolve().parent


def ensure_python_deps():
    """首次运行若缺少 Python 依赖，自动 pip 安装，保证干净克隆也能直接跑。"""
    required = ["requests", "lxml", "browser_cookie3", "zstandard"]
    missing = []
    for mod in required:
        try:
            importlib.import_module(mod)
        except ImportError:
            missing.append(mod)
    if not missing:
        return
    req_path = SCRIPT_DIR / "requirements.txt"
    if not req_path.exists():
        raise RuntimeError(f"缺少依赖 {missing}，且未找到 requirements.txt（{req_path}）")
    print(f"[bootstrap] 缺少 Python 依赖 {missing}，正在安装…", file=sys.stderr)
    subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(req_path)], check=True)


def load_config():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def run_step(command, workdir):
    result = subprocess.run(command, cwd=workdir, capture_output=True, text=True)
    return {
        "command": command,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def main():
    config = load_config()
    ensure_python_deps()
    wechat = config.get("wechat") or {}
    if not wechat.get("enabled"):
        print(json.dumps({"status": "wechat_disabled"}, ensure_ascii=False, indent=2))
        return

    decrypt_step = None
    decrypt_python = wechat.get("decrypt_python")
    decrypt_script = wechat.get("decrypt_script")
    decrypt_workdir = wechat.get("decrypt_workdir")

    # macOS 一键解密桥：若未显式配置 decrypt_*，自动接线内置桥
    # （decrypt_wechat_db.py → node decrypt_fetch.mjs → WxLens xkey_helper + libwcdb_api）。
    # 非 macOS 保持原行为：未配置则跳过解密步骤（由外部工具预解密）。
    if not (decrypt_python and decrypt_script and decrypt_workdir) and sys.platform == "darwin":
        decrypt_python = sys.executable
        decrypt_script = str(SCRIPT_DIR / "decrypt_wechat_db.py")
        decrypt_workdir = str(SCRIPT_DIR)

    if decrypt_python and decrypt_script and decrypt_workdir:
        decrypt_cmd = [decrypt_python, decrypt_script, "--incremental", "--config", str(CONFIG_PATH)]
        decrypt_step = run_step(decrypt_cmd, decrypt_workdir)
        if decrypt_step["returncode"] != 0:
            print(json.dumps({"status": "decrypt_failed", "decrypt": decrypt_step}, ensure_ascii=False, indent=2))
            sys.exit(1)

    import_cmd = [sys.executable, str(IMPORT_SCRIPT)]
    import_step = run_step(import_cmd, str(Path(__file__).parent))
    if import_step["returncode"] != 0:
        print(json.dumps({
            "status": "import_failed",
            "decrypt": decrypt_step,
            "import": import_step,
        }, ensure_ascii=False, indent=2))
        sys.exit(1)

    try:
        import_result = json.loads(import_step["stdout"])
    except json.JSONDecodeError:
        import_result = {"raw_output": import_step["stdout"]}

    print(json.dumps({
        "status": "ok",
        "decrypt": decrypt_step,
        "import": import_result,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
