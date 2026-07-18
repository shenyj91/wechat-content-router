#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def normalize_path(value: str) -> str:
    return str(Path(value).expanduser().resolve()) if value else ""


def prompt_choice(title: str, options: list[tuple[str, str]], default_key: str | None = None) -> str:
    print(f"\n{title}")
    for index, (_, label) in enumerate(options, start=1):
        print(f"{index}. {label}")
    while True:
        raw = input(f"请输入序号{'（默认 ' + default_key + '）' if default_key else ''}：").strip()
        if not raw and default_key:
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


def detect_windows_wechat_paths() -> dict[str, str]:
    result = {
        "session_db": "",
        "message_dir": "",
        "decrypt_workdir": "",
        "decrypt_python": "",
        "decrypt_script": "",
    }

    home = Path.home()
    candidates = []
    docs = home / "Documents" / "WeChat Files"
    if docs.exists():
        candidates.append(docs)
    docs_cn = home / "文档" / "WeChat Files"
    if docs_cn.exists():
        candidates.append(docs_cn)

    wxid_dirs: list[Path] = []
    for base in candidates:
        wxid_dirs.extend(sorted(base.glob("wxid_*")))

    for wxid_dir in wxid_dirs:
        for db in wxid_dir.rglob("session.db"):
            result["session_db"] = str(db.resolve())
            break
        if result["session_db"]:
            break

    for wxid_dir in wxid_dirs:
        msg_dirs = [p for p in wxid_dir.rglob("Msg") if p.is_dir()]
        if msg_dirs:
            result["message_dir"] = str(msg_dirs[0].resolve())
            break

    for name in ("wechat-decrypt", "WeChatDump", "wechat_dump"):
        for base in (home / "Downloads", home / "Desktop", home / "Documents"):
            candidate = base / name
            if candidate.exists():
                result["decrypt_workdir"] = str(candidate.resolve())
                break
        if result["decrypt_workdir"]:
            break

    python_candidate = Path.home() / "AppData" / "Local" / "Programs" / "Python"
    if python_candidate.exists():
        pythons = sorted(python_candidate.glob("Python*/python.exe"))
        if pythons:
            result["decrypt_python"] = str(pythons[-1].resolve())

    if result["decrypt_workdir"]:
        scripts = list(Path(result["decrypt_workdir"]).rglob("*.py"))
        for script in scripts:
            if "decrypt" in script.name.lower() or "dump" in script.name.lower():
                result["decrypt_script"] = str(script.resolve())
                break

    return result


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
    chat_username: str = "filehelper",
    session_db: str = "",
    message_dir: str = "",
    message_table: str = "",
    decrypt_workdir: str = "",
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
            "session_db": session_db,
            "message_dir": message_dir,
            "chat_username": chat_username,
            "message_table": message_table,
            "decrypt_workdir": decrypt_workdir,
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
        vault_root = prompt_path("请选择 Obsidian vault 路径", kind="dir")
    else:
        local_root = prompt_path("请选择本地保存目录", default="~/Documents/ImportedContent", kind="dir")

    run_ocr = prompt_yes_no("要不要开启图片 OCR？", default=True)

    default_action = prompt_choice(
        "你平时更想怎么用？",
        [("manual_link", "手动粘贴链接/分享文案"), ("wechat_monitor", "从微信聊天里自动扫描")],
        default_key="manual_link",
    )

    wechat_enabled = default_action == "wechat_monitor"
    monitor_mode = "manual"
    interval_seconds = 900
    chat_username = "filehelper"
    session_db = ""
    message_dir = ""
    message_table = ""
    decrypt_workdir = ""
    decrypt_python = ""
    decrypt_script = ""

    if wechat_enabled:
        wechat_entry = prompt_choice(
            "你要固定监控哪个微信入口？",
            [("filehelper", "文件传输助手（推荐）"), ("custom", "指定某个聊天对象")],
            default_key="filehelper",
        )
        if wechat_entry == "custom":
            chat_username = prompt_text("请输入要固定监控的微信会话名")
        else:
            chat_username = "filehelper"

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

        auto_detect = prompt_yes_no("要不要先自动查找这台电脑上的微信数据库和常见解密路径？", default=True)
        detected = detect_windows_wechat_paths() if auto_detect else {}
        if detected:
            print("\n已尝试自动查找：")
            for key, label in (
                ("session_db", "session.db"),
                ("message_dir", "消息数据库目录"),
                ("decrypt_workdir", "解密工具目录"),
                ("decrypt_python", "解密脚本 Python"),
                ("decrypt_script", "解密脚本"),
            ):
                print(f"- {label}：{detected.get(key) or '未找到'}")

        session_db = prompt_path(
            "请选择微信 session.db 文件（不知道可跳过）",
            default=detected.get("session_db", ""),
            kind="file",
            allow_empty=True,
        )
        message_dir = prompt_path(
            "请选择解密后的消息数据库目录（不知道可跳过）",
            default=detected.get("message_dir", ""),
            kind="dir",
            allow_empty=True,
        )
        message_table = prompt_text("消息表名（不知道可留空）", allow_empty=True)
        decrypt_workdir = prompt_path(
            "请选择解密工具目录（没有可跳过）",
            default=detected.get("decrypt_workdir", ""),
            kind="dir",
            allow_empty=True,
        )
        decrypt_python = prompt_path(
            "请选择解密脚本所用 Python（没有可跳过）",
            default=detected.get("decrypt_python", ""),
            kind="file",
            allow_empty=True,
        )
        decrypt_script = prompt_path(
            "请选择解密脚本（没有可跳过）",
            default=detected.get("decrypt_script", ""),
            kind="file",
            allow_empty=True,
        )

    return build_config(
        mode=mode,
        vault_root=vault_root,
        local_root=local_root,
        run_ocr=run_ocr,
        default_action=default_action,
        monitor_mode=monitor_mode,
        interval_seconds=interval_seconds,
        wechat_enabled=wechat_enabled,
        chat_username=chat_username,
        session_db=session_db,
        message_dir=message_dir,
        message_table=message_table,
        decrypt_workdir=decrypt_workdir,
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
        session_db=normalize_path(args.session_db) if args.session_db else "",
        message_dir=normalize_path(args.message_dir) if args.message_dir else "",
        message_table=args.message_table or "",
        decrypt_workdir=normalize_path(args.decrypt_workdir) if args.decrypt_workdir else "",
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

    if monitor_mode == "realtime":
        monitor_text = "尽量实时（15 秒轮询）"
    elif monitor_mode == "interval":
        monitor_text = f"固定间隔（约 {max(1, interval_seconds // 60)} 分钟一次）"
    else:
        monitor_text = "手动/只跑一次"

    print("\n配置摘要")
    print(f"- 保存模式：{'本地文件夹' if storage.get('mode') == 'local' else 'Obsidian'}")
    print(f"- 目标路径：{target}")
    print(f"- OCR：{'开启' if settings.get('runOcr', True) else '关闭'}")
    print(f"- 默认使用方式：{action_text}")
    print(f"- 微信入口：{wechat_entry}")
    print(f"- 扫描方式：{monitor_text}")
    print(f"- session.db：{wechat.get('session_db') or '未配置'}")
    print(f"- 消息数据库目录：{wechat.get('message_dir') or '未配置'}")
    print(f"- 解密工具目录：{wechat.get('decrypt_workdir') or '未配置'}")
    print("\n你后面最常用的启动方式：")
    print("- 双击 START-HERE.bat")
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
    parser.add_argument("--session-db")
    parser.add_argument("--message-dir")
    parser.add_argument("--message-table")
    parser.add_argument("--decrypt-workdir")
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
