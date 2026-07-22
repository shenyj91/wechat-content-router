#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path


def normalize_path(value: str) -> str:
    return str(Path(value).expanduser().resolve()) if value else ""


def prompt_choice(title: str, options: list[tuple[str, str]], default_key: str | None = None, require_explicit: bool = False) -> str:
    print(f"\n{title}")
    for index, (key, label) in enumerate(options, start=1):
        mark = "（默认）" if (default_key and key == default_key) else ""
        print(f"{index}. {label}{mark}")
    while True:
        hint = f"（默认 {default_key}）" if default_key else ""
        raw = input(f"请输入序号{hint}：").strip()
        if not raw:
            if require_explicit:
                print("请明确输入一个序号后再继续（不能留空）。")
                continue
            if default_key:
                return default_key
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                return options[idx][0]
        print("输入不对，请重新选。")


def prompt_yes_no(title: str, default: bool = True) -> bool:
    suffix = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{title} [{suffix}]：").strip().lower()
        if not raw:
            return default
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        print("请输入 y 或 n。")


def pick_path_via_dialog(*, title: str, kind: str) -> str:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:
        return ""

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    root.update()
    try:
        if kind == "dir":
            value = filedialog.askdirectory(title=title)
        else:
            value = filedialog.askopenfilename(title=title)
    finally:
        root.destroy()
    return normalize_path(value) if value else ""


def prompt_path(title: str, *, default: str = "", kind: str = "dir", allow_empty: bool = False) -> str:
    selected = pick_path_via_dialog(title=title, kind=kind)
    if selected:
        return selected
    while True:
        print(f"\n{title}")
        if default:
            print(f"默认：{default}")
        print("可直接粘贴路径，或输入：")
        print("B = 打开选择器")
        if allow_empty:
            print("S = 跳过")
        raw = input("请输入路径 / B / S：").strip()
        if not raw:
            if default:
                return normalize_path(default)
            if allow_empty:
                return ""
            print("这个值不能为空。")
            continue
        upper = raw.upper()
        if upper == "B":
            selected = pick_path_via_dialog(title=title, kind=kind)
            if selected:
                return selected
            print("没有选到路径。")
            continue
        if allow_empty and upper == "S":
            return ""
        return normalize_path(raw)


def prompt_text(title: str, default: str = "", allow_empty: bool = False) -> str:
    while True:
        raw = input(f"{title}{'（默认：' + default + '）' if default else ''}：").strip()
        if raw:
            return raw
        if default:
            return default
        if allow_empty:
            return ""
        print("这个值不能为空。")


def iter_windows_drive_roots() -> list[Path]:
    roots: list[Path] = []
    for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        drive = Path(f"{letter}:/")
        if drive.exists():
            roots.append(drive)
    return roots


def detect_obsidian_vaults() -> list[str]:
    candidates: list[Path] = []
    home = Path.home()

    for root in [home, home / "Documents", home / "Desktop", *iter_windows_drive_roots()]:
        if not root.exists():
            continue
        try:
            if (root / ".obsidian").is_dir():
                candidates.append(root)
            for child in root.iterdir():
                if not child.is_dir():
                    continue
                if (child / ".obsidian").is_dir():
                    candidates.append(child)
        except Exception:
            continue

    unique: list[str] = []
    seen = set()
    for path in candidates:
        resolved = str(path.resolve())
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return unique


def prompt_obsidian_vault_path() -> str:
    detected = detect_obsidian_vaults()
    if detected:
        print("\n已自动识别到这些 Obsidian 库：")
        options: list[tuple[str, str]] = []
        for idx, path in enumerate(detected[:8], start=1):
            options.append((path, f"{path}（自动识别）"))
        options.append(("__browse__", "选择其他文件夹"))
        choice = prompt_choice("请选择要使用的 Obsidian vault（必须输入序号，不能留空）", options, default_key=detected[0], require_explicit=True)
        if choice != "__browse__":
            return choice
    return prompt_path("请选择 Obsidian vault 路径", kind="dir")


def format_mtime(ts: float) -> str:
    if not ts:
        return "未知"
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "未知"


def read_text_candidates(path: Path) -> str:
    for enc in ("utf-8", "gbk", "utf-16", "utf-16-le", "utf-16-be"):
        try:
            content = path.read_text(encoding=enc, errors="ignore")
            if content:
                return content
        except Exception:
            continue
    return ""


def extract_windows_path_candidates(content: str) -> list[Path]:
    candidates: list[Path] = []
    seen = set()

    for raw_line in content.splitlines():
        line = raw_line.strip().strip("\x00").strip().strip('"').strip("'")
        if not line:
            continue

        for match in re.findall(r"[A-Za-z]:(?:\\\\|\\|/)[^\r\n\t\"']+", line):
            normalized = match.replace("\\\\", "\\").strip().strip('"').strip("'")
            key = normalized.lower()
            if key not in seen:
                seen.add(key)
                candidates.append(Path(normalized))

        if re.match(r"^[A-Za-z]:(?:\\|/)", line):
            normalized = line.replace("\\\\", "\\")
            key = normalized.lower()
            if key not in seen:
                seen.add(key)
                candidates.append(Path(normalized))

    return candidates


def build_wechat_account_entry(db_dir: Path, source: str = "") -> dict[str, str | float]:
    resolved = db_dir.resolve()
    wxid = resolved.parent.name
    mtime_target = resolved
    try:
        last_modified = mtime_target.stat().st_mtime
    except Exception:
        last_modified = 0.0

    label = f"{wxid}（最近活跃：{format_mtime(last_modified)}）"
    if source:
        label = f"{label} / {source}"

    return {
        "account_dir": str(resolved),
        "db_dir": str(resolved),
        "wxid": wxid,
        "label": label,
        "last_modified": last_modified,
        "session_db": "",
        "message_dir": "",
    }


def detect_windows_wechat_accounts() -> list[dict[str, str | float]]:
    home = Path.home()
    candidates: list[dict[str, str | float]] = []
    seen = set()

    def add_db_dir(db_dir: Path, source: str = "") -> None:
        try:
            if not db_dir.exists() or not db_dir.is_dir():
                return
            resolved = db_dir.resolve()
        except Exception:
            return
        key = str(resolved).lower()
        if key in seen:
            return
        seen.add(key)
        candidates.append(build_wechat_account_entry(resolved, source=source))

    appdata = os.environ.get("APPDATA", "")
    if appdata:
        config_dir = Path(appdata) / "Tencent" / "xwechat" / "config"
        if config_dir.exists():
            for ini_file in sorted(config_dir.glob("*.ini")):
                content = read_text_candidates(ini_file)
                if not content:
                    continue
                for raw_path in extract_windows_path_candidates(content):
                    path_candidates: list[Path] = []
                    if raw_path.name.lower() == "db_storage":
                        path_candidates.append(raw_path)
                    else:
                        path_candidates.append(raw_path / "xwechat_files")
                        path_candidates.append(raw_path)
                    for candidate in path_candidates:
                        if not candidate.exists():
                            continue
                        if candidate.name.lower() == "db_storage":
                            add_db_dir(candidate, source=f"来自 {ini_file.name}")
                        else:
                            for db_dir in candidate.glob("*/db_storage"):
                                add_db_dir(db_dir, source=f"来自 {ini_file.name}")

    search_roots = [
        home / "Documents" / "xwechat_files",
        home / "xwechat_files",
        home / "文档" / "xwechat_files",
    ]
    for drive in iter_windows_drive_roots():
        search_roots.append(drive / "xwechat_files")

    for root in search_roots:
        if not root.exists():
            continue
        for db_dir in root.glob("*/db_storage"):
            add_db_dir(db_dir, source="本地目录扫描")

    candidates.sort(key=lambda item: float(item.get("last_modified") or 0), reverse=True)
    return candidates


def detect_windows_wechat_paths() -> dict[str, str]:
    result = {
        "db_dir": "",
        "wechat_process": "Weixin.exe",
        "session_db": "",
        "message_dir": "",
        "selected_account_wxid": "",
        "selected_account_label": "",
        "decrypt_workdir": "",
        "decrypt_exe": "",
        "decrypt_python": "",
        "decrypt_script": "",
    }

    detected_accounts = detect_windows_wechat_accounts()
    if detected_accounts:
        selected = detected_accounts[0]
        result["db_dir"] = str(selected.get("db_dir") or "")
        result["session_db"] = str(selected.get("session_db") or result["session_db"])
        result["message_dir"] = str(selected.get("message_dir") or result["message_dir"])
        result["selected_account_wxid"] = str(selected.get("wxid") or "")
        result["selected_account_label"] = str(selected.get("label") or "")

    return result


def collect_windows_wechat_diagnostics() -> dict:
    home = Path.home()
    data_roots = [
        home / "Documents" / "xwechat_files",
        home / "xwechat_files",
        home / "文档" / "xwechat_files",
    ]

    existing_data_roots = [str(p.resolve()) for p in data_roots if p.exists()]
    ini_files: list[str] = []
    wxid_dirs: list[str] = []
    db_dir_hits: list[str] = []

    for root in data_roots:
        if not root.exists():
            continue
        for wxid_dir in sorted(root.iterdir())[:20]:
            if not wxid_dir.is_dir():
                continue
            wxid_dirs.append(str(wxid_dir.resolve()))
            db_storage = wxid_dir / "db_storage"
            if db_storage.exists():
                db_dir_hits.append(str(db_storage.resolve()))

    appdata = os.environ.get("APPDATA", "")
    if appdata:
        config_dir = Path(appdata) / "Tencent" / "xwechat" / "config"
        if config_dir.exists():
            ini_files = [str(p.resolve()) for p in sorted(config_dir.glob("*.ini"))[:20]]

    accounts = detect_windows_wechat_accounts()
    detected = detect_windows_wechat_paths()
    notes: list[str] = []
    if not db_dir_hits:
        notes.append("未找到 Windows 微信 4.x 的 db_storage（xwechat_files/<账号>/db_storage）。")
    else:
        notes.append("已找到微信账号目录，可进入内置解密流程。")

    return {
        "data_roots": existing_data_roots,
        "ini_files": ini_files,
        "wxid_dirs": wxid_dirs[:20],
        "db_dir_hits": db_dir_hits[:20],
        "accounts": accounts[:20],
        "detected": detected,
        "notes": notes,
    }


def build_config(
    *,
    mode: str,
    vault_root: str = "",
    local_root: str = "",
    run_ocr: bool = True,
    default_action: str = "manual_link",
    monitor_mode: str = "manual",
    interval_seconds: int = 900,
    wechat_enabled: bool = False,
    wechat_source_mode: str = "decrypted_files",
    chat_username: str = "filehelper",
    account_dir: str = "",
    db_dir: str = "",
    wechat_process: str = "Weixin.exe",
    session_db: str = "",
    message_dir: str = "",
    message_table: str = "",
    selected_account_wxid: str = "",
    selected_account_label: str = "",
    decrypt_workdir: str = "",
    decrypt_exe: str = "",
    decrypt_python: str = "",
    decrypt_script: str = "",
) -> dict:
    state_root = vault_root or local_root
    return {
        "vault_root": vault_root,
        "state_file": str(Path(state_root) / ".wechat-content-router-state.json"),
        "storage": {
            "mode": mode,
            "local_root": local_root,
        },
        "settings": {
            "openAfterCreate": False,
            "downloadImages": True,
            "runOcr": run_ocr,
            "keepImagesInNote": True,
            "deleteImagesAfterOcr": False,
            "appendImagesAfterText": True,
            "includeFrontmatter": True,
            "includeImportedAt": True,
        },
        "routes": {
            "xhs": {
                "enabled": True,
                "import_root": "微信导入/小红书",
                "asset_root": "微信导入/小红书/assets",
                "save_pdf": mode == "local",
                "prefer_pdf_preview": mode == "local",
                "pdf_source": "browser_render",
            },
            "mp": {
                "enabled": True,
                "import_root": "微信导入/公众号",
                "save_pdf": mode == "local",
                "prefer_pdf_preview": mode == "local",
                "pdf_source": "browser_render",
            },
            "feishu": {
                "enabled": True,
                "import_root": "微信导入/飞书",
                "save_pdf": mode == "local",
                "prefer_pdf_preview": mode == "local",
                "pdf_source": "browser_render",
            },
        },
        "workflow": {
            "default_action": default_action,
            "monitor_mode": monitor_mode,
            "interval_seconds": interval_seconds,
        },
        "wechat": {
            "enabled": wechat_enabled,
            "source_mode": wechat_source_mode,
            "account_dir": account_dir,
            "db_dir": db_dir,
            "wechat_process": wechat_process,
            "session_db": session_db,
            "message_dir": message_dir,
            "chat_username": chat_username,
            "message_table": message_table,
            "selected_account_wxid": selected_account_wxid,
            "selected_account_label": selected_account_label,
            "decrypt_workdir": decrypt_workdir,
            "decrypt_exe": decrypt_exe,
            "decrypt_python": decrypt_python,
            "decrypt_script": decrypt_script,
        },
    }


def interactive_config() -> dict:
    print("开始配置 wechat-content-router")
    mode = prompt_choice(
        "内容要保存到哪里？",
        [("local", "保存到本地普通文件夹"), ("obsidian", "保存到 Obsidian")],
        default_key="local",
    )

    vault_root = ""
    local_root = ""
    if mode == "obsidian":
        vault_root = prompt_obsidian_vault_path()
    else:
        local_root = prompt_path("请选择本地保存目录（直接输入完整路径，或输入 B 打开文件夹选择器）", default="", kind="dir")

    run_ocr = True

    default_action = prompt_choice(
        "你平时更想怎么用？",
        [("manual_link", "手动粘贴链接/分享文案"), ("wechat_monitor", "从微信聊天里自动扫描")],
        default_key="manual_link",
    )

    wechat_enabled = default_action == "wechat_monitor"
    wechat_source_mode = "decrypted_files"
    monitor_mode = "manual"
    interval_seconds = 900
    chat_username = "filehelper"
    db_dir = ""
    wechat_process = "Weixin.exe"
    session_db = ""
    message_dir = ""
    message_table = ""
    selected_account_wxid = ""
    selected_account_label = ""
    decrypt_workdir = ""
    decrypt_exe = ""
    decrypt_python = ""
    decrypt_script = ""

    if wechat_enabled:
        wechat_source_mode = "decrypted_files"

        wechat_entry = prompt_choice(
            "链接从哪个微信入口读取？（你通常会把要整理的内容转发到文件传输助手）",
            [("filehelper", "文件传输助手（推荐，读你转发进来的链接）"), ("custom", "指定某个具体聊天对象")],
            default_key="filehelper",
        )
        if wechat_entry == "custom":
            chat_username = prompt_text("请输入要固定监控的微信会话名（请确认拼写无误）")
        else:
            chat_username = "filehelper"
            print("已确认：从你的【文件传输助手】读取链接。")

        monitor_mode = prompt_choice(
            "自动扫描要怎么跑？",
            [("manual", "先只跑一次"), ("realtime", "尽量实时（15 秒轮询）"), ("interval", "按固定间隔轮询")],
            default_key="manual",
        )
        if monitor_mode == "realtime":
            interval_seconds = 15
        elif monitor_mode == "interval":
            minutes = prompt_text("请输入轮询间隔（分钟）", default="10")
            interval_seconds = max(60, int(float(minutes) * 60))

        if wechat_source_mode == "decrypted_files":
            print("\n将使用内置 WCDB 解密模块自动解密微信数据库。")
            print("先自动识别本机微信账号目录，不行再手动选。")

            accounts = []
            account_dir = ""
            try:
                accounts = detect_windows_wechat_accounts()
            except Exception as e:
                print(f"⚠️ 自动查找账号失败：{e}")

            if accounts:
                if len(accounts) == 1:
                    only = accounts[0]
                    print(f"\n本机只检测到这 1 个微信账号：{only['wxid']} ({only['account_dir']})")
                    if prompt_yes_no("确认就用这个微信账号吗？", default=True):
                        selected = only
                    else:
                        selected = None
                        account_dir = prompt_path("请选择微信账号目录（包含 db_storage）", kind="dir")
                        selected_account_wxid = Path(account_dir).name
                        selected_account_label = selected_account_wxid
                    if selected is not None:
                        account_dir = selected["account_dir"]
                        selected_account_wxid = selected["wxid"]
                        selected_account_label = selected["wxid"]
                        print(f"已绑定微信账号：{selected_account_label}")
                else:
                    print("\n已识别到多个微信账号，请选一个作为固定绑定账号：")
                    options = [(item["account_dir"], f"{item['wxid']} ({item['account_dir']})") for item in accounts]
                    selected_dir = prompt_choice(
                        "请选择要绑定的微信账号（必须输入序号，不能留空）",
                        options,
                        default_key=accounts[0]["account_dir"],
                        require_explicit=True,
                    )
                    selected = next((a for a in accounts if a["account_dir"] == selected_dir), accounts[0])
                    account_dir = selected["account_dir"]
                    selected_account_wxid = selected["wxid"]
                    selected_account_label = selected["wxid"]
            if not account_dir:
                account_dir = prompt_path("请选择微信账号目录（包含 db_storage）", kind="dir")
                selected_account_wxid = Path(account_dir).name
                selected_account_label = selected_account_wxid

            db_dir = account_dir
            session_db = ""
            message_dir = ""
            wechat_process = "Weixin.exe"
            decrypt_workdir = ""
            decrypt_exe = ""
            decrypt_python = ""
            decrypt_script = ""
            message_table = ""
        db_dir = account_dir
        session_db = ""
        message_dir = ""
        wechat_process = "Weixin.exe"
        decrypt_workdir = ""
        decrypt_exe = ""
        decrypt_python = ""
        decrypt_script = ""
        message_table = ""

    return build_config(
        mode=mode,
        vault_root=vault_root,
        local_root=local_root,
        run_ocr=run_ocr,
        default_action=default_action,
        monitor_mode=monitor_mode,
        interval_seconds=interval_seconds,
        wechat_enabled=wechat_enabled,
        wechat_source_mode=wechat_source_mode,
        chat_username=chat_username,
        account_dir=account_dir,
        db_dir=db_dir,
        wechat_process=wechat_process,
        session_db=session_db,
        message_dir=message_dir,
        message_table=message_table,
        selected_account_wxid=selected_account_wxid,
        selected_account_label=selected_account_label,
        decrypt_workdir=decrypt_workdir,
        decrypt_exe=decrypt_exe,
        decrypt_python=decrypt_python,
        decrypt_script=decrypt_script,
    )


def cli_config(args) -> dict:
    vault_root = normalize_path(args.vault_root) if args.vault_root else ""
    local_root = normalize_path(args.local_root) if args.local_root else ""
    if args.mode == "obsidian" and not vault_root:
        raise SystemExit("--mode obsidian 时必须提供 --vault-root")
    if args.mode == "local" and not local_root:
        raise SystemExit("--mode local 时必须提供 --local-root")
    account_dir_norm = normalize_path(args.account_dir) if getattr(args, "account_dir", None) else ""
    selected_account_wxid = ""
    selected_account_label = ""
    if account_dir_norm:
        _p = Path(account_dir_norm)
        selected_account_wxid = _p.parent.name if _p.name.lower() == "db_storage" else _p.name
        selected_account_label = selected_account_wxid

    return build_config(
        mode=args.mode,
        vault_root=vault_root,
        local_root=local_root,
        run_ocr=not args.disable_ocr,
        default_action=args.default_action,
        monitor_mode=args.monitor_mode,
        interval_seconds=args.interval_seconds,
        wechat_enabled=args.wechat_enabled,
        chat_username=args.chat_username,
        account_dir=account_dir_norm,
        db_dir=normalize_path(args.db_dir) if getattr(args, "db_dir", None) else "",
        wechat_process=getattr(args, "wechat_process", None) or "Weixin.exe",
        session_db=normalize_path(args.session_db) if args.session_db else "",
        message_dir=normalize_path(args.message_dir) if args.message_dir else "",
        message_table=args.message_table or "",
        selected_account_wxid=selected_account_wxid,
        selected_account_label=selected_account_label,
        decrypt_workdir=normalize_path(args.decrypt_workdir) if args.decrypt_workdir else "",
        decrypt_exe=normalize_path(args.decrypt_exe) if args.decrypt_exe else "",
        decrypt_python=normalize_path(args.decrypt_python) if args.decrypt_python else "",
        decrypt_script=normalize_path(args.decrypt_script) if args.decrypt_script else "",
    )


def print_config_summary(config: dict) -> None:
    storage = config.get("storage") or {}
    settings = config.get("settings") or {}
    workflow = config.get("workflow") or {}
    wechat = config.get("wechat") or {}
    target = storage.get("local_root") if storage.get("mode") == "local" else config.get("vault_root")
    default_action = workflow.get("default_action") or "manual_link"
    monitor_mode = workflow.get("monitor_mode") or "manual"
    interval_seconds = int(workflow.get("interval_seconds") or 900)

    action_text = "手动粘贴链接/分享文案" if default_action == "manual_link" else "自动扫描微信"

    if not wechat.get("enabled"):
        wechat_entry = "未启用微信自动扫描"
    elif (wechat.get("chat_username") or "filehelper") == "filehelper":
        wechat_entry = "固定监控：文件传输助手"
    else:
        wechat_entry = f"固定监控：{wechat.get('chat_username')}"

    source_mode = wechat.get("source_mode") or "decrypted_files"
    if source_mode == "decrypted_files":
        source_text = "微信数据源：内置 WCDB 解密并导入"
    else:
        source_text = "微信数据源：实验模式（直接扫描微信进程）"

    account_text = wechat.get("selected_account_label") or wechat.get("selected_account_wxid") or "首次运行时自动识别"

    if monitor_mode == "realtime":
        monitor_text = "尽量实时（15 秒轮询）"
    elif monitor_mode == "interval":
        monitor_text = f"固定间隔（约 {max(1, interval_seconds // 60)} 分钟一次）"
    else:
        monitor_text = "手动/只跑一次"

    print("\n配置摘要")
    print(f"- 保存模式：{'本地文件夹' if storage.get('mode') == 'local' else 'Obsidian'}")
    print(f"- 目标路径：{target}")
    print("- OCR：默认开启")
    print(f"- 默认使用方式：{action_text}")
    print(f"- 绑定微信账号：{account_text}")
    print(f"- 微信入口：{wechat_entry}")
    print(f"- {source_text}")
    print(f"- 扫描方式：{monitor_text}")
    print("- 微信数据准备：后台自动处理")
    print("\n你后面最常用的启动方式：")
    print("- 直接打开 START-HERE.bat")
    print("- 或运行：python scripts/use_router.py")


def main():
    parser = argparse.ArgumentParser(description="Create a local config for wechat-content-router.")
    parser.add_argument("--mode", choices=["obsidian", "local"], help="Where imported files should be saved")
    parser.add_argument("--vault-root", help="Absolute path to your Obsidian vault root")
    parser.add_argument("--local-root", help="Absolute path to a normal local folder for direct download")
    parser.add_argument("--disable-ocr", action="store_true", help="Disable OCR in generated config")
    parser.add_argument("--default-action", choices=["manual_link", "wechat_monitor"], default="manual_link")
    parser.add_argument("--monitor-mode", choices=["manual", "realtime", "interval"], default="manual")
    parser.add_argument("--interval-seconds", type=int, default=900)
    parser.add_argument("--wechat-enabled", action="store_true")
    parser.add_argument("--chat-username", default="filehelper")
    parser.add_argument("--account-dir")
    parser.add_argument("--db-dir")
    parser.add_argument("--wechat-process", default="Weixin.exe")
    parser.add_argument("--session-db")
    parser.add_argument("--message-dir")
    parser.add_argument("--message-table")
    parser.add_argument("--decrypt-workdir")
    parser.add_argument("--decrypt-exe")
    parser.add_argument("--decrypt-python")
    parser.add_argument("--decrypt-script")
    parser.add_argument(
        "--output",
        default=str(Path(__file__).with_name("config.json")),
        help="Where to write the config file",
    )
    args = parser.parse_args()

    config = interactive_config() if not args.mode else cli_config(args)
    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n配置已写入：{output_path}")
    print_config_summary(config)


if __name__ == "__main__":
    main()
