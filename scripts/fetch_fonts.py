"""Download DejaVu TTFs into fonts/ (open license). Run once if fonts/ is empty."""

from __future__ import annotations

import io
import zipfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "fonts"
ZIP_URL = "https://github.com/dejavu-fonts/dejavu-fonts/releases/download/version_2_37/dejavu-fonts-ttf-2.37.zip"
FILES = (
    "dejavu-fonts-ttf-2.37/ttf/DejaVuSans.ttf",
    "dejavu-fonts-ttf-2.37/ttf/DejaVuSans-Bold.ttf",
    "dejavu-fonts-ttf-2.37/ttf/DejaVuSansMono.ttf",
)


def main() -> None:
    FONTS.mkdir(exist_ok=True)
    req = urllib.request.Request(ZIP_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        z = zipfile.ZipFile(io.BytesIO(resp.read()))
    for entry in FILES:
        name = Path(entry).name
        out = FONTS / name
        out.write_bytes(z.read(entry))
        print(f"wrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
