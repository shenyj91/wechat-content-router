#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
decrypt_wechat_db.py
────────────────────────────────────────────────────────────────────────────
macOS 一键解密桥的「落库」环节（Python 侧）。

职责：
  1. 调用 Node 取数脚本 decrypt_fetch.mjs（复用 WxLens 的 xkey_helper + libwcdb_api，
     不碰任何解密算法）拿到指定聊天（默认 filehelper）的明文消息 JSON；
  2. 用内置 sqlite3 把消息写成「扫描器期望的解密库」：
       - <message_dir>/session.db        : SessionTable(username, last_timestamp)
       - <message_dir>/message_0.db      : Msg_<md5(username)>(local_id, create_time,
                                            local_type, message_content BLOB,
                                            WCDB_CT_message_content=0)
     写入采用 INSERT OR REPLACE（按 local_id），天然幂等、不丢历史消息。

配置（config.json 的 wechat.*）：
  message_dir   : 解密库输出目录（必填）
  chat_username : 目标聊天（默认 filehelper，决定表名与 SessionTable 行）
  account_dir   : 可选，强制指定微信账号目录
  node_bin      : 可选，node 可执行文件路径（默认用 PATH 中的 node）

用法：
  python3 decrypt_wechat_db.py [--config PATH] [--incremental]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = SCRIPT_DIR / "config.json"
FETCH_SCRIPT = SCRIPT_DIR / "decrypt_fetch.mjs"


def load_config(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def find_node(node_bin: str | None) -> str:
    if node_bin:
        candidate = shutil.which(node_bin) or node_bin
        if Path(candidate).exists():
            return candidate
    found = shutil.which("node")
    if found:
        return found
    raise RuntimeError(
        "未找到 node 可执行文件。请在 PATH 中安装 Node.js，或在 config.wechat.node_bin 指定路径。"
    )


def extract_json(stdout: str) -> dict:
    """从 Node stdout 中稳健地取出 JSON 对象（容忍零星非 JSON 输出）。"""
    s = stdout.strip()
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Node 输出中未找到 JSON")
    return json.loads(s[start : end + 1])


def fetch_messages(config_path: Path, wechat: dict, incremental: bool) -> dict:
    node = find_node(wechat.get("node_bin"))
    message_dir = Path(wechat["message_dir"]).expanduser()
    key_file = message_dir / ".wcr_key"

    cmd = [node, str(FETCH_SCRIPT), "--config", str(config_path), "--key-file", str(key_file)]
    if wechat.get("chat_username"):
        cmd += ["--username", wechat["chat_username"]]
    if wechat.get("account_dir"):
        cmd += ["--account-dir", str(Path(wechat["account_dir"]).expanduser())]
    if incremental:
        cmd.append("--incremental")

    print(f"[decrypt] 运行取数: {' '.join(cmd)}", file=sys.stderr)
    result = subprocess.run(cmd, cwd=str(SCRIPT_DIR), capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[decrypt] 取数失败 (exit={result.returncode})", file=sys.stderr)
        if result.stderr.strip():
            print(result.stderr.strip(), file=sys.stderr)
        sys.exit(1)
    if result.stderr.strip():
        # 进度日志打到 stderr，仅作信息
        for line in result.stderr.strip().splitlines():
            print(f"[fetch] {line}", file=sys.stderr)
    return extract_json(result.stdout)


def write_decrypted_db(message_dir: Path, username: str, messages: list[dict]) -> tuple[Path, Path]:
    message_dir = Path(message_dir).expanduser()
    message_dir.mkdir(parents=True, exist_ok=True)

    table = f"Msg_{hashlib.md5(username.encode('utf-8')).hexdigest()}"
    session_db = message_dir / "session.db"
    msg_db = message_dir / "message_0.db"

    # session.db
    sconn = sqlite3.connect(session_db)
    try:
        sconn.execute(
            "CREATE TABLE IF NOT EXISTS SessionTable "
            "(username TEXT PRIMARY KEY, last_timestamp INTEGER)"
        )
        max_ts = max((int(m.get("create_time", 0)) for m in messages), default=0)
        sconn.execute(
            "INSERT OR REPLACE INTO SessionTable (username, last_timestamp) VALUES (?, ?)",
            (username, max_ts),
        )
        sconn.commit()
    finally:
        sconn.close()

    # message_0.db
    mconn = sqlite3.connect(msg_db)
    try:
        mconn.execute(
            f"CREATE TABLE IF NOT EXISTS {table} ("
            "local_id INTEGER PRIMARY KEY, create_time INTEGER, local_type INTEGER, "
            "message_content BLOB, WCDB_CT_message_content INTEGER)"
        )
        written = 0
        for m in messages:
            content = m.get("content") or ""
            if not isinstance(content, str):
                content = str(content)
            blob = content.encode("utf-8")
            mconn.execute(
                f"INSERT OR REPLACE INTO {table} "
                "(local_id, create_time, local_type, message_content, WCDB_CT_message_content) "
                "VALUES (?, ?, ?, ?, 0)",
                (
                    int(m.get("local_id", 0)),
                    int(m.get("create_time", 0)),
                    int(m.get("local_type", 0)),
                    blob,
                ),
            )
            written += 1
        mconn.commit()
    finally:
        mconn.close()

    return session_db, msg_db, written


def main() -> None:
    parser = argparse.ArgumentParser(description="macOS 一键解密桥：取数并落库")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="config.json 路径")
    parser.add_argument("--incremental", action="store_true", help="增量模式（复用缓存密钥）")
    args = parser.parse_args()

    config_path = Path(args.config).expanduser()
    config = load_config(config_path)
    wechat = config.get("wechat") or {}
    if not wechat.get("enabled"):
        print(json.dumps({"status": "wechat_disabled"}, ensure_ascii=False, indent=2))
        return
    if not wechat.get("message_dir"):
        print(f"ERROR: config.wechat.message_dir 未配置", file=sys.stderr)
        sys.exit(1)

    data = fetch_messages(config_path, wechat, args.incremental)
    username = data.get("username") or wechat.get("chat_username") or "filehelper"
    messages = data.get("messages", [])

    session_db, msg_db, written = write_decrypted_db(
        Path(wechat["message_dir"]).expanduser(), username, messages
    )

    print(
        json.dumps(
            {
                "status": "decrypted",
                "username": username,
                "message_count": len(messages),
                "written": written,
                "session_db": str(session_db),
                "message_db": str(msg_db),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
