#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
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
        vault_root = normalize_path(prompt_text("请输入 Obsidian vault 路径"))
    else:
        local_root = normalize_path(prompt_text("请输入本地保存目录", default="~/Documents/ImportedContent"))

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

        session_db = normalize_path(prompt_text("微信 session.db 路径", allow_empty=True))
        message_dir = normalize_path(prompt_text("微信解密后的消息数据库目录", allow_empty=True))
        message_table = prompt_text("消息表名（不知道可先留空）", allow_empty=True)
        decrypt_workdir = normalize_path(prompt_text("微信解密工具目录（可留空）", allow_empty=True))
        decrypt_python = normalize_path(prompt_text("解密脚本 Python 路径（可留空）", allow_empty=True))
        decrypt_script = normalize_path(prompt_text("解密脚本路径（可留空）", allow_empty=True))

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
    print(f"当前保存模式：{config['storage']['mode']}")
    print(f"当前默认使用方式：{config['workflow']['default_action']}")


if __name__ == "__main__":
    main()
