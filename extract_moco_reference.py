#!/usr/bin/env python3
"""Extract an IBGE PPP base coordinate and write a MOCO reference text file."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from pypdf import PdfReader


def number_pt(value: str) -> float:
    """Convert a Portuguese decimal number such as '590,43' to float."""
    return float(value.replace(".", "").replace(",", "."))


def dms_to_decimal(degrees: str, minutes: str, seconds: str) -> float:
    deg = float(degrees.replace(",", "."))
    minute = float(minutes.replace(",", "."))
    second = float(seconds.replace(",", "."))
    sign = -1.0 if deg < 0 else 1.0
    return sign * (abs(deg) + minute / 60.0 + second / 3600.0)


def extract_pdf_text(pdf_path: Path) -> str:
    reader = PdfReader(str(pdf_path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def extract_values(text: str) -> tuple[float, float, float, float]:
    # Some IBGE PDFs expose minute/second symbols as PostScript glyph names.
    text = re.sub(r"/(?:acute|hungarumlaut)\.ts1", " ", text)
    # Antenna height from the processing summary.
    antenna_match = re.search(
        r"Altura\s+da\s+Antena.*?\(m\)\s*:\s*([0-9.,]+)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not antenna_match:
        raise ValueError("Antenna height was not found in the PDF.")
    antenna_height = number_pt(antenna_match.group(1))

    # Prefer the official SIRGAS 2000.4 row, explicitly marked by IBGE as the one to use.
    coord_match = re.search(
        r"Em\s+2000\.4.*?"
        r"(-?\d+)\s*[°º]\s*(\d+)\s*(?:[´']\s*)?([0-9.,]+)\s*(?:[˝\"”]\s*)?"
        r"(-?\d+)\s*[°º]\s*(\d+)\s*(?:[´']\s*)?([0-9.,]+)\s*(?:[˝\"”]\s*)?"
        r"([0-9.,]+)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not coord_match:
        raise ValueError("The official SIRGAS 2000.4 coordinate row was not found.")

    latitude = dms_to_decimal(*coord_match.group(1, 2, 3))
    longitude = dms_to_decimal(*coord_match.group(4, 5, 6))
    ellipsoidal_height = number_pt(coord_match.group(7))

    # The IBGE value is the antenna reference-point height. Ground is obtained
    # by subtracting the entered antenna height.
    ground_height = ellipsoidal_height #- antenna_height

    return antenna_height, latitude, longitude, ground_height


def write_moco_reference(output_path: Path, values: tuple[float, float, float, float]) -> None:
    antenna_height, latitude, longitude, ground_height = values
    content = (
        "Moco reference {CH}\n"
        "===================\n\n"
        f"Antenna height [m] {{d}}: {antenna_height:.3f}\n"
        f"Latitude [deg]     {{d}}: {latitude:.9f}\n"
        f"Longitude [deg]    {{d}}: {longitude:.9f}\n"
        f"Ground [m]         {{d}}: {ground_height:.2f}\n"
    )
    output_path.write_text(content, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract the official SIRGAS 2000.4 base coordinate from an IBGE PPP PDF."
    )
    parser.add_argument("pdf", type=Path, help="Input IBGE PPP PDF")
    parser.add_argument(
        "-o", "--output", type=Path, default=Path("moco_reference.moco"), help="Output text file"
    )
    args = parser.parse_args()

    text = extract_pdf_text(args.pdf)
    values = extract_values(text)
    write_moco_reference(args.output, values)
    print(f"Created: {args.output}")


if __name__ == "__main__":
    main()
