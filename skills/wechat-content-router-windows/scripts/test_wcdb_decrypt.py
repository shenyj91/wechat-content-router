#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wcdb_decrypt.py 的回归测试（无需微信，纯合成库验证）。

要点：SQLCipher 每页末尾 reserve(=hmac_sz+iv_sz) 字节被 IV/HMAC 占用，明文内容
不得写进该区。标准 sqlite3 建的库 reserve=0，cell 从页尾向下生长会侵入该区，
因此本测试先把文件头 offset 20 设为 80（预留）再 VACUUM，造出"合法预留库"。

运行：
  python3 scripts/test_wcdb_decrypt.py
"""
import os
import struct
import sqlite3
import hashlib
import hmac as hmac_mod
import tempfile
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import wcdb_decrypt as wd
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

PAGE = 4096
IV = 16
RES = 80  # IV16 + SHA512 64


def _enc_page(pp, pageno, ck, hk, page_size=PAGE, res=RES):
    rs = 16 if pageno == 1 else 0
    size = page_size - rs - res
    iv = os.urandom(IV)
    c = Cipher(algorithms.AES(ck), modes.CBC(iv))
    e = c.encryptor()
    enc = e.update(pp[rs: rs + size]) + e.finalize()
    hi = enc + iv + struct.pack("<I", pageno)
    hm = hmac_mod.new(hk, hi, "sha512").digest()[: res - IV]
    return (pp[0:16] + enc + iv + hm) if pageno == 1 else (enc + iv + hm)


def _encrypt_db(plain, key, page_size=PAGE):
    n = len(plain) // page_size
    salt = plain[0:16]
    ck = key[:32]
    hk = hashlib.pbkdf2_hmac("sha512", ck, bytes(b ^ 0x3A for b in salt), 2, 32)
    return b"".join(_enc_page(plain[(p - 1) * page_size: p * page_size], p, ck, hk,
                               page_size=page_size)
                     for p in range(1, n + 1))


def _make_reserved_db(path, nrows, txt):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE Msg(a INTEGER, b TEXT)")
    for i in range(nrows):
        con.execute("INSERT INTO Msg VALUES(?,?)", (i, f"{txt}{i}"))
    con.commit()
    con.close()
    with open(path, "r+b") as f:
        f.seek(20)
        f.write(bytes([80]))  # 设 reserved=80
    con = sqlite3.connect(path)
    con.execute("VACUUM")     # 重建并尊重预留区
    con.close()
    return open(path, "rb").read()


def main():
    d = tempfile.mkdtemp()
    dbp = os.path.join(d, "m.db")
    plain = _make_reserved_db(dbp, 600, "x" * 150)
    n_pages = len(plain) // PAGE
    print(f"合成库 {len(plain)} 字节 = {n_pages} 页")

    key = bytes.fromhex("a1" * 32)
    enc = _encrypt_db(plain, key)

    # 1) 全解无损
    dec, cfg = wd.decrypt_wcdb(enc, key)
    assert dec is not None and dec == plain, "全解应无损还原"
    assert cfg.get("partial") is False
    print(f"[PASS] 全解无损 (SHA512/raw_key)")

    # 2) 损坏页 3,5,7 -> best-effort 标记 partial 且定位失败页
    bad = bytearray(enc)
    for p in (3, 5, 7):
        off = (p - 1) * PAGE + (16 if p == 1 else 0)
        bad[off: off + 8] = bytes(8)
    dec2, cfg2 = wd.decrypt_wcdb(bytes(bad), key)
    assert dec2 is not None and cfg2.get("partial") is True
    assert set(cfg2["failed_pages"]) == {3, 5, 7}
    print(f"[PASS] best-effort 标记 partial, 失败页={cfg2['failed_pages']}")

    # 3) 错 key -> None
    assert wd.decrypt_wcdb(enc, bytes.fromhex("b2" * 32))[0] is None
    print("[PASS] 错 key 返回 None")

    # 4) page_size=2048 也能解
    dbp2 = os.path.join(d, "m2.db")
    con = sqlite3.connect(dbp2)
    con.execute("PRAGMA page_size=2048")
    con.execute("CREATE TABLE T(x)")
    for i in range(20):
        con.execute("INSERT INTO T VALUES(?)", (i,))
    con.commit()
    con.close()
    with open(dbp2, "r+b") as f:
        f.seek(20)
        f.write(bytes([80]))
    con = sqlite3.connect(dbp2)
    con.execute("VACUUM")
    con.close()
    plain2 = open(dbp2, "rb").read()
    salt2 = plain2[0:16]
    hk2 = hashlib.pbkdf2_hmac("sha512", key[:32], bytes(b ^ 0x3A for b in salt2), 2, 32)
    enc2 = _encrypt_db(plain2, key, page_size=2048)
    dec3, cfg3 = wd.decrypt_wcdb(enc2, key)
    assert dec3 is not None and dec3 == plain2
    assert cfg3["page_size"] == 2048
    print(f"[PASS] page_size=2048 无损还原")

    # 5) diagnose 不崩
    diag = wd.diagnose(enc, key)
    assert "全解成功" in diag
    print("[PASS] diagnose 正常")

    print("\n全部断言通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
