"""ตรวจเครื่อง GPU ก่อนเทรน: python -m flock_train.check_env"""

import platform
import shutil
import subprocess


def main() -> None:
    print("python  ", platform.python_version())
    try:
        import torch
    except ImportError:
        raise SystemExit("ยังไม่ได้ติดตั้ง torch (ดู training/README.md ขั้น 0)")
    print("torch   ", torch.__version__, "cuda", torch.version.cuda)
    if not torch.cuda.is_available():
        raise SystemExit("torch มองไม่เห็น GPU: ตรวจไดรเวอร์ NVIDIA และติดตั้ง torch รุ่น CUDA")
    p = torch.cuda.get_device_properties(0)
    print("gpu     ", p.name, f"{p.total_memory / 2**30:.1f} GiB", f"sm_{p.major}{p.minor}")
    x = torch.randn(2048, 2048, device="cuda", dtype=torch.float16)
    torch.cuda.synchronize()
    print("matmul  ", "ok" if torch.isfinite(x @ x).all() else "FAILED")
    for tool in ("ffmpeg", "trtexec", "nvidia-smi"):
        print(f"{tool:8}", shutil.which(tool) or "ไม่พบ")
    if shutil.which("nvidia-smi"):
        q = "--query-gpu=driver_version,temperature.gpu,power.limit"
        print(subprocess.run(["nvidia-smi", q, "--format=csv,noheader"], capture_output=True, text=True).stdout.strip())


if __name__ == "__main__":
    main()
