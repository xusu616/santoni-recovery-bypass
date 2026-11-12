import hashlib
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(r"D:\santoni-recovery-bypass")
EDL = ROOT / "tools" / "emmcdl-2.16.exe"
LOADER = ROOT / "tools" / "prog_emmc_firehose_8937_ddr.mbn"
ABOOT_IMG = ROOT / "payloads" / "aboot-miui11-signed-1MiB.bin"
REC_IMG = ROOT / "payloads" / "RedWolf-santoni-appended.img"
RUN_DIR = ROOT / "local-only" / "run-f2b396ae7d44-20261107"

EXPECTED_ABOOT_SHA256 = "b659e08b40b95a50418295aa98b5bd0ee72f7f4ce7a7b7f454dc47efd591be71"
EXPECTED_REC_SHA256 = "d411149e3c87c5bce464d3c36cf3b20e66ea40099f119038775da89d0cb9e164"
EXPECTED_REC_LEN = 28950528


def sha256_file(path: Path, length: int | None = None) -> str:
    data = path.read_bytes()
    if length is not None:
        data = data[:length]
    return hashlib.sha256(data).hexdigest().lower()


def find_9008_port() -> str | None:
    cmd = [
        "powershell",
        "-NoProfile",
        "-Command",
        "Get-CimInstance Win32_PnPEntity | Where-Object { $_.Name -match 'Qualcomm HS-USB QDLoader 9008 \\((COM\\d+)\\)' } | ForEach-Object { $_.Name }",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    for line in res.stdout.splitlines():
        m = re.search(r"\((COM\d+)\)", line)
        if m:
            return m.group(1)
    return None


def run_edl(port: str, args: list[str], log_name: str) -> str:
    cmd = [
        str(EDL),
        "-p",
        port,
        "-f",
        str(LOADER),
        "-MaxPayloadSizeToTargetInBytes",
        "16384",
        *args,
    ]
    print(f"[EDL] Running: {' '.join(args)}", flush=True)
    res = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, errors="replace")
    (RUN_DIR / f"{log_name}.log").write_text(res.stdout, encoding="utf-8")
    (RUN_DIR / f"{log_name}.err.log").write_text(res.stderr, encoding="utf-8")
    if res.returncode != 0 or "Status: 0 " not in res.stdout:
        print(f"[ERROR] EDL command failed (rc={res.returncode}):\n{res.stdout}\n{res.stderr}", flush=True)
        sys.exit(1)
    return res.stdout


def main() -> None:
    assert sha256_file(ABOOT_IMG) == EXPECTED_ABOOT_SHA256, "Input aboot hash mismatch!"
    assert sha256_file(REC_IMG) == EXPECTED_REC_SHA256, "Input recovery hash mismatch!"

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    print("[WAIT] Waiting for Qualcomm HS-USB QDLoader 9008 COM port...", flush=True)
    port = None
    while not port:
        port = find_9008_port()
        if not port:
            time.sleep(1.0)

    print(f"[DETECTED] Found 9008 on {port}! Waiting 1.5s for port stabilization...", flush=True)
    time.sleep(1.5)

    # 1. Read GPT and verify LBA layout
    gpt_out = run_edl(port, ["-gpt"], "00-gpt")
    for name, start, count in [
        ("aboot", "786432", "2048"),
        ("abootbak", "788480", "2048"),
        ("recovery", "921600", "131072"),
    ]:
        pat = rf"Partition Name:\s*{name}\b.*Start LBA:\s*{start}\b.*Size in LBA:\s*{count}\b"
        if not re.search(pat, gpt_out, re.IGNORECASE):
            print(f"[ERROR] Unexpected GPT layout for {name}!\n{gpt_out}", flush=True)
            sys.exit(1)
    print("[OK] GPT layout verified.", flush=True)

    # 2. Backup primary GPT, devinfo, config, aboot twice, abootbak once, recovery twice
    gpt_bin = RUN_DIR / "gpt-primary.bin"
    devinfo_bin = RUN_DIR / "devinfo.bin"
    config_bin = RUN_DIR / "config.bin"
    aboot_a = RUN_DIR / "aboot-a.bin"
    aboot_b = RUN_DIR / "aboot-b.bin"
    abootbak = RUN_DIR / "abootbak.bin"
    rec_a = RUN_DIR / "recovery-a.bin"
    rec_b = RUN_DIR / "recovery-b.bin"

    run_edl(port, ["-d", "0", "34", "-o", str(gpt_bin)], "00b-read-gpt-primary")
    run_edl(port, ["-d", "1052672", "2048", "-o", str(devinfo_bin)], "00c-read-devinfo")
    run_edl(port, ["-d", "8064000", "64", "-o", str(config_bin)], "00d-read-config")
    run_edl(port, ["-d", "786432", "2048", "-o", str(aboot_a)], "01-read-aboot-a")
    run_edl(port, ["-d", "786432", "2048", "-o", str(aboot_b)], "02-read-aboot-b")
    run_edl(port, ["-d", "788480", "2048", "-o", str(abootbak)], "03-read-abootbak")
    run_edl(port, ["-d", "921600", "131072", "-o", str(rec_a)], "04-read-recovery-a")
    run_edl(port, ["-d", "921600", "131072", "-o", str(rec_b)], "05-read-recovery-b")

    h_aboot_a = sha256_file(aboot_a)
    h_aboot_b = sha256_file(aboot_b)
    h_abootbak = sha256_file(abootbak)
    h_rec_a = sha256_file(rec_a)
    h_rec_b = sha256_file(rec_b)

    print(f"[BACKUP] aboot-a:  {h_aboot_a} ({aboot_a.stat().st_size} B)", flush=True)
    print(f"[BACKUP] aboot-b:  {h_aboot_b} ({aboot_b.stat().st_size} B)", flush=True)
    print(f"[BACKUP] abootbak: {h_abootbak} ({abootbak.stat().st_size} B)", flush=True)
    print(f"[BACKUP] rec-a:    {h_rec_a} ({rec_a.stat().st_size} B)", flush=True)
    print(f"[BACKUP] rec-b:    {h_rec_b} ({rec_b.stat().st_size} B)", flush=True)

    if aboot_a.stat().st_size != 1048576 or h_aboot_a != h_aboot_b:
        print("[ERROR] aboot backup verification failed!", flush=True)
        sys.exit(1)
    if abootbak.stat().st_size != 1048576:
        print("[ERROR] abootbak backup size mismatch!", flush=True)
        sys.exit(1)
    if rec_a.stat().st_size != 67108864 or h_rec_a != h_rec_b:
        print("[ERROR] recovery backup verification failed!", flush=True)
        sys.exit(1)

    print("[OK] All backups verified! Proceeding to write aboot and recovery...", flush=True)

    # 3. Write main aboot and RedWolf recovery
    run_edl(port, ["-b", "aboot", str(ABOOT_IMG)], "06-write-aboot")
    run_edl(port, ["-b", "recovery", str(REC_IMG)], "07-write-recovery")

    # 4. Readback and verify
    aboot_after = RUN_DIR / "aboot-after.bin"
    rec_after = RUN_DIR / "recovery-after.bin"
    run_edl(port, ["-d", "786432", "2048", "-o", str(aboot_after)], "08-readback-aboot")
    run_edl(port, ["-d", "921600", "131072", "-o", str(rec_after)], "09-readback-recovery")

    h_aboot_after = sha256_file(aboot_after)
    h_rec_after_prefix = sha256_file(rec_after, EXPECTED_REC_LEN)

    print(f"[VERIFY] aboot-after SHA256:           {h_aboot_after}", flush=True)
    print(f"[VERIFY] recovery-after prefix SHA256: {h_rec_after_prefix}", flush=True)

    if h_aboot_after != EXPECTED_ABOOT_SHA256:
        print("[ERROR] aboot readback hash mismatch!", flush=True)
        sys.exit(1)
    if h_rec_after_prefix != EXPECTED_REC_SHA256:
        print("[ERROR] recovery readback prefix hash mismatch!", flush=True)
        sys.exit(1)

    print("[SUCCESS] EDL backup, write, and full readback verification completed 100%!", flush=True)


if __name__ == "__main__":
    main()
