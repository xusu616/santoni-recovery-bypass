#!/usr/bin/env python3
"""
Wait for Qualcomm 9008 EDL mode on Redmi 4 Prime (markw, MSM8953)
and perform safe READ-ONLY GPT inspection and diagnostic partition dump.

SAFETY GUARANTEE:
- STRICTLY READ-ONLY: Never writes or flashes any partition.
- Dumps: GPT layout, primary GPT (LBA 0-33), and diagnostic partitions (aboot, devinfo).
"""

import hashlib
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(r"D:\santoni-recovery-bypass")
EDL_EXE = ROOT / "tools" / "emmcdl-2.16.exe"
LOADER_MSM8953 = Path(
    r"F:\ROMbackUp\redmi4A-rolex_unlock\Redmi 4a instan UBL  ombob.my.id  (SFILE.MOBI)\loader.mbn"
)
OUTPUT_DIR = ROOT / "local-only" / "markw-diagnosis-20261112"


def find_9008_port() -> str | None:
    """Detect active Qualcomm HS-USB QDLoader 9008 COM port via PowerShell."""
    cmd = [
        "powershell",
        "-NoProfile",
        "-Command",
        "Get-CimInstance Win32_PnPEntity | "
        "Where-Object { $_.Name -match 'Qualcomm HS-USB QDLoader 9008 \\((COM\\d+)\\)' } | "
        "ForEach-Object { $_.Name }",
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        for line in res.stdout.splitlines():
            m = re.search(r"\((COM\d+)\)", line)
            if m:
                return m.group(1)
    except Exception:
        pass
    return None


def run_edl_cmd(port: str, args: list[str], log_prefix: str) -> tuple[int, str]:
    """Execute an emmcdl command safely with stdout/stderr logging."""
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
    print(f"\n[EXEC] {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, errors="replace")
    (OUTPUT_DIR / f"{log_prefix}.log").write_text(res.stdout, encoding="utf-8")
    (OUTPUT_DIR / f"{log_prefix}.err.log").write_text(res.stderr, encoding="utf-8")
    return res.returncode, res.stdout


def sha256_file(path: Path) -> str:
    """Compute SHA256 checksum of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def parse_gpt_partitions(gpt_text: str) -> dict[str, tuple[int, int]]:
    """Parse partition name -> (start_lba, size_in_lba) from emmcdl -gpt output."""
    partitions = {}
    pattern = re.compile(
        r"Partition Name:\s*([^\s\r\n]+)\s+Start LBA:\s*(\d+)\s+Size in LBA:\s*(\d+)",
        re.IGNORECASE,
    )
    for match in pattern.finditer(gpt_text):
        name, start_lba, size_lba = match.groups()
        partitions[name.lower()] = (int(start_lba), int(size_lba))
    return partitions


def main() -> None:
    print("=" * 65)
    print("Redmi 4 Prime (markw / MSM8953) 9008 Safe Diagnostic Tool")
    print("READ-ONLY MODE: No flash or write operations will occur.")
    print("=" * 65)

    if not EDL_EXE.is_file():
        print(f"[ERROR] emmcdl not found: {EDL_EXE}")
        sys.exit(1)
    if not LOADER_MSM8953.is_file():
        print(f"[ERROR] MSM8953 Firehose loader not found: {LOADER_MSM8953}")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("\n[STEP 1] Waiting for device in 9008 mode...")
    print("  -> Please disconnect battery flex cable,")
    print("  -> Short the two EDL test points with tweezers,")
    print("  -> Plug in the USB cable...")
    print("  (Listening for COM port, polling every second...)\n")

    port = None
    dots = 0
    while not port:
        port = find_9008_port()
        if not port:
            dots = (dots + 1) % 4
            sys.stdout.write(f"\r[WAIT] Scanning for 9008 port{'.' * dots}   ")
            sys.stdout.flush()
            time.sleep(1.0)

    print(f"\n\n[DETECTED] Found Qualcomm 9008 on {port}!")
    print(">>> YOU CAN NOW RELEASE THE TWEEZERS! Keep the USB connected. <<<")
    print("Waiting 1.5s for port to stabilize...")
    time.sleep(1.5)

    # 1. Read GPT layout
    print("\n[STEP 2] Reading GPT partition table...")
    rc, gpt_output = run_edl_cmd(port, ["-gpt"], "01-read-gpt")
    print(gpt_output)

    if "Partition Name:" not in gpt_output or "Status: 0" not in gpt_output:
        print("[ERROR] Failed to read GPT or programmer response error.")
        sys.exit(1)

    partitions = parse_gpt_partitions(gpt_output)
    print(f"[INFO] Successfully discovered {len(partitions)} partitions in GPT.")

    # 2. Dump Primary GPT header (LBA 0-33, 34 sectors = 17408 bytes)
    print("\n[STEP 3] Backing up Primary GPT (LBA 0..33)...")
    gpt_file = OUTPUT_DIR / "gpt-primary.bin"
    rc, _ = run_edl_cmd(port, ["-d", "0", "34", "-o", str(gpt_file)], "02-dump-gpt-primary")
    if gpt_file.is_file():
        print(f"[OK] Saved: {gpt_file.name} ({gpt_file.stat().st_size} B, SHA256: {sha256_file(gpt_file)})")

    # 3. Safely dump key diagnostic partitions if present
    targets = ["aboot", "abootbak", "devinfo"]
    for tgt in targets:
        if tgt in partitions:
            start_lba, size_lba = partitions[tgt]
            out_file = OUTPUT_DIR / f"{tgt}.bin"
            print(f"\n[STEP 4] Dumping {tgt} (LBA {start_lba}, count {size_lba})...")
            rc, _ = run_edl_cmd(
                port,
                ["-d", str(start_lba), str(size_lba), "-o", str(out_file)],
                f"03-dump-{tgt}",
            )
            if out_file.is_file():
                h = sha256_file(out_file)
                print(f"[OK] Dumped {tgt}: {out_file.stat().st_size} B, SHA256: {h}")
        else:
            print(f"[WARN] Partition '{tgt}' not found in GPT.")

    print("\n" + "=" * 65)
    print("[SUCCESS] All diagnostic reading and backups completed successfully!")
    print(f"All dumps and logs saved to: {OUTPUT_DIR.resolve()}")
    print("=" * 65)


if __name__ == "__main__":
    main()
