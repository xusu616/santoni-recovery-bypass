#!/usr/bin/env python3
"""
Redmi 4 Prime (markw / MSM8953) 9008 TWRP 直接刷入脚本

前提：原厂 Recovery (21.76MB 有效 Payload，63.55MB 实读数据) 已确认安全备份完毕。
本脚本专职负责：
1. 监听 9008 端口。
2. 将已追加 Bypass 签名的 TWRP (34.4 MiB) 一次性写入 recovery 分区（耗时仅约 15-20 秒）。
3. 写入完毕后自动发出蜂鸣声提示松开镊子。
"""

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

EXPECTED_TWRP_SHA256 = "1a49de2d583a2855e6c538c5249b6e183bfec51eb1d088d69ea8d5859ba5bc71"
EXPECTED_TWRP_SECTORS = 70552  # 36122624 / 512


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
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


def beep() -> None:
    try:
        import winsound

        winsound.Beep(1200, 250)
        winsound.Beep(1600, 350)
    except Exception:
        pass


def main() -> None:
    print("=" * 65)
    print("红米 4 高配版 (markw) 9008 TWRP 快速刷入")
    print("=" * 65)

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
        print(f"[错误] TWRP 镜像哈希校验失败: {twrp_hash}")
        sys.exit(1)

    print("\n[就绪] 待刷入镜像校验通过:")
    print(f"  文件: {TWRP_APPENDED_IMG.name} ({TWRP_APPENDED_IMG.stat().st_size} 字节)")
    print(f"  SHA-256: {twrp_hash}")
    print("\n请按住短接点并插入 USB 线...")

    port = None
    dots = 0
    while not port:
        port = find_9008_port()
        if not port:
            dots = (dots + 1) % 4
            sys.stdout.write(f"\r等待 9008 端口连接{'.' * dots}   ")
            sys.stdout.flush()
            time.sleep(1.0)

    print(f"\n\n[已连接] 检测到 9008 端口: {port}")
    print("开始刷入 TWRP (约 15~20 秒)，请保持短接稳定...")

    cmd = [
        str(EDL_EXE),
        "-p",
        port,
        "-f",
        str(LOADER_MSM8953),
        "-MaxPayloadSizeToTargetInBytes",
        "16384",
        "-b",
        "recovery",
        str(TWRP_APPENDED_IMG),
    ]

    log_file = OUTPUT_DIR / "15-direct-flash-twrp.log"
    proc = subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    all_lines = []
    rem_pattern = re.compile(r"Sectors remaining\s+(\d+)", re.IGNORECASE)
    last_print = 0.0

    while True:
        line = proc.stdout.readline()
        if not line and proc.poll() is not None:
            break
        if line:
            all_lines.append(line)
            m = rem_pattern.search(line)
            if m:
                rem = int(m.group(1))
                done = EXPECTED_TWRP_SECTORS - rem
                now = time.time()
                if now - last_print >= 0.25 or rem == 0:
                    pct = max(0.0, min(100.0, done / EXPECTED_TWRP_SECTORS * 100))
                    bar_len = 25
                    filled = int(bar_len * pct / 100)
                    bar = "=" * filled + (">" if filled < bar_len else "") + "." * (bar_len - filled - (1 if filled < bar_len else 0))
                    sys.stdout.write(f"\r  [写入 TWRP] {pct:5.1f}% [{bar}] ({done}/{EXPECTED_TWRP_SECTORS} 扇区)")
                    sys.stdout.flush()
                    last_print = now

    proc.wait(timeout=10)
    log_file.write_text("".join(all_lines), encoding="utf-8")
    rc = proc.returncode

    if rc == 0 and "Status: 0 " in "".join(all_lines):
        sys.stdout.write(f"\r  [写入 TWRP] 100.0% [=========================] 写入成功！            \n")
        sys.stdout.flush()
        beep()
        print("\n" + "=" * 65)
        print("TWRP 已成功刷入 recovery 分区！")
        print("现在可以松开镊子并拔掉数据线。")
        print("\n进入 TWRP 步骤：")
        print("  1. 拔掉 USB 数据线；")
        print("  2. 扣上电池排线，盖上后盖；")
        print("  3. 同时按住【音量加 + 音量减 + 电源键】开机；")
        print("  4. 震动亮起 Mi 标志后松开电源键，继续保持按住音量键直至进入 TWRP。")
        print("=" * 65)
    else:
        print(f"\n[错误] 刷入未成功完成，返回值: {rc}。详细信息请见: {log_file}")
        sys.exit(1)


if __name__ == "__main__":
    main()
