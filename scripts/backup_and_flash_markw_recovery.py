#!/usr/bin/env python3
"""
Redmi 4 Prime (markw / MSM8953) 9008 Recovery 自动处理脚本

使用方式：
直接通过 subprocess.run 继承控制台原生输出，彻底去除管道重定向和 readline 缓冲，
保证 emmcdl 每一行输出实时打印到 PowerShell 界面，绝无阻塞。
"""

import argparse
import hashlib
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(r"D:\santoni-recovery-bypass")
EDL_EXE = ROOT / "tools" / "emmcdl-2.16.exe"
LOADER_MSM8953 = ROOT / "tools" / "prog_emmc_firehose_8953_ddr.mbn"
OUTPUT_DIR = ROOT / "local-only" / "markw-diagnosis-20261112"
TWRP_APPENDED_IMG = ROOT / "roms" / "twrp-3.4.0-1-markw-appended.img"
ORIGINAL_REC_BIN = OUTPUT_DIR / "recovery-original.bin"

EXPECTED_TWRP_SHA256 = "1a49de2d583a2855e6c538c5249b6e183bfec51eb1d088d69ea8d5859ba5bc71"
EXPECTED_TWRP_LEN = 36122624
EXPECTED_TWRP_SECTORS = 70552  # 36122624 / 512

RECOVERY_START_LBA = 921600
RECOVERY_TOTAL_SECTORS = 131072  # 64 MiB


def sha256_file(path: Path, length: int | None = None) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        remaining = length if length is not None else float("inf")
        while remaining > 0:
            chunk_size = min(65536, remaining) if length is not None else 65536
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
            if length is not None:
                remaining -= len(chunk)
    return h.hexdigest().lower()


def find_9008_port() -> str | None:
    cmd = [
        "powershell",
        "-NoProfile",
        "-Command",
        "Get-CimInstance Win32_PnPEntity | "
        "Where-Object { $_.Name -match 'Qualcomm HS-USB QDLoader 9008 \\((COM\\d+)\\)' } | "
        "ForEach-Object { $_.Name }",
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
        for line in res.stdout.splitlines():
            m = re.search(r"\((COM\d+)\)", line)
            if m:
                return m.group(1)
    except Exception:
        pass
    return None


def run_edl_direct(port: str, args: list[str]) -> int:
    """直接调用 emmcdl，原生继承当前控制台 stdout/stderr，零缓冲，零阻塞。"""
    cmd = [
        str(EDL_EXE),
        "-p",
        port,
        "-f",
        str(LOADER_MSM8953),
        "-MaxPayloadSizeToTargetInBytes",
        "16384",
        *args,
    ]
    print(f"\n>> [执行命令] {' '.join(cmd)}\n")
    res = subprocess.run(cmd, cwd=str(ROOT))
    return res.returncode


def beep() -> None:
    try:
        import winsound

        winsound.Beep(1200, 250)
        winsound.Beep(1600, 350)
    except Exception:
        pass


def check_original_backup_ready() -> bool:
    if not ORIGINAL_REC_BIN.is_file():
        return False
    sz = ORIGINAL_REC_BIN.stat().st_size
    if sz != RECOVERY_TOTAL_SECTORS * 512:
        return False
    with open(ORIGINAL_REC_BIN, "rb") as f:
        magic = f.read(8)
    return magic == b"ANDROID!"


def main() -> None:
    parser = argparse.ArgumentParser(description="Redmi 4 Prime 9008 Recovery 工具")
    parser.add_argument("--force-backup", action="store_true", help="强制重新完整备份 64MiB 原厂 Recovery")
    args = parser.parse_args()

    print("=" * 68)
    print("红米 4 高配版 (markw / MSM8953) 9008 原生控制台直通刷机工具")
    print("=" * 68)

    if not EDL_EXE.is_file():
        print(f"[错误] emmcdl 不存在: {EDL_EXE}")
        sys.exit(1)
    if not LOADER_MSM8953.is_file():
        print(f"[错误] Firehose loader 不存在: {LOADER_MSM8953}")
        sys.exit(1)
    if not TWRP_APPENDED_IMG.is_file():
        print(f"[错误] TWRP 镜像不存在: {TWRP_APPENDED_IMG}")
        sys.exit(1)

    twrp_hash = sha256_file(TWRP_APPENDED_IMG)
    if twrp_hash != EXPECTED_TWRP_SHA256:
        print(f"[错误] TWRP 镜像哈希不匹配: {twrp_hash}")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 检查是否已具有合法的 64MiB 原厂备份
    has_backup = check_original_backup_ready()
    if has_backup and not args.force_backup:
        print("\n[状态检测] 本地已存在完整且合法的原厂 Recovery 备份:")
        print(f"  文件路径: {ORIGINAL_REC_BIN.resolve()}")
        print(f"  文件大小: {ORIGINAL_REC_BIN.stat().st_size} 字节 (精确 64.0 MiB, Magic: ANDROID!)")
        print("  -> 跳过 64MiB 冗余备份，直接进入 TWRP 刷写（仅需约 15 秒）！")
        need_dump = False
    else:
        print("\n[状态检测] 将执行 64MiB 原厂 Recovery 完整备份...")
        need_dump = True

    print("\n请按住短接点并插入 USB 数据线...")
    port = None
    dots = 0
    while not port:
        port = find_9008_port()
        if not port:
            dots = (dots + 1) % 4
            sys.stdout.write(f"\r等待 9008 COM 端口连接{'.' * dots}   ")
            sys.stdout.flush()
            time.sleep(1.0)

    print(f"\n\n[已连接] 检测到 9008 端口: {port}！保持短接稳定...")

    # 1. 如果需要备份原厂 recovery
    if need_dump:
        print("\n[步骤 1] 正在备份原厂 Recovery (64 MiB)...")
        rc = run_edl_direct(
            port,
            ["-d", str(RECOVERY_START_LBA), str(RECOVERY_TOTAL_SECTORS), "-o", str(ORIGINAL_REC_BIN)],
        )
        if rc != 0 or not check_original_backup_ready():
            print(f"\n[错误] 原厂 Recovery 备份失败或校验未通过，已终止写入。返回值: {rc}")
            sys.exit(1)
        print("\n[完成] 原厂 Recovery 备份校验通过！")

    # 2. 刷入 TWRP (Appended)
    print("\n[步骤 2] 正在刷入 TWRP 3.4.0-1 (Bypass) 到 recovery 分区...")
    rc = run_edl_direct(
        port,
        ["-b", "recovery", str(TWRP_APPENDED_IMG)],
    )
    if rc != 0:
        print(f"\n[错误] 刷入 TWRP 失败，返回值: {rc}")
        sys.exit(1)

    # 3. 回读前 70552 扇区进行校验
    print("\n[步骤 3] 正在回读校验已写入的 TWRP 分区数据...")
    rec_verify = OUTPUT_DIR / "recovery-flashed-verify.bin"
    rc = run_edl_direct(
        port,
        ["-d", str(RECOVERY_START_LBA), str(EXPECTED_TWRP_SECTORS), "-o", str(rec_verify)],
    )
    if rc != 0 or not rec_verify.is_file():
        print(f"\n[错误] 回读校验命令失败，返回值: {rc}")
        sys.exit(1)

    verify_hash = sha256_file(rec_verify, EXPECTED_TWRP_LEN)
    print(f"\n  回读前缀校验哈希: {verify_hash}")
    print(f"  预期 TWRP 哈希:   {EXPECTED_TWRP_SHA256}")

    if verify_hash != EXPECTED_TWRP_SHA256:
        print("\n[错误] 回读哈希校验不匹配！")
        sys.exit(1)

    beep()
    print("\n" + "=" * 68)
    print("TWRP 3.4.0-1 刷入与 100% 回读校验全部成功！")
    print("现在可以松开镊子并拔掉数据线。")
    print("\n进入 TWRP 步骤：")
    print("  1. 拔掉 USB 数据线；")
    print("  2. 扣上电池排线，盖上后盖；")
    print("  3. 同时按住【音量加 + 音量减 + 电源键】开机；")
    print("  4. 震动亮起 Mi 标志后松开电源键，继续保持按住音量键直至进入 TWRP。")
    print("=" * 68)


if __name__ == "__main__":
    main()
