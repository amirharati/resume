#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import mimetypes
import pathlib
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = ROOT / "output" / "fetch"
PLAYWRIGHT_HELPER = ROOT / "scripts" / "fetch_url_playwright.js"


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"^https?://", "", value)
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value or "capture"


def derive_name(url: str, explicit_name: str | None) -> str:
    if explicit_name:
        return slugify(explicit_name)

    parsed = urllib.parse.urlparse(url)
    tail = pathlib.PurePosixPath(parsed.path).name or parsed.netloc
    return slugify(tail or url)


def fetch_raw(url: str, timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
        content_type = response.headers.get("Content-Type", "application/octet-stream")
        return {
            "final_url": response.geturl(),
            "status": getattr(response, "status", 200),
            "content_type": content_type,
            "body": body,
            "headers": dict(response.headers.items()),
        }


def write_raw_capture(out_dir: pathlib.Path, name: str, capture: dict[str, Any]) -> list[str]:
    content_type = capture["content_type"].split(";", 1)[0].strip().lower()
    extension = mimetypes.guess_extension(content_type) or ".bin"
    if content_type in {"text/html", "application/xhtml+xml"}:
        extension = ".html"
    elif content_type == "application/json":
        extension = ".json"
    elif content_type.startswith("text/"):
        extension = ".txt"

    raw_path = out_dir / f"{name}.raw{extension}"
    raw_path.write_bytes(capture["body"])

    meta_path = out_dir / f"{name}.raw.meta.json"
    meta_path.write_text(
        json.dumps(
            {
                "mode": "raw",
                "final_url": capture["final_url"],
                "status": capture["status"],
                "content_type": capture["content_type"],
                "headers": capture["headers"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return [str(raw_path), str(meta_path)]


def run_playwright_capture(url: str, out_dir: pathlib.Path, name: str, timeout: int) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    command = [
        "node",
        str(PLAYWRIGHT_HELPER),
        url,
        str(out_dir.resolve()),
        name,
        str(timeout * 1000),
    ]
    result = subprocess.run(command, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            "Playwright fetch failed.\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def write_rendered_markdown(rendered_files: list[str]) -> str | None:
    text_path = None
    meta_path = None
    for file_name in rendered_files:
        path = pathlib.Path(file_name)
        if path.name.endswith(".rendered.txt"):
            text_path = path
        elif path.name.endswith(".rendered.meta.json"):
            meta_path = path

    if not text_path or not meta_path or not text_path.exists() or not meta_path.exists():
        return None

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    text = text_path.read_text(encoding="utf-8").strip()
    title = meta.get("title") or text_path.stem.replace(".rendered", "")
    source_url = meta.get("source_url", "")
    final_url = meta.get("final_url", "")

    lines = [f"# {title}", ""]
    if source_url:
        lines.append(f"- Source: {source_url}")
    if final_url and final_url != source_url:
        lines.append(f"- Final URL: {final_url}")
    lines.extend(["", "## Captured Text", "", text if text else "_No text captured._", ""])

    markdown_path = text_path.with_suffix(".md")
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return str(markdown_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch a URL as raw HTTP content and optionally as rendered page output."
    )
    parser.add_argument("url", help="URL to fetch")
    parser.add_argument("--out", default=str(DEFAULT_OUT_DIR), help="Output directory")
    parser.add_argument("--name", help="Base filename to use for outputs")
    parser.add_argument("--timeout", type=int, default=30, help="Timeout in seconds")
    parser.add_argument(
        "--rendered",
        action="store_true",
        help="Also capture rendered HTML/text using Playwright",
    )
    parser.add_argument(
        "--rendered-only",
        action="store_true",
        help="Skip raw HTTP fetch and capture only rendered output",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = pathlib.Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    name = derive_name(args.url, args.name)

    written_files: list[str] = []
    if not args.rendered_only:
        try:
            raw_capture = fetch_raw(args.url, args.timeout)
            written_files.extend(write_raw_capture(out_dir, name, raw_capture))
        except urllib.error.URLError as exc:
            print(f"Raw fetch failed: {exc}", file=sys.stderr)
            if not args.rendered:
                return 1

    if args.rendered or args.rendered_only:
        rendered_files = run_playwright_capture(args.url, out_dir, name, args.timeout)
        written_files.extend(rendered_files)
        markdown_file = write_rendered_markdown(rendered_files)
        if markdown_file:
            written_files.append(markdown_file)

    print("\n".join(written_files))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
