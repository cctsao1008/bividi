#!/usr/bin/env python3
"""Bounded DirectShow discriminator for DECXIN AR0234 YUYV acquisition.

This tool complements diagnose_ar0234_yuyv.py.  It verifies what DirectShow
advertises, brackets the YUYV attempt with MJPEG controls, and uses a hard
process watchdog so a driver/device stall cannot hang an operator shell.

A DirectShow YUYV stall is evidence below Bividi/OpenCV normalization.  It is
not, by itself, proof of USB-bandwidth exhaustion: device firmware, UVC mode
negotiation, Windows USB/UVC stack, and the negotiated host link remain
separate hypotheses.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

SCHEMA = "bividi.ar0234.directshow_yuyv_diagnostic.v1"


@dataclass
class Attempt:
    name: str
    purpose: str
    command: list[str]
    return_code: int | None = None
    timed_out: bool = False
    elapsed_s: float = 0.0
    frames: int = 0
    stdout_log: str = ""
    stderr_log: str = ""

    @property
    def passed(self) -> bool:
        return not self.timed_out and self.return_code == 0 and self.frames > 0


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def default_session() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + socket.gethostname()


def parse_progress_frames(text: str) -> int:
    values = [int(x) for x in re.findall(r"(?m)^frame=(\d+)\s*$", text)]
    return max(values) if values else 0


def parse_options(text: str) -> dict[str, bool]:
    return {
        "mjpeg": bool(re.search(r"vcodec=mjpeg\s+min s=4000x1200 fps=30", text)),
        "yuyv30": bool(re.search(r"pixel_format=yuyv422\s+min s=4000x1200 fps=30\s+max s=4000x1200 fps=30", text)),
    }


def bounded_run(attempt: Attempt, root: Path, watchdog_s: float) -> Attempt:
    stdout_path = root / f"{attempt.name}.stdout.log"
    stderr_path = root / f"{attempt.name}.stderr.log"
    started = time.monotonic()

    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    proc = subprocess.Popen(
        attempt.command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        creationflags=creationflags,
    )
    try:
        out, err = proc.communicate(timeout=watchdog_s)
        attempt.return_code = proc.returncode
    except subprocess.TimeoutExpired:
        attempt.timed_out = True
        proc.kill()
        out, err = proc.communicate()
        attempt.return_code = proc.returncode

    attempt.elapsed_s = time.monotonic() - started
    attempt.frames = parse_progress_frames(out)
    stdout_path.write_text(out, encoding="utf-8")
    stderr_path.write_text(err, encoding="utf-8")
    attempt.stdout_log = str(stdout_path)
    attempt.stderr_log = str(stderr_path)
    return attempt


def capture_command(ffmpeg: str, device: str, *, transport: str, frames: int) -> list[str]:
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel", "info",
        "-f", "dshow",
        "-rtbufsize", "1024M",
        "-video_size", "4000x1200",
        "-framerate", "30",
    ]
    if transport == "yuyv":
        cmd += ["-pixel_format", "yuyv422"]
    elif transport == "mjpeg":
        cmd += ["-vcodec", "mjpeg"]
    else:
        raise ValueError(transport)
    cmd += [
        "-i", f"video={device}",
        "-frames:v", str(frames),
        "-progress", "pipe:1",
        "-nostats",
        "-f", "null", "-",
    ]
    return cmd


def classify(options: dict[str, bool], attempts: dict[str, Attempt]) -> tuple[str, str]:
    if not options.get("yuyv30"):
        return "DSHOW_YUYV_NOT_ADVERTISED", "DirectShow did not advertise 4000x1200 YUYV422 at 30 fps."
    pre = attempts["D02_mjpeg_pre"].passed
    yuyv = attempts["D03_yuyv30"]
    post = attempts["D04_mjpeg_post"].passed
    if not pre or not post:
        return "DSHOW_DEVICE_UNHEALTHY", "MJPEG control failed before or after the YUYV attempt; do not isolate the fault to YUYV."
    if yuyv.passed:
        return "DSHOW_YUYV_FUNCTIONAL", "DirectShow delivered the requested YUYV30 frames while MJPEG controls also remained healthy."
    if yuyv.timed_out:
        return "DSHOW_YUYV_STALL", "DirectShow advertised YUYV30 but the bounded capture did not complete before the watchdog while MJPEG controls remained healthy."
    return "DSHOW_YUYV_OPEN_OR_STREAM_FAILED", "DirectShow advertised YUYV30 but the capture exited unsuccessfully while MJPEG controls remained healthy."


def render_report(root: Path, options: dict[str, bool], attempts: dict[str, Attempt], classification: str, conclusion: str) -> str:
    lines = [
        "# DECXIN AR0234 DirectShow YUYV Diagnostic Report",
        "",
        f"- Created: `{utc_now()}`",
        f"- Host: `{socket.gethostname()}` / `{platform.platform()}`",
        f"- Classification: **{classification}**",
        f"- Advertised options: `{json.dumps(options, sort_keys=True)}`",
        "",
        "## Result",
        "",
        conclusion,
        "",
        "## Attempt matrix",
        "",
        "| Attempt | Purpose | RC | Timeout | Frames | Elapsed s |",
        "|---|---|---:|---|---:|---:|",
    ]
    for item in attempts.values():
        lines.append(
            f"| {item.name} | {item.purpose} | {item.return_code} | {str(item.timed_out).lower()} | {item.frames} | {item.elapsed_s:.3f} |"
        )
    lines += [
        "",
        "## Interpretation boundary",
        "",
        "- A YUYV stall here occurs before Bividi/OpenCV YUYV normalization.",
        "- If Nori and DirectShow both fail YUYV while MJPEG remains healthy, suspicion moves below the two application backends: device/firmware, UVC uncompressed-mode negotiation, Windows USB/UVC stack, or host-link conditions.",
        "- This test does not prove negotiated USB speed or bandwidth exhaustion.",
        "",
        f"Artifacts: `{root}`",
        "",
    ]
    return "\n".join(lines)


def self_test() -> int:
    sample = """vcodec=mjpeg  min s=4000x1200 fps=30 max s=4000x1200 fps=60.0002\npixel_format=yuyv422  min s=4000x1200 fps=30 max s=4000x1200 fps=30\n"""
    assert parse_options(sample) == {"mjpeg": True, "yuyv30": True}
    assert parse_progress_frames("frame=1\nframe=30\nprogress=end\n") == 30
    print("AR0234 DirectShow YUYV diagnostic self-test: PASS")
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Bounded DirectShow YUYV diagnostic for DECXIN AR0234.")
    p.add_argument("--ffmpeg", default=None, help="ffmpeg executable; defaults to PATH lookup")
    p.add_argument("--device-name", default="DECXIN Camera")
    p.add_argument("--frames", type=int, default=30)
    p.add_argument("--watchdog-s", type=float, default=15.0)
    p.add_argument("--output-dir", type=Path, default=Path("artifacts/physical/nori/directshow-yuyv-diagnostic"))
    p.add_argument("--session-id", default=None)
    p.add_argument("--self-test", action="store_true")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.self_test:
        return self_test()

    ffmpeg = args.ffmpeg or shutil.which("ffmpeg")
    if not ffmpeg:
        print("ffmpeg not found; pass --ffmpeg", file=sys.stderr)
        return 2

    root = args.output_dir / (args.session_id or default_session())
    root.mkdir(parents=True, exist_ok=False)

    list_cmd = [ffmpeg, "-hide_banner", "-f", "dshow", "-list_options", "true", "-i", f"video={args.device_name}"]
    list_attempt = Attempt("D01_list_options", "enumerate DirectShow camera modes", list_cmd)
    bounded_run(list_attempt, root, args.watchdog_s)
    # FFmpeg commonly exits non-zero after printing dshow options; parse both streams.
    list_text = Path(list_attempt.stdout_log).read_text(encoding="utf-8") + "\n" + Path(list_attempt.stderr_log).read_text(encoding="utf-8")
    options = parse_options(list_text)

    attempts = {
        "D02_mjpeg_pre": Attempt(
            "D02_mjpeg_pre", "MJPEG30 control before YUYV",
            capture_command(ffmpeg, args.device_name, transport="mjpeg", frames=min(args.frames, 30)),
        ),
        "D03_yuyv30": Attempt(
            "D03_yuyv30", "YUYV422 4000x1200@30 bounded capture",
            capture_command(ffmpeg, args.device_name, transport="yuyv", frames=args.frames),
        ),
        "D04_mjpeg_post": Attempt(
            "D04_mjpeg_post", "MJPEG30 control after YUYV",
            capture_command(ffmpeg, args.device_name, transport="mjpeg", frames=min(args.frames, 30)),
        ),
    }

    print(f"[D01_list_options] advertised mjpeg={options['mjpeg']} yuyv30={options['yuyv30']}")
    for item in attempts.values():
        print(f"[{item.name}] {item.purpose}")
        bounded_run(item, root, args.watchdog_s)
        print(f"  rc={item.return_code} timeout={item.timed_out} frames={item.frames} elapsed_s={item.elapsed_s:.3f}")

    classification, conclusion = classify(options, attempts)
    report = render_report(root, options, attempts, classification, conclusion)
    report_path = root / "report.md"
    result_path = root / "result.json"
    report_path.write_text(report, encoding="utf-8")
    result_path.write_text(json.dumps({
        "schema": SCHEMA,
        "created_utc": utc_now(),
        "classification": classification,
        "conclusion": conclusion,
        "host": {"hostname": socket.gethostname(), "platform": platform.platform()},
        "device_name": args.device_name,
        "advertised": options,
        "attempts": [asdict(list_attempt)] + [asdict(x) | {"passed": x.passed} for x in attempts.values()],
        "report": str(report_path),
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"classification: {classification}")
    print(f"report: {report_path}")
    print(f"result: {result_path}")
    return 0 if classification == "DSHOW_YUYV_FUNCTIONAL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
