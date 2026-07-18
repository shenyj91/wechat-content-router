#!/usr/bin/env python3

import json
import os
import subprocess
import sys
from pathlib import Path

from init_local_config import (
    collect_windows_wechat_diagnostics,
    detect_windows_wechat_accounts,
    detect_windows_wechat_paths,
)


CONFIG_PATH = Path(__file__).with_name("config.json")
IMPORT_SCRIPT = Path(__file__).with_name("import_latest_wechat_links.py")


def load_config():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(config):
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def get_bound_account_label(wechat: dict) -> str:
    return (
        wechat.get("selected_account_label")
        or wechat.get("selected_account_wxid")
        or "当前绑定微信账号"
    )


def align_selected_wechat_account(wechat: dict) -> bool:
    changed = False
    accounts = detect_windows_wechat_accounts()
    if not accounts:
        return False

    selected_db_dir = (wechat.get("db_dir") or "").strip().lower()
    selected_wxid = (wechat.get("selected_account_wxid") or "").strip().lower()
    selected_label = (wechat.get("selected_account_label") or "").strip().lower()

    selected = None
    for account in accounts:
        account_db_dir = str(account.get("db_dir") or "").strip().lower()
        account_wxid = str(account.get("wxid") or "").strip().lower()
        account_label = str(account.get("label") or "").strip().lower()
        if selected_db_dir and account_db_dir == selected_db_dir:
            selected = account
            break
        if selected_wxid and account_wxid == selected_wxid:
            selected = account
            break
        if selected_label and account_label == selected_label:
            selected = account
            break

    if not selected:
        if selected_wxid or selected_db_dir or selected_label:
            return False
        selected = accounts[0]

    for field, key in (
        ("db_dir", "db_dir"),
        ("session_db", "session_db"),
        ("message_dir", "message_dir"),
        ("selected_account_wxid", "wxid"),
        ("selected_account_label", "label"),
    ):
        value = str(selected.get(key) or "")
        if value and wechat.get(field) != value:
            wechat[field] = value
            changed = True
    return changed


def merge_detected_wechat_paths(wechat: dict) -> bool:
    changed = False
    if align_selected_wechat_account(wechat):
        changed = True
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


def sync_decrypt_tool_config(wechat: dict) -> str:
    decrypt_workdir = wechat.get("decrypt_workdir") or ""
    db_dir = wechat.get("db_dir") or ""
    if not decrypt_workdir or not db_dir:
        return ""

    config_path = Path(decrypt_workdir).expanduser().resolve() / "config.json"
    existing = {}
    if config_path.exists():
        try:
            existing = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    merged = {
        "db_dir": db_dir,
        "wechat_process": wechat.get("wechat_process") or "Weixin.exe",
        "keys_file": existing.get("keys_file") or "all_keys.json",
        "decrypted_dir": existing.get("decrypted_dir") or "decrypted",
        "decoded_image_dir": existing.get("decoded_image_dir") or "decoded_images",
        "selected_account_wxid": wechat.get("selected_account_wxid") or "",
        "selected_account_label": wechat.get("selected_account_label") or "",
    }
    merged.update(existing)
    merged["db_dir"] = db_dir
    merged["wechat_process"] = wechat.get("wechat_process") or merged.get("wechat_process") or "Weixin.exe"
    merged["selected_account_wxid"] = wechat.get("selected_account_wxid") or merged.get("selected_account_wxid") or ""
    merged["selected_account_label"] = wechat.get("selected_account_label") or merged.get("selected_account_label") or ""

    config_path.write_text(json.dumps(merged, ensure_ascii=False, indent=4), encoding="utf-8")
    return str(config_path)


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


def build_failure_hints(decrypt_step, diagnostics: dict, wechat: dict) -> list[str]:
    hints: list[str] = []
    stderr = ""
    stdout = ""
    if decrypt_step:
        stderr = decrypt_step.get("stderr") or ""
        stdout = decrypt_step.get("stdout") or ""
    combined = f"{stderr}\n{stdout}"
    account_label = get_bound_account_label(wechat)

    if diagnostics.get("db_dir_hits") and not diagnostics.get("tool_exe_hits") and not diagnostics.get("tool_dir_hits"):
        hints.append(f"已找到 {account_label} 的 xwechat 数据目录，但本机没找到可用的 WeChatDecrypt 工具。")
    if "0 candidate keys" in combined or "未能提取到任何密钥" in combined:
        hints.append(f"已定位到 {account_label} 的微信 4.1+ 数据目录，但当前提 key 失败，疑似命中 4.1 新口令/密钥派生问题。")
    if "db_dir" in combined and "未配置" in combined:
        hints.append(f"解密工具没有吃到 {account_label} 的正确数据目录，我会优先检查工具目录里的 config.json 是否成功回填。")
    if not diagnostics.get("db_dir_hits"):
        hints.append("当前机器上还没找到 xwechat_files/<账号>/db_storage。可先在微信设置→文件管理里确认数据目录。")
    return hints


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
    decrypt_tool_config = sync_decrypt_tool_config(wechat)
    if decrypt_tool_config:
        config_changed = True

    if decrypt_cmd and decrypt_workdir:
        decrypt_step = run_step(decrypt_cmd, decrypt_workdir)
        if decrypt_step["returncode"] != 0:
            diagnostics = collect_windows_wechat_diagnostics()
            print(json.dumps({
                "status": "decrypt_failed",
                "bound_account": {
                    "wxid": wechat.get("selected_account_wxid") or "",
                    "label": wechat.get("selected_account_label") or "",
                },
                "decrypt": decrypt_step,
                "decrypt_tool_config": decrypt_tool_config,
                "diagnostics": diagnostics,
                "hints": build_failure_hints(decrypt_step, diagnostics, wechat),
            }, ensure_ascii=False, indent=2))
            sys.exit(1)
        if merge_detected_wechat_paths(wechat):
            config_changed = True
        if fill_wechat_paths_from_decrypt_output(wechat):
            config_changed = True

    if config_changed:
        save_config(config)

    ready, reason = validate_import_ready(wechat)
    if not ready:
        diagnostics = collect_windows_wechat_diagnostics()
        print(json.dumps({
            "status": "wechat_prepare_failed",
            "reason": reason,
            "bound_account": {
                "wxid": wechat.get("selected_account_wxid") or "",
                "label": wechat.get("selected_account_label") or "",
            },
            "hint": "程序没能自动准备好微信数据环境，请联系维护者处理这台 Windows 的微信定位/解密适配。",
            "diagnostics": diagnostics,
            "decrypt_tool_config": decrypt_tool_config,
            "hints": build_failure_hints(decrypt_step, diagnostics, wechat),
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
        "bound_account": {
            "wxid": wechat.get("selected_account_wxid") or "",
            "label": wechat.get("selected_account_label") or "",
        },
        "decrypt_tool_config": decrypt_tool_config,
        "decrypt": decrypt_step,
        "import": import_result,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
