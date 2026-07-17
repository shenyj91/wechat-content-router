#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sqlite3
import sys
from pathlib import Path

import zstandard as zstd


DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.json")
XHS_URL_RE = re.compile(r"https?://(?:www\.)?(?:xiaohongshu\.com|xhslink\.com)/[^\s<>\"]+")
MP_URL_RE = re.compile(r"https?://mp\.weixin\.qq\.com/[^\s<>\"]+")


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_config(config_path=None):
    path = Path(config_path or DEFAULT_CONFIG_PATH).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    config = load_json(path, {})
    config["_config_path"] = str(path.resolve())
    return config


def load_importer(module_name: str, script_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def decompress_content(content, ct):
    if content is None:
        return ""
    if isinstance(content, bytes) and ct == 4:
        return zstd.ZstdDecompressor().decompress(content).decode("utf-8", errors="replace")
    if isinstance(content, bytes):
        return content.decode("utf-8", errors="replace")
    return str(content)


def detect_message_type(text: str) -> tuple[str, str]:
    for link_type, pattern in (("xhs", XHS_URL_RE), ("mp", MP_URL_RE)):
        match = pattern.search(text or "")
        if match:
            return link_type, match.group(0).replace("&amp;", "&")
    return "", ""


def message_key(item: dict) -> str:
    return f'{item["create_time"]}:{item["local_id"]}:{item["url"]}'


def normalize_state(state: dict) -> dict[str, list[str]]:
    processed = state.get("processed_messages")
    if isinstance(processed, list):
        return {"processed_messages": processed}
    return {"processed_messages": []}


def collect_recent_messages(config: dict, limit_per_db: int = 50) -> list[dict]:
    wechat = config.get("wechat") or {}
    session_db = Path(wechat["session_db"])
    message_dir = Path(wechat["message_dir"])
    username = wechat["chat_username"]
    table_name = wechat.get("message_table") or f"Msg_{hashlib.md5(username.encode()).hexdigest()}"

    session_conn = sqlite3.connect(session_db)
    try:
        session_row = session_conn.execute(
            "select last_timestamp from SessionTable where username = ?",
            (username,),
        ).fetchone()
    finally:
        session_conn.close()
    if not session_row:
        raise RuntimeError(f"Chat not found: {username}")
    last_timestamp = int(session_row[0])

    candidates = []
    for db_path in sorted(message_dir.glob("message_*.db")):
        if db_path.name == "message_fts.db":
            continue
        conn = sqlite3.connect(db_path)
        try:
            exists = conn.execute(
                "select name from sqlite_master where type='table' and name=?",
                (table_name,),
            ).fetchone()
            if not exists:
                continue
            rows = conn.execute(
                f"""
                select local_id, create_time, local_type, message_content, WCDB_CT_message_content
                from {table_name}
                where create_time <= ?
                order by create_time desc, local_id desc
                limit ?
                """,
                (last_timestamp, limit_per_db),
            ).fetchall()
            for local_id, create_time, local_type, message_content, ct in rows:
                text = decompress_content(message_content, ct)
                link_type, url = detect_message_type(text)
                if not url:
                    continue
                candidates.append({
                    "db_path": str(db_path),
                    "local_id": local_id,
                    "create_time": create_time,
                    "local_type": local_type,
                    "raw_text": text,
                    "type": link_type,
                    "url": url,
                })
        finally:
            conn.close()

    unique_items = {}
    for item in candidates:
        unique_items[message_key(item)] = item
    return sorted(unique_items.values(), key=lambda item: (item["create_time"], item["local_id"]))


def main():
    config = load_config()
    wechat = config.get("wechat") or {}
    if not wechat.get("enabled"):
        raise RuntimeError("WeChat mode is disabled in config")

    state_path = Path(config.get("state_file") or (Path(config["vault_root"]) / ".wechat-content-router-state.json"))
    state = normalize_state(load_json(state_path, {}))
    processed_keys = set(state["processed_messages"])

    recent_messages = collect_recent_messages(config)
    xhs_importer = load_importer("wechat_router_xhs", Path(__file__).with_name("import_xhs_note.py"))
    mp_importer = load_importer("wechat_router_mp", Path(__file__).with_name("import_wechat_mp_article.py"))

    imports = []
    for item in recent_messages:
        key = message_key(item)
        if key in processed_keys:
            continue

        if item["type"] == "xhs":
            result = xhs_importer.import_note(item["raw_text"], config=config, overwrite=True)
        elif item["type"] == "mp":
            result = mp_importer.import_article(item["url"], config=config, overwrite=True)
        else:
            continue

        imports.append({
            "type": item["type"],
            "wechat_message": {
                "db_path": item["db_path"],
                "local_id": item["local_id"],
                "create_time": item["create_time"],
                "url": item["url"],
            },
            "import_result": result,
        })
        processed_keys.add(key)

    save_json(state_path, {"processed_messages": sorted(processed_keys)})
    print(json.dumps({
        "status": "imported" if imports else "no_new_links",
        "count": len(imports),
        "imports": imports,
        "state_file": str(state_path),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
