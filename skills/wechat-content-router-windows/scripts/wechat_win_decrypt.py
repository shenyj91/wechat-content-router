#!/usr/bin/env python3
"""
Windows 微信 4.x 解密与导入辅助模块。

默认走纯 Python 的 WCDB 解密路径；旧的 live_wcdb 桥接仍保留给实验模式。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import importlib.util
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BRIDGE_SCRIPT = SCRIPT_DIR / "wechat_bridge.mjs"

XHS_RE = re.compile(r"https?://(?:www\.)?(?:xiaohongshu\.com|xhslink\.com)/[^\s<>\"]+")
MP_RE = re.compile(r"https?://mp\.weixin\.qq\.com/[^\s<>\"]+")
FEISHU_RE = re.compile(r"https?://(?:[\w-]+\.)?feishu\.cn/(?:wiki|docx)/[^\s<>\"]+")


def _run_bridge(command: str, *args: str, timeout: int = 60) -> dict:
    """调用Node.js桥接脚本"""
    node_cmd = os.environ.get("NODEJS_PATH") or "node"
    cmd = [node_cmd, str(BRIDGE_SCRIPT), command, *args]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(SCRIPT_DIR),
    )

    stdout = result.stdout.strip()
    json_lines = [line for line in stdout.splitlines() if line.strip().startswith("{")]
    if not json_lines:
        raise RuntimeError(
            f"Bridge返回无效输出:\nstdout: {result.stdout[:500]}\nstderr: {result.stderr[:500]}"
        )

    data = json.loads(json_lines[-1])
    if not data.get("success"):
        raise RuntimeError(f"Bridge错误: {data.get('error', '未知错误')}")
    return data


def _load_wcdb_decrypt_module():
    spec = importlib.util.spec_from_file_location("wechat_wcdb_decrypt", SCRIPT_DIR / "wcdb_decrypt.py")
    if not spec or not spec.loader:
        raise RuntimeError("无法加载 wcdb_decrypt.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _resolve_account_root(account_dir: str) -> Path:
    root = Path(account_dir).expanduser().resolve()
    db_storage = root / "db_storage"
    if db_storage.exists():
        return root
    if root.name.lower() == "db_storage" and root.parent.exists():
        return root.parent.resolve()
    raise RuntimeError(f"未找到 db_storage: {root}")


def decrypt_account_dbs(account_dir: str, hex_key: str, output_root: str | None = None, clean: bool = True) -> dict:
    """把账号目录下的 WCDB 数据库解密到一个本地缓存目录。"""
    account_root = _resolve_account_root(account_dir)
    db_storage = account_root / "db_storage"
    if not db_storage.exists():
        raise RuntimeError(f"db_storage不存在: {db_storage}")

    decrypt_mod = _load_wcdb_decrypt_module()

    decrypted_root = Path(output_root).expanduser().resolve() if output_root else (account_root / "_decrypted")
    if clean and decrypted_root.exists():
        shutil.rmtree(decrypted_root, ignore_errors=True)
    decrypted_root.mkdir(parents=True, exist_ok=True)

    count = 0
    for db_file in sorted(db_storage.rglob("*.db")):
        rel = db_file.relative_to(db_storage)
        out_path = decrypted_root / rel
        try:
            decrypt_mod.decrypt_db(str(db_file), str(out_path), hex_key)
            count += 1
        except Exception as e:
            print(f"跳过 {rel}: {e}")

    session_db = decrypted_root / "session" / "session.db"
    message_dir = decrypted_root / "message"
    return {
        "account_root": str(account_root),
        "db_storage": str(db_storage),
        "decrypted_root": str(decrypted_root),
        "session_db": str(session_db) if session_db.exists() else "",
        "message_dir": str(message_dir) if message_dir.exists() else "",
        "decrypted_count": count,
    }


def _load_collect_recent_messages():
    importer = importlib.util.spec_from_file_location(
        "wechat_router_local_links",
        SCRIPT_DIR / "import_latest_wechat_links.py",
    )
    if not importer or not importer.loader:
        raise RuntimeError("无法加载 import_latest_wechat_links.py")
    module = importlib.util.module_from_spec(importer)
    sys.modules[importer.name] = module
    importer.loader.exec_module(module)
    return module


def _load_contact_names(decrypted_root: Path) -> dict:
    """从解密后的 contact.db 读取 username -> 显示名（remark > nick_name > alias）。"""
    for root, _, files in os.walk(decrypted_root):
        for fn in files:
            if not fn.lower().endswith(".db"):
                continue
            p = os.path.join(root, fn)
            try:
                con = sqlite3.connect(p)
                try:
                    tbl = con.execute(
                        "select name from sqlite_master where type='table' and name in ('Contact','Friend')"
                    ).fetchone()
                    if not tbl:
                        continue
                    t = tbl[0]
                    cols = [r[1] for r in con.execute(f"pragma table_info('{t}')")]
                    need = {"username", "remark", "nick_name", "alias"} & set(cols)
                    if "username" not in need:
                        continue
                    sel = ", ".join(need)
                    out = {}
                    for row in con.execute(f"select {sel} from {t}"):
                        d = dict(zip(need, row))
                        u = d.get("username")
                        if not u:
                            continue
                        name = (d.get("remark") or d.get("nick_name") or d.get("alias") or "").strip()
                        out[u] = name or u
                    return out
                finally:
                    con.close()
            except Exception:
                continue
    return {}


def list_sessions_from_decrypted_files(account_dir: str, hex_key: str, output_root: str | None = None) -> list[dict]:
    """从解密后的 session.db 里列出会话（纯 Python，不依赖崩溃 DLL）。"""
    decrypted = decrypt_account_dbs(account_dir, hex_key, output_root=output_root)
    decrypted_root = Path(decrypted.get("decrypted_root") or "")
    session_db = decrypted.get("session_db")
    if not session_db or not decrypted_root.exists():
        return []

    session_path = Path(session_db)
    conn = sqlite3.connect(session_path)
    try:
        cols = [r[1] for r in conn.execute("pragma table_info(SessionTable)")]
        have = set(cols)
        order = "last_timestamp" if "last_timestamp" in have else "rowid"
        rows = conn.execute(
            f"select username, last_timestamp from SessionTable order by {order} desc"
        ).fetchall()
    finally:
        conn.close()

    sessions = []
    for username, last_timestamp in rows:
        username = str(username or "").strip()
        if not username:
            continue
        sessions.append(
            {
                "session_id": username,
                "display_name": username,
                "is_group": username.endswith("@chatroom"),
                "raw": {
                    "username": username,
                    "last_timestamp": int(last_timestamp or 0),
                },
            }
        )

    contacts = _load_contact_names(decrypted_root)
    for s in sessions:
        u = s["session_id"]
        if not u.endswith("@chatroom") and not u.startswith("gh_") and contacts.get(u):
            s["display_name"] = contacts[u]
    return sessions


def list_all_accounts() -> list[dict]:
    """
    列出所有微信4.x账号目录
    返回: [{account_dir, wxid, mtime}]
    """
    data = _run_bridge("find_account_dir", timeout=10)
    all_accounts = data.get("allAccounts", [])
    if not all_accounts:
        all_accounts = [data["accountDir"]]

    accounts = []
    for acc_dir in all_accounts:
        p = Path(acc_dir)
        wxid = p.name
        # 去掉wxid后面的随机后缀 _xxxx
        wxid_clean = re.sub(r"_[a-zA-Z0-9]{4}$", "", wxid)
        try:
            mtime = p.stat().st_mtime
        except Exception:
            mtime = 0
        accounts.append({
            "account_dir": str(p),
            "wxid": wxid_clean,
            "raw_name": wxid,
            "mtime": mtime,
        })

    # 按修改时间倒序（最近使用的在前）
    accounts.sort(key=lambda a: a["mtime"], reverse=True)
    return accounts


def extract_wechat_key(timeout: int = 30) -> str:
    """从微信进程提取密钥（需要管理员权限）"""
    print("正在从微信进程提取密钥（需要管理员权限）...")
    data = _run_bridge("extract_key", timeout=timeout + 10)
    key = data.get("key", "")
    if not key or len(key) != 64:
        raise RuntimeError(f"提取到的密钥格式不对: {key}")
    print(f"密钥提取成功: {key[:8]}...")
    return key


def load_key_from_file(path) -> str:
    """从文件读取 64 位十六进制密钥（兼容多种格式）：
    - 纯 64hex
    - x'64hex'（WeChat 内存 / DbkeyHook 常见格式）
    - 含 key 字段的 JSON（key-extractor.js 的 status.json）
    - dbkey.txt（DbkeyHook 写出的文本）
    这样即使自动提取（wx_key.dll）失败，也可以手动把密钥贴进来继续。
    """
    p = Path(path).expanduser()
    if not p.exists():
        raise RuntimeError(f"密钥文件不存在: {p}")
    txt = p.read_text(encoding="utf-8", errors="replace").strip()
    m = re.search(r"x'([0-9a-fA-F]{64})'", txt)
    if m:
        return m.group(1)
    m = re.search(r"([0-9a-fA-F]{64})", txt)
    if m:
        return m.group(1)
    try:
        obj = json.loads(txt)
        if isinstance(obj, dict) and obj.get("key"):
            return str(obj["key"]).strip()
    except Exception:
        pass
    raise RuntimeError(f"密钥文件中未找到 64 位十六进制密钥: {p}")


def ensure_wechat_running() -> dict:
    """确保微信已启动；未启动则自动拉起"""
    data = _run_bridge("ensure_wechat_running", timeout=15)
    return data


def find_account_dir() -> tuple[str, list[str]]:
    """自动找微信4.x账号目录（兼容旧代码）"""
    data = _run_bridge("find_account_dir", timeout=10)
    return data["accountDir"], data.get("allAccounts", [])


def get_sessions(account_dir: str, hex_key: str) -> list[dict]:
    """获取所有会话列表"""
    data = _run_bridge("get_sessions", account_dir, hex_key, timeout=30)
    return data.get("sessions", [])


def list_sessions_with_info(account_dir: str, hex_key: str) -> list[dict]:
    """获取会话列表，并归一化成启动器可直接展示的结构（纯 Python 解密，不依赖崩溃 DLL）"""
    sessions = list_sessions_from_decrypted_files(account_dir, hex_key)
    normalized = []
    for item in sessions:
        session_id = (
            item.get("session_id")
            or item.get("sessionId")
            or item.get("userName")
            or item.get("username")
            or item.get("talker")
            or ""
        )
        if not session_id:
            continue
        display_name = (
            item.get("display_name")
            or item.get("displayName")
            or item.get("nickname")
            or item.get("remark")
            or item.get("name")
            or session_id
        )
        is_group = bool(
            item.get("is_group")
            or item.get("isGroup")
            or str(session_id).endswith("@chatroom")
        )
        normalized.append(
            {
                "session_id": session_id,
                "display_name": display_name,
                "is_group": is_group,
                "raw": item,
            }
        )
    return normalized


def get_messages(
    account_dir: str,
    hex_key: str,
    session_id: str,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """获取某会话的消息"""
    data = _run_bridge(
        "get_messages",
        account_dir,
        hex_key,
        session_id,
        str(limit),
        str(offset),
        timeout=30,
    )
    return data.get("messages", [])


def get_recent_links(
    account_dir: str,
    hex_key: str,
    session_id: str = "filehelper",
    limit: int = 50,
) -> list[dict]:
    """从指定会话提取最近消息里的链接"""
    messages = get_messages(account_dir, hex_key, session_id, limit)
    results = []

    for msg in messages:
        content = msg.get("content") or msg.get("message") or ""
        if not content:
            continue
        for link_type, pattern in (("xhs", XHS_RE), ("mp", MP_RE), ("feishu", FEISHU_RE)):
            match = pattern.search(content)
            if match:
                results.append({
                    "type": link_type,
                    "url": match.group(0).replace("&amp;", "&"),
                    "raw_text": content,
                    "create_time": msg.get("createTime") or msg.get("create_time") or 0,
                    "local_id": msg.get("localId") or msg.get("local_id") or 0,
                })
                break

    return results


def decrypt_and_get_links(
    session_id: str = "filehelper",
    limit: int = 50,
    key: str | None = None,
    account_dir: str | None = None,
    output_root: str | None = None,
) -> dict:
    """一键完成：账号目录 → 提取密钥 → 解密数据库 → 读取链接"""
    if not account_dir:
        raise RuntimeError(
            "未指定account_dir。请先运行 use_router.py 完成账号选择配置。"
        )

    ensure_wechat_running()

    if not key:
        key = extract_wechat_key()

    print("正在解密微信数据库...")
    decrypted = decrypt_account_dbs(account_dir, key, output_root=output_root)
    temp_config = {
        "state_file": "",
        "wechat": {
            "session_db": decrypted.get("session_db") or "",
            "message_dir": decrypted.get("message_dir") or "",
            "chat_username": session_id,
        },
    }
    if not temp_config["wechat"]["session_db"] or not temp_config["wechat"]["message_dir"]:
        raise RuntimeError("解密后的 session.db 或 message_*.db 目录不存在")

    print(f"正在读取会话 [{session_id}] 的最近消息...")
    collect_module = _load_collect_recent_messages()
    links = collect_module.collect_recent_messages(temp_config)
    print(f"找到 {len(links)} 条链接")

    return {
        "account_dir": account_dir,
        "key": key,
        "session_id": session_id,
        "links": links,
        "decrypted_root": decrypted.get("decrypted_root") or "",
        "session_db": decrypted.get("session_db") or "",
        "message_dir": decrypted.get("message_dir") or "",
    }


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--list-accounts", action="store_true", help="列出所有账号")
    parser.add_argument("--session", default="filehelper")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--key")
    parser.add_argument("--account-dir")
    args = parser.parse_args()

    try:
        if args.list_accounts:
            accounts = list_all_accounts()
            print(json.dumps(accounts, ensure_ascii=False, indent=2))
            return

        result = decrypt_and_get_links(
            session_id=args.session,
            limit=args.limit,
            key=args.key,
            account_dir=args.account_dir,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()


def decrypt_all_dbs(account_dir: str, hex_key: str) -> str:
    """批量解密账号目录下所有db，返回解密后目录"""
    from wcdb_decrypt import decrypt_db
    import os
    
    db_storage = Path(account_dir) / "db_storage"
    if not db_storage.exists():
        raise RuntimeError(f"db_storage不存在: {db_storage}")
    
    output_dir = Path(account_dir) / "_decrypted"
    output_dir.mkdir(exist_ok=True)
    
    count = 0
    for db_file in db_storage.rglob("*.db"):
        rel = db_file.relative_to(db_storage)
        out_path = output_dir / rel
        try:
            decrypt_db(str(db_file), str(out_path), hex_key)
            count += 1
        except Exception as e:
            print(f"跳过 {rel}: {e}")
    
    print(f"解密完成: {count}个db文件 → {output_dir}")
    return str(output_dir)
