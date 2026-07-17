#!/usr/bin/env python3

import json
import subprocess
import sys
from pathlib import Path


CONFIG_PATH = Path(__file__).with_name("config.json")
IMPORT_SCRIPT = Path(__file__).with_name("import_latest_wechat_links.py")


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
    wechat = config.get("wechat") or {}
    if not wechat.get("enabled"):
        print(json.dumps({"status": "wechat_disabled"}, ensure_ascii=False, indent=2))
        return

    decrypt_step = None
    decrypt_python = wechat.get("decrypt_python")
    decrypt_script = wechat.get("decrypt_script")
    decrypt_workdir = wechat.get("decrypt_workdir")

    if decrypt_python and decrypt_script and decrypt_workdir:
        decrypt_cmd = [decrypt_python, decrypt_script, "--incremental"]
        decrypt_step = run_step(decrypt_cmd, decrypt_workdir)
        if decrypt_step["returncode"] != 0:
            print(json.dumps({"status": "decrypt_failed", "decrypt": decrypt_step}, ensure_ascii=False, indent=2))
            sys.exit(1)

    import_cmd = ["python3", str(IMPORT_SCRIPT)]
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
