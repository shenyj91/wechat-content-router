#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
viewer_query.py — 微信只读查看器后端（纯 Python，零原生依赖，不碰崩溃 DLL）

这是 WxLens `wcdb_api.dll` / `WCDB.dll` 的**纯 Python 替代品**，用于查看器
（viewer-server.mjs）的「解密 + 查询」环节。

  * 解密：复用 wcdb_decrypt.py（SQLCipher 4 / WCDB 页面解密，已对照
    Tencent/sqlcipher 源码核实参数）。
  * 查询：直接读解密后的 SQLite，按微信 4.x 真实 schema 取会话 / 消息 / 搜索。

微信 4.x 真实 schema（来自社区逆向 wechat-dump-rs / chatlog / 52pojie）：
  * session.db  → SessionTable(username PK, unread_count, last_timestamp,
                  sort_timestamp, last_msg_sender, last_sender_display_name, summary, ...)
  * message_*.db → Msg_<md5(talker)>(local_id, server_id, local_type, sort_seq,
                  real_sender_id, create_time, status, message_content,
                  WCDB_CT_message_content, packed_info_data, ...)
                  WCDB_CT_message_content == 4 表示 message_content 经 zstd 压缩
  * 发送者解析：real_sender_id → Name2Id(rowid) → user_name
  * 联系人显示名：contact.db → Contact(username, alias, remark, nick_name, ...)

密钥来源（与自动扫描一致）：
  * 自动提取：key-extractor.js（独立 wx_key.dll，hook 微信进程）拿到 64hex
  * 手动：查看器页面粘贴 64hex，或 config 里的 key_file

子命令
------
  decrypt   --account-dir D --key HEX --cache-dir C
  sessions  --cache-dir C --self WXID [--kind all|private|group]
  messages  --cache-dir C --self WXID --session-id S [--limit N] [--offset N]
  search    --cache-dir C --self WXID --keyword KW [--session-id S] [--limit N]
  display-names --cache-dir C --ids a,b,c
  contact   --cache-dir C --username U

仅用于处理**你自己**的微信数据。

注意：解密需要 `cryptography`；消息解压需要 `zstandard`（缺失时跳过解压，
返回原始字节文本，不影响会话/消息列表展示）。
"""
import sys
import os
import json
import sqlite3
import hashlib
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wcdb_decrypt import decrypt_wcdb

try:
    import zstandard
    _ZSTD = zstandard.ZstdDecompressor()
except Exception:
    zstandard = None
    _ZSTD = None


# 这些库通常不需要解密（或解密后无 SQLite 结构）；跳过可省时间
SKIP_NAMES = {"fts_db", "fts", "index", "session_large"}


# ────────────────────────────────────────────────────
# 解密
# ────────────────────────────────────────────────────
def find_db_storage(in_path):
    """输入可能是 account 目录（含 db_storage 子目录）或直接是 db_storage。"""
    if os.path.isfile(in_path):
        return None
    cand = os.path.join(in_path, "db_storage")
    if os.path.isdir(cand):
        return cand
    return in_path


def cmd_decrypt(account_dir, key_hex, cache_dir):
    key_bytes = bytes.fromhex(key_hex)
    if len(key_bytes) != 32:
        print(json.dumps({"success": False, "error": f"密钥长度应为 32 字节（64 hex），实际 {len(key_bytes)}"}))
        return 2

    storage = find_db_storage(account_dir)
    if storage is None or not os.path.isdir(storage):
        print(json.dumps({"success": False, "error": "找不到 db_storage 目录"}))
        return 2

    os.makedirs(cache_dir, exist_ok=True)
    decrypted = failed = skipped = 0
    for root, _, files in os.walk(storage):
        for fn in sorted(files):
            if not fn.lower().endswith(".db"):
                continue
            base = fn[:-3].lower()
            if base in SKIP_NAMES or base.endswith("_fts"):
                skipped += 1
                continue
            src = os.path.join(root, fn)
            rel = os.path.relpath(src, storage)
            dst = os.path.join(cache_dir, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            try:
                with open(src, "rb") as f:
                    data = f.read()
                plain, cfg = decrypt_wcdb(data, key_bytes)
            except Exception as e:
                sys.stderr.write(f"[FAIL] {rel}: 读取/解密异常 {e}\n")
                failed += 1
                continue
            if plain is None:
                sys.stderr.write(f"[FAIL] {rel}: 所有候选参数均失败\n")
                failed += 1
                continue
            with open(dst, "wb") as f:
                f.write(plain)
            decrypted += 1
            sys.stderr.write(f"[OK] {rel}  raw_key={cfg['raw_key']} "
                             f"{cfg['kdf_algorithm']}/{cfg['hmac_algorithm']} "
                             f"pgno={cfg['hmac_pgno']}\n")

    sys.stderr.write(f"\n解密完成: 成功 {decrypted}，失败 {failed}，跳过 {skipped}\n")
    out = {"success": failed == 0, "decrypted": decrypted, "failed": failed,
           "skipped": skipped, "cache_dir": cache_dir}
    if failed:
        out["error"] = f"{failed} 个库解密失败（密钥或加密参数不匹配）"
    print(json.dumps(out))
    return 0 if failed == 0 else 1


# ────────────────────────────────────────────────────
# 查询辅助
# ────────────────────────────────────────────────────
def iter_cache_dbs(cache_dir):
    for root, _, files in os.walk(cache_dir):
        for fn in files:
            if not fn.lower().endswith(".db"):
                continue
            base = fn[:-3].lower()
            if base in SKIP_NAMES or base.endswith("_fts"):
                continue
            yield os.path.join(root, fn)


def db_has_table(path, table):
    try:
        con = sqlite3.connect(path)
        try:
            row = con.execute(
                "select 1 from sqlite_master where type in ('table','view') and name=?",
                (table,),
            ).fetchone()
            return row is not None
        finally:
            con.close()
    except Exception:
        return False


def find_table_db(cache_dir, table):
    for p in iter_cache_dbs(cache_dir):
        if db_has_table(p, table):
            return p
    return None


def _decompress(content, ct):
    if content is None:
        return ""
    if isinstance(content, bytes):
        if ct == 4 and _ZSTD is not None:
            try:
                return _ZSTD.decompress(content).decode("utf-8", errors="replace")
            except Exception:
                pass
        return content.decode("utf-8", "replace")
    return str(content)


def load_name2id(cache_dir):
    """Name2Id(rowid) -> user_name（发送者解析用）。"""
    n2i = {}
    for p in iter_cache_dbs(cache_dir):
        if not db_has_table(p, "Name2Id"):
            continue
        try:
            con = sqlite3.connect(p)
            try:
                for rowid, uname in con.execute("select rowid, user_name from Name2Id"):
                    if uname:
                        n2i[rowid] = uname
            finally:
                con.close()
        except Exception:
            continue
    return n2i


def load_contacts(cache_dir):
    """username -> 显示名（remark > nick_name > alias）。"""
    contacts = {}
    table_names = ("Contact", "Friend", "contact", "friend")
    contact_db = None
    for t in table_names:
        contact_db = find_table_db(cache_dir, t)
        if contact_db:
            break
    if not contact_db:
        return contacts
    try:
        con = sqlite3.connect(contact_db)
        try:
            cols = [r[1] for r in con.execute("pragma table_info('%s')" % t)]
            need = {"username", "remark", "nick_name", "alias"}
            have = need & set(cols)
            if "username" not in have:
                return contacts
            sel = ", ".join(have)
            for row in con.execute(f"select {sel} from {t}"):
                d = dict(zip(have, row))
                uname = d.get("username")
                if not uname:
                    continue
                name = (d.get("remark") or d.get("nick_name") or d.get("alias") or "").strip()
                contacts[uname] = name or uname
        finally:
            con.close()
    except Exception:
        pass
    return contacts


def _session_id_to_table(talker):
    return "Msg_" + hashlib.md5(talker.encode("utf-8")).hexdigest()


def _table_to_talker(cache_dir):
    """Msg_<md5(username)> -> username（反向映射，供跨会话搜索用）。"""
    sdb = find_table_db(cache_dir, "SessionTable")
    if not sdb:
        return {}
    out = {}
    try:
        con = sqlite3.connect(sdb)
        try:
            for (username,) in con.execute("select username from SessionTable"):
                if username:
                    out[_session_id_to_table(username)] = username
        finally:
            con.close()
    except Exception:
        pass
    return out


# ────────────────────────────────────────────────────
# 会话列表
# ────────────────────────────────────────────────────
def cmd_sessions(cache_dir, self_wxid, kind="all"):
    sdb = find_table_db(cache_dir, "SessionTable")
    if not sdb:
        print(json.dumps({"success": True, "sessions": []}))
        return 0
    contacts = load_contacts(cache_dir)
    out = []
    try:
        con = sqlite3.connect(sdb)
        try:
            cols = [r[1] for r in con.execute("pragma table_info(SessionTable)")]
            have = set(cols)
            sel = ", ".join(
                c for c in ("username", "unread_count", "last_timestamp",
                            "sort_timestamp", "last_sender_display_name", "summary")
                if c in have
            ) or "username"
            order = "sort_timestamp" if "sort_timestamp" in have else (
                "last_timestamp" if "last_timestamp" in have else "rowid")
            rows = con.execute(f"select {sel} from SessionTable order by {order} desc").fetchall()
        finally:
            con.close()
    except Exception as e:
        print(json.dumps({"success": False, "error": f"读 SessionTable 失败: {e}"}))
        return 1

    idx = {c: i for i, c in enumerate(sel.split(", "))}
    for r in rows:
        username = r[idx["username"]]
        if not username:
            continue
        is_group = str(username).endswith("@chatroom")
        is_gh = str(username).startswith("gh_")
        if kind == "private" and (is_group or is_gh):
            continue
        if kind == "group" and not is_group:
            continue
        display = contacts.get(username) or username
        last_ts = r[idx["last_timestamp"]] if "last_timestamp" in idx else 0
        unread = r[idx["unread_count"]] if "unread_count" in idx else 0
        summary = r[idx["summary"]] if "summary" in idx else ""
        out.append({
            "username": username,
            "display_name": display,
            "last_timestamp": last_ts or 0,
            "unread_count": unread or 0,
            "summary": summary or "",
            "sessionType": "group" if is_group else "private",
        })
    print(json.dumps({"success": True, "sessions": out}))
    return 0


# ────────────────────────────────────────────────────
# 消息列表
# ────────────────────────────────────────────────────
def _collect_messages(cache_dir, session_id):
    """返回该会话所有消息原始行（跨 message_*.db 合并，未排序/未分页）。"""
    table = _session_id_to_table(session_id)
    rows = []
    for p in iter_cache_dbs(cache_dir):
        if not db_has_table(p, table):
            continue
        try:
            con = sqlite3.connect(p)
            try:
                cols = [r[1] for r in con.execute(f"pragma table_info('{table}')")]
                have = set(cols)
                need = ("local_id", "server_id", "local_type", "real_sender_id",
                        "create_time", "message_content", "WCDB_CT_message_content",
                        "packed_info_data", "status")
                pick = [c for c in need if c in have]
                sel = ", ".join(pick)
                for row in con.execute(f"select {sel} from {table}"):
                    rows.append(dict(zip(pick, row)))
            finally:
                con.close()
        except Exception:
            continue
    return rows


def _build_message(row, self_wxid, name2id, contacts):
    ct = row.get("WCDB_CT_message_content") or 0
    content = _decompress(row.get("message_content"), ct)
    real_sender = row.get("real_sender_id") or 0
    sender_username = name2id.get(real_sender)

    is_send = 0
    if sender_username == self_wxid:
        is_send = 1
        sender_name = "我"
    elif sender_username:
        sender_name = contacts.get(sender_username) or sender_username
    else:
        # 1:1 私聊：real_sender_id 无映射时，按对方处理
        sender_name = contacts.get(row.get("_session_id")) or row.get("_session_id") or ""

    return {
        "localId": row.get("local_id") or 0,
        "serverId": str(row.get("server_id") or ""),
        "type": row.get("local_type") or 0,
        "createTime": row.get("create_time") or 0,
        "content": content,
        "isSend": is_send,
        "sender": sender_name,
        "senderId": sender_username or "",
        "sessionId": row.get("_session_id") or "",
    }


def cmd_messages(cache_dir, self_wxid, session_id, limit=50, offset=0):
    raw = _collect_messages(cache_dir, session_id)
    for r in raw:
        r["_session_id"] = session_id
    # 排序：create_time 降序，local_id 降序（最新在前）
    raw.sort(key=lambda r: (r.get("create_time") or 0, r.get("local_id") or 0), reverse=True)

    name2id = load_name2id(cache_dir)
    contacts = load_contacts(cache_dir)

    page = raw[offset: offset + limit]
    msgs = [_build_message(r, self_wxid, name2id, contacts) for r in page]
    print(json.dumps({
        "success": True,
        "messages": msgs,
        "total": len(raw),
        "limit": limit,
        "offset": offset,
    }))
    return 0


# ────────────────────────────────────────────────────
# 搜索
# ────────────────────────────────────────────────────
def cmd_search(cache_dir, self_wxid, keyword, session_id=None, limit=30):
    kw = (keyword or "").lower()
    name2id = load_name2id(cache_dir)
    contacts = load_contacts(cache_dir)
    table_to_talker = _table_to_talker(cache_dir)
    hits = []
    for p in iter_cache_dbs(cache_dir):
        # 遍历所有 Msg_ 表
        try:
            con = sqlite3.connect(p)
            try:
                tables = [r[0] for r in con.execute(
                    "select name from sqlite_master where type='table' and name like 'Msg_%'")]
            finally:
                con.close()
        except Exception:
            continue
        for table in tables:
            # 若限定了会话，跳过不匹配的表
            if session_id and table != _session_id_to_table(session_id):
                continue
            try:
                con = sqlite3.connect(p)
                try:
                    cols = [r[1] for r in con.execute(f"pragma table_info('{table}')")]
                    have = set(cols)
                    need = ("local_id", "server_id", "local_type", "real_sender_id",
                            "create_time", "message_content", "WCDB_CT_message_content")
                    pick = [c for c in need if c in have]
                    if "create_time" not in have:
                        continue
                    talker = table_to_talker.get(table) or (session_id if session_id else table)
                    for row in con.execute(f"select {', '.join(pick)} from {table}"):
                        d = dict(zip(pick, row))
                        ct = d.get("WCDB_CT_message_content") or 0
                        text = _decompress(d.get("message_content"), ct)
                        if kw and kw in text.lower():
                            d["_session_id"] = talker
                            hits.append(_build_message(d, self_wxid, name2id, contacts))
                finally:
                    con.close()
            except Exception:
                continue
    hits.sort(key=lambda m: (m["createTime"], m["localId"]), reverse=True)
    print(json.dumps({"success": True, "messages": hits[:limit], "total": len(hits)}))
    return 0


# ────────────────────────────────────────────────────
# 联系人显示名 / 单个联系人
# ────────────────────────────────────────────────────
def cmd_display_names(cache_dir, ids, self_wxid=""):
    contacts = load_contacts(cache_dir)
    out = {}
    for i in ids:
        if not i:
            continue
        if self_wxid and i == self_wxid:
            out[i] = "我"
        else:
            out[i] = contacts.get(i) or i
    print(json.dumps({"success": True, "names": out}))
    return 0


def cmd_contact(cache_dir, username):
    table_names = ("Contact", "Friend", "contact", "friend")
    contact_db = None
    for t in table_names:
        contact_db = find_table_db(cache_dir, t)
        if contact_db:
            break
    if not contact_db:
        print(json.dumps({"success": False, "error": "未找到联系人表"}))
        return 1
    try:
        con = sqlite3.connect(contact_db)
        try:
            row = con.execute(
                f"select * from {t} where username=?", (username,)
            ).fetchone()
            if not row:
                print(json.dumps({"success": True, "contact": None}))
                return 0
            cols = [r[1] for r in con.execute(f"pragma table_info('{t}')")]
            contact = dict(zip(cols, row))
        finally:
            con.close()
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))
        return 1
    print(json.dumps({"success": True, "contact": contact}))
    return 0


# ────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="微信查看器后端（纯 Python）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("decrypt")
    p.add_argument("--account-dir", required=True)
    p.add_argument("--key", required=True)
    p.add_argument("--cache-dir", required=True)

    p = sub.add_parser("sessions")
    p.add_argument("--cache-dir", required=True)
    p.add_argument("--self", default="")
    p.add_argument("--kind", default="all")

    p = sub.add_parser("messages")
    p.add_argument("--cache-dir", required=True)
    p.add_argument("--self", default="")
    p.add_argument("--session-id", required=True)
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--offset", type=int, default=0)

    p = sub.add_parser("search")
    p.add_argument("--cache-dir", required=True)
    p.add_argument("--self", default="")
    p.add_argument("--keyword", required=True)
    p.add_argument("--session-id", default=None)
    p.add_argument("--limit", type=int, default=30)

    p = sub.add_parser("display-names")
    p.add_argument("--cache-dir", required=True)
    p.add_argument("--self", default="")
    p.add_argument("--ids", required=True)

    p = sub.add_parser("contact")
    p.add_argument("--cache-dir", required=True)
    p.add_argument("--username", required=True)

    args = ap.parse_args()

    if args.cmd == "decrypt":
        return cmd_decrypt(args.account_dir, args.key, args.cache_dir)
    if args.cmd == "sessions":
        return cmd_sessions(args.cache_dir, args.self, args.kind)
    if args.cmd == "messages":
        return cmd_messages(args.cache_dir, args.self, args.session_id, args.limit, args.offset)
    if args.cmd == "search":
        return cmd_search(args.cache_dir, args.self, args.keyword, args.session_id, args.limit)
    if args.cmd == "display-names":
        return cmd_display_names(args.cache_dir, [x for x in args.ids.split(",") if x], args.self)
    if args.cmd == "contact":
        return cmd_contact(args.cache_dir, args.username)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))
        sys.exit(1)
