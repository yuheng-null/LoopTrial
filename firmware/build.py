"""Build the complete Blue Pill example with a GNU Arm Embedded toolchain."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess


def build(output: Path, bin_dir: Path | None = None):
    root = Path(__file__).resolve().parent
    if not bin_dir:
        gcc = shutil.which("arm-none-eabi-gcc")
        if gcc:
            bin_dir = Path(gcc).parent
        else:
            bundle = Path(os.environ.get("LOCALAPPDATA", ".")) / "stm32cube/bundles/gnu-tools-for-stm32"
            installed = sorted(bundle.glob("*/bin/arm-none-eabi-gcc.exe"))
            if not installed:
                raise SystemExit("Install GNU Arm Embedded tools or pass --toolchain-bin.")
            bin_dir = installed[-1].parent
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    base = output / "looptrial-bluepill-0.2.0.elf"
    subprocess.run([str(bin_dir / "arm-none-eabi-gcc"), "-std=c11", "-mcpu=cortex-m3",
                    "-mthumb", "-Os", "-Wall", "-Wextra", "-Werror", "-ffreestanding",
                    "-fno-builtin", "-ffunction-sections", "-fdata-sections", "-nostdlib",
                    "-Wl,--gc-sections,--build-id=none", "-T", "stm32f103c8.ld",
                    "looptrial.c", "board.c", "-o", str(base)], cwd=root, check=True)
    subprocess.run([str(bin_dir / "arm-none-eabi-objcopy"), "-O", "binary", str(base),
                    str(base.with_suffix(".bin"))], check=True)
    subprocess.run([str(bin_dir / "arm-none-eabi-size"), str(base)], check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--toolchain-bin", type=Path)
    args = parser.parse_args()
    build(args.output, args.toolchain_bin)
