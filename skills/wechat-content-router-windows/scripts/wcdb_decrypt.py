#!/usr/bin/env python3
"""
WCDB 微信4.x数据库解密（纯Python版）
不依赖WxLens的DLL
"""
import hashlib
import hmac
import os
from pathlib import Path

try:
    from Crypto.Cipher import AES
except ImportError:
    print("请安装: pip install pycryptodome")
    raise

PAGE_SIZE = 4096
SALT_SIZE = 16
KEY_SIZE = 32
IV_SIZE = 16
HMAC_SHA512_SIZE = 64
RESERVED_SIZE = IV_SIZE + HMAC_SHA512_SIZE  # 80
PBKDF2_ITER = 256000
HMAC_ITER = 2
SQLITE_HEADER = b"SQLite format 3\x00"


def decrypt_db(encrypted_path: str, output_path: str, hex_key: str) -> None:
    """解密WCDB加密的数据库"""
    key = bytes.fromhex(hex_key)
    
    with open(encrypted_path, "rb") as f:
        data = f.read()
    
    if data[:16] == SQLITE_HEADER:
        with open(output_path, "wb") as f:
            f.write(data)
        return
    
    salt = data[:SALT_SIZE]
    dk = hashlib.pbkdf2_hmac("sha512", key, salt, PBKDF2_ITER, KEY_SIZE)
    
    mac_salt = bytes(x ^ 0x3a for x in salt)
    mac_key = hashlib.pbkdf2_hmac("sha512", dk, mac_salt, HMAC_ITER, KEY_SIZE)
    
    pages = []
    total_pages = len(data) // PAGE_SIZE
    
    for i in range(total_pages):
        offset = i * PAGE_SIZE
        page = data[offset:offset + PAGE_SIZE]
        
        # 校验HMAC-SHA512
        hmac_start = PAGE_SIZE - HMAC_SHA512_SIZE
        stored_mac = page[hmac_start:]
        
        h = hmac.new(mac_key, digestmod=hashlib.sha512)
        h.update(page[:hmac_start])
        h.update((i + 1).to_bytes(4, "little"))
        computed_mac = h.digest()
        
        if not hmac.compare_digest(stored_mac, computed_mac):
            raise ValueError(f"HMAC校验失败(page {i}), 密钥可能不对")
        
        # AES解密
        iv_start = PAGE_SIZE - RESERVED_SIZE
        iv = page[iv_start:iv_start + IV_SIZE]
        
        if i == 0:
            encrypted = page[SALT_SIZE:iv_start]
        else:
            encrypted = page[:iv_start]
        
        cipher = AES.new(dk, AES.MODE_CBC, iv)
        decrypted = cipher.decrypt(encrypted)
        
        if i == 0:
            page_out = SQLITE_HEADER + decrypted + page[iv_start:]
        else:
            page_out = decrypted + page[iv_start:]
        
        pages.append(page_out)
    
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        for p in pages:
            f.write(p)
    
    with open(output_path, "rb") as f:
        if f.read(16) != SQLITE_HEADER:
            os.unlink(output_path)
            raise RuntimeError("解密失败：验证失败")


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 4:
        print("用法: python wcdb_decrypt.py <加密db路径> <输出路径> <64位hex密钥>")
        sys.exit(1)
    decrypt_db(sys.argv[1], sys.argv[2], sys.argv[3])
    print(f"OK: {sys.argv[2]}")
