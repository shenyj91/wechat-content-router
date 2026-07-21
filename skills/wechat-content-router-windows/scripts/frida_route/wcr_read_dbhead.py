"""
Read WeChat DB file header using Windows API with FILE_SHARE_READ|WRITE.
用 FILE_SHARE_READ|WRITE 打开被微信占用的 .db 文件，打印前 512 字节与关键字段
（salt / 加密区起点 / reserve 区 IV / HMAC）。用于对照「磁盘加密参数」与内存解密结果。

注意：加密 SQLCipher 库从 offset 16 起全是密文，offset 20 的 reserved 在磁盘上不可读；
本脚本打印的 reserved 区域是从「假设 reserve=80(IV16+HMAC64)」推算的展示位，仅供对照。
真正可读的 reserved 来自内存明文页（见 run_frida_scan.py 的 databases.json）。

用法（管理员 PowerShell）：
  python wcr_read_dbhead.py --path "F:\\xwechat_files\\wxid_xxx\\db_storage\\session\\session.db"
"""
import ctypes
import argparse
from ctypes import wintypes

kernel32 = ctypes.WinDLL("kernel32")
GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", required=True, help="被微信占用的 .db 文件路径")
    args = ap.parse_args()

    handle = kernel32.CreateFileW(
        args.path, GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None, OPEN_EXISTING, 0, None,
    )
    if handle == ctypes.c_void_p(-1).value:
        print(f"Failed to open file: {args.path}")
        import sys
        sys.exit(1)

    buf = (ctypes.c_ubyte * 4096)()
    bytes_read = wintypes.DWORD()
    kernel32.ReadFile(handle, buf, 4096, ctypes.byref(bytes_read), None)
    kernel32.CloseHandle(handle)

    data = bytes(buf[:bytes_read.value])
    print(f"Read {bytes_read.value} bytes from {args.path}")
    print(f"\nSalt (first 16 bytes): {data[:16].hex()}")
    print(f"\nPage 1 hex dump:")
    for i in range(0, min(len(data), 512), 32):
        hex_str = " ".join(f"{b:02x}" for b in data[i:i + 32])
        ascii_str = "".join(chr(b) if 32 <= b < 127 else "." for b in data[i:i + 32])
        print(f"  {i:04x}: {hex_str}  {ascii_str}")

    print(f"\n--- Key regions for SQLCipher 4 ---")
    print(f"Salt (offset 0-15):  {data[:16].hex()}")
    print(f"Encrypted data start (offset 16): {data[16:32].hex()}")
    reserved = 80
    hmac_start = 4096 - reserved
    print(f"HMAC+IV region (offset {hmac_start}-{4095}):")
    print(f"  IV (offset {hmac_start}-{hmac_start+15}): {data[hmac_start:hmac_start+16].hex()}")
    print(f"  HMAC (offset {hmac_start+16}-{hmac_start+79}): {data[hmac_start+16:hmac_start+80].hex()}")


if __name__ == "__main__":
    main()
