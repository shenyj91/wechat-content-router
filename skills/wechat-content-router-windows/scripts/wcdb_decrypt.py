#!/usr/bin/env python3
"""WCDB微信4.x解密 - 自动探测参数"""
import hashlib, hmac as hmac_mod, sys, os
from pathlib import Path

try:
    from Crypto.Cipher import AES
except ImportError:
    raise RuntimeError("pip install pycryptodome")

SQLITE_HEADER = b"SQLite format 3\x00"
PAGE_SIZE = 4096
KEY_SIZE = 32
IV_SIZE = 16

PARAM_CANDIDATES = [
    {"pbkdf2_hash": "sha512", "pbkdf2_iter": 256000, "hmac_hash": "sha512", "hmac_iter": 2, "reserved": 80},
    {"pbkdf2_hash": "sha512", "pbkdf2_iter": 256000, "hmac_hash": "sha256", "hmac_iter": 2, "reserved": 48},
    {"pbkdf2_hash": "sha1", "pbkdf2_iter": 64000, "hmac_hash": "sha1", "hmac_iter": 2, "reserved": 48},
]

def _try_params(data: bytes, key: bytes, params: dict):
    salt = data[:16]
    try:
        dk = hashlib.pbkdf2_hmac(params["pbkdf2_hash"], key, salt, params["pbkdf2_iter"], KEY_SIZE)
        mac_salt = bytes(x ^ 0x3a for x in salt)
        mac_key = hashlib.pbkdf2_hmac(params["pbkdf2_hash"], dk, mac_salt, params["hmac_iter"], KEY_SIZE)
        
        reserved = params["reserved"]
        hmac_size = reserved - IV_SIZE
        page = data[:PAGE_SIZE]
        hmac_start = PAGE_SIZE - reserved
        stored_mac = page[hmac_start:hmac_start + hmac_size]
        
        h = hmac_mod.new(mac_key, digestmod=hashlib.new(params["hmac_hash"]))
        h.update(page[:hmac_start + IV_SIZE])
        h.update((1).to_bytes(4, "little"))
        computed = h.digest()[:hmac_size]
        
        if hmac_mod.compare_digest(stored_mac, computed):
            return dk, mac_key, params
    except:
        pass
    return None

def decrypt_db(encrypted_path: str, output_path: str, hex_key: str):
    key = bytes.fromhex(hex_key)
    
    with open(encrypted_path, "rb") as f:
        data = f.read()
    
    if data[:16] == SQLITE_HEADER:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(data)
        return
    
    found = None
    for params in PARAM_CANDIDATES:
        result = _try_params(data, key, params)
        if result:
            found = result
            break
    
    if not found:
        raise ValueError("HMAC全失败，密钥可能过期或格式变化")
    
    dk, mac_key, params = found
    
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "wb") as out:
        total_pages = len(data) // PAGE_SIZE
        reserved = params["reserved"]
        
        for i in range(total_pages):
            offset = i * PAGE_SIZE
            page = data[offset:offset + PAGE_SIZE]
            hmac_start = PAGE_SIZE - reserved
            iv = page[hmac_start:hmac_start + IV_SIZE]
            
            if i == 0:
                enc = page[16:hmac_start]
                cipher = AES.new(dk, AES.MODE_CBC, iv)
                dec = cipher.decrypt(enc)
                out.write(SQLITE_HEADER + dec[16:] + page[hmac_start:])
            else:
                enc = page[:hmac_start]
                cipher = AES.new(dk, AES.MODE_CBC, iv)
                dec = cipher.decrypt(enc)
                out.write(dec + page[hmac_start:])
    
    with open(output_path, "rb") as f:
        if f.read(16) != SQLITE_HEADER:
            os.unlink(output_path)
            raise RuntimeError("解密后验证失败")

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("用法: python wcdb_decrypt.py <db> <out> <key>")
        sys.exit(1)
    decrypt_db(sys.argv[1], sys.argv[2], sys.argv[3])
    print(f"OK: {sys.argv[2]}")
