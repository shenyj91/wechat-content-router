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


def load_cached_key_file() -> str | None:
    """DLL 提取失败时的降级：从本地密钥文件读取 64hex 密钥。

    适用场景：内置 wx_key.dll 因微信版本/内存布局变化（如 4.1.4+ 改了
    WCDB 设密钥函数结构）导致 hook 特征码不匹配、永远轮不到 key 时，可改用
    任意维护中的第三方提取器（wx_key / chatlog_alpha / pc_wechat_exp 等）
    把 64hex 抓出来写进下面任一处，pipeline 自动回退读取，不再卡死。

    候选文件（按优先级）：
      - <SCRIPT_DIR>/wechat_key.txt      （推荐：用户粘贴或第三方工具写出）
      - <SCRIPT_DIR>/wechat_key.json     （{"key": "64hex"}）
      - <SCRIPT_DIR>/key.tmp             （wx_key 系列工具默认写出的 key.tmp）
    格式兼容 load_key_from_file：纯 64hex / x'64hex' / JSON{key} / dbkey.txt。
    """
    candidates = [
        SCRIPT_DIR / "wechat_key.txt",
        SCRIPT_DIR / "wechat_key.json",
        SCRIPT_DIR / "key.tmp",
    ]
    for p in candidates:
        if p.exists():
            try:
                return load_key_from_file(p)
            except Exception as e:
                print(f"[fallback] 读取 {p.name} 失败: {e}")
                continue
    return None


def extract_wechat_key(timeout: int = 30, allow_file_fallback: bool = True) -> str:
    """从微信进程提取密钥（需要管理员权限）。

    若 DLL 注入提取失败（常见于微信版本/内存布局变化导致 hook 找不到特征码），
    自动回退到本地密钥文件 wechat_key.txt / wechat_key.json / key.tmp
    （可由任意第三方提取器写出）。这样即使内置 wx_key.dll 过时，也能用
    外部维护的提取器拿到密钥后无缝继续。
    """
    print("正在从微信进程提取密钥（需要管理员权限）...")
    try:
        data = _run_bridge("extract_key", timeout=timeout + 10)
        key = data.get("key", "")
        if not key or len(key) != 64:
            raise RuntimeError(f"提取到的密钥格式不对: {key}")
        print(f"密钥提取成功: {key[:8]}...")
        return key
    except Exception as e:
        if allow_file_fallback:
            fb = load_cached_key_file()
            if fb:
                print(f"[fallback] DLL 提取失败（{e}），改用本地密钥文件: {fb[:8]}...")
                return fb
        raise


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
