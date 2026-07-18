#!/usr/bin/env python3

import json
import subprocess
import sys
from pathlib import Path

from init_local_config import detect_windows_wechat_paths


CONFIG_PATH = Path(__file__).with_name("config.json")
IMPORT_SCRIPT = Path(__file__).with_name("import_latest_wechat_links.py")


def load_config():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(config):
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def merge_detected_wechat_paths(wechat: dict) -> bool:
    changed = False
    detected = detect_windows_wechat_paths()
    for key, value in detected.items():
        if value and not wechat.get(key):
            wechat[key] = value
            changed = True
    return changed


def fill_wechat_paths_from_decrypt_output(wechat: dict) -> bool:
    changed = False
    workdir = wechat.get("decrypt_workdir") or ""
    decrypt_exe = wechat.get("decrypt_exe") or ""

    if not workdir and decrypt_exe:
        workdir = str(Path(decrypt_exe).expanduser().resolve().parent)
        wechat["decrypt_workdir"] = workdir
        changed = True

    if not workdir:
        return changed

    workdir_path = Path(workdir).expanduser().resolve()
    session_candidate = workdir_path / "decrypted" / "session" / "session.db"
    message_candidate = workdir_path / "decrypted" / "message"
    exe_candidate = workdir_path / "WeChatDecrypt.exe"
    dist_exe_candidate = workdir_path / "dist" / "WeChatDecrypt.exe"

    if not wechat.get("decrypt_exe"):
        if exe_candidate.exists():
            wechat["decrypt_exe"] = str(exe_candidate)
            changed = True
        elif dist_exe_candidate.exists():
            wechat["decrypt_exe"] = str(dist_exe_candidate)
            wechat["decrypt_workdir"] = str(dist_exe_candidate.parent)
            changed = True
            workdir_path = dist_exe_candidate.parent
            session_candidate = workdir_path / "decrypted" / "session" / "session.db"
            message_candidate = workdir_path / "decrypted" / "message"

    if session_candidate.exists() and wechat.get("session_db") != str(session_candidate):
        wechat["session_db"] = str(session_candidate)
        changed = True
    if message_candidate.exists() and wechat.get("message_dir") != str(message_candidate):
        wechat["message_dir"] = str(message_candidate)
        changed = True

    return changed


def build_decrypt_command(wechat: dict):
    decrypt_exe = wechat.get("decrypt_exe") or ""
    decrypt_python = wechat.get("decrypt_python") or sys.executable
    decrypt_script = wechat.get("decrypt_script") or ""
    decrypt_workdir = wechat.get("decrypt_workdir") or ""

    if decrypt_exe and Path(decrypt_exe).exists():
        workdir = decrypt_workdir or str(Path(decrypt_exe).expanduser().resolve().parent)
        return [decrypt_exe, "decrypt"], workdir

    if decrypt_script and Path(decrypt_script).exists():
        script_name = Path(decrypt_script).name.lower()
        workdir = decrypt_workdir or str(Path(decrypt_script).expanduser().resolve().parent)
        if script_name in {"main.py", "wechat_decrypt_launcher.py"}:
            return [decrypt_python, decrypt_script, "decrypt"], workdir
        if script_name == "decrypt_db.py":
            return [decrypt_python, decrypt_script, "--incremental"], workdir
        return [decrypt_python, decrypt_script], workdir

    return None, ""


def run_step(command, workdir):
    result = subprocess.run(command, cwd=workdir, capture_output=True, text=True)
    return {
        "command": command,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def validate_import_ready(wechat: dict) -> tuple[bool, str]:
    session_db = wechat.get("session_db") or ""
    message_dir = wechat.get("message_dir") or ""
    if not session_db or not Path(session_db).exists():
        return False, "未能自动找到可用的 session.db"
    if not message_dir or not Path(message_dir).exists():
        return False, "未能自动找到可用的消息数据库目录"
    return True, ""


def main():
    config = load_config()
    wechat = config.get("wechat") or {}
    if not wechat.get("enabled"):
        print(json.dumps({"status": "wechat_disabled"}, ensure_ascii=False, indent=2))
        return

    config_changed = merge_detected_wechat_paths(wechat)
    if fill_wechat_paths_from_decrypt_output(wechat):
        config_changed = True

    decrypt_step = None
    decrypt_cmd, decrypt_workdir = build_decrypt_command(wechat)

    if decrypt_cmd and decrypt_workdir:
        decrypt_step = run_step(decrypt_cmd, decrypt_workdir)
        if decrypt_step["returncode"] != 0:
            print(json.dumps({"status": "decrypt_failed", "decrypt": decrypt_step}, ensure_ascii=False, indent=2))
            sys.exit(1)
        if merge_detected_wechat_paths(wechat):
            config_changed = True
        if fill_wechat_paths_from_decrypt_output(wechat):
            config_changed = True

    if config_changed:
        save_config(config)

    ready, reason = validate_import_ready(wechat)
    if not ready:
        print(json.dumps({
            "status": "wechat_prepare_failed",
            "reason": reason,
            "hint": "程序没能自动准备好微信数据环境，请联系维护者处理这台 Windows 的微信定位/解密适配。",
        }, ensure_ascii=False, indent=2))
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
