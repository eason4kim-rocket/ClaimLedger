#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from claimledger.parsers import OcrEngine


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="claimledger-ocr-") as directory:
        path = Path(directory) / "receipt.png"
        image = Image.new("RGB", (1000, 180), "white")
        draw = ImageDraw.Draw(image)
        draw.text((40, 55), "BANK RECEIPT 2026-07-18 AMOUNT 120000", fill="black", font=ImageFont.load_default(28))
        image.save(path)
        text, confidence, _bbox = OcrEngine().read(path)
        if not text:
            raise SystemExit("OCR smoke test returned no text")
        print(f"confidence={confidence:.3f} text={text}")


if __name__ == "__main__":
    main()

