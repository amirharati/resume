#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path

from pypdf import PdfReader


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract plain text from a PDF for seeding structured resume data.")
    parser.add_argument("pdf_path")
    args = parser.parse_args()

    path = Path(args.pdf_path)
    reader = PdfReader(str(path))
    for index, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ""
        print(f"--- PAGE {index} ---")
        print(text)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
