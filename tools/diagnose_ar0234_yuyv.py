#!/usr/bin/env python3
"""Diagnose DECXIN AR0234/Nori YUYV acquisition failures without blaming decode.

The feature qualification runner intentionally reports A04 as a hard functional
failure when an advertised YUYV mode produces no raw frame.  This diagnostic
then separates a few common classes of failure:

* transient first-frame/startup latency;
* interaction with the runner's free-run trigger configuration;
* broader device/backend failure;
* YUYV-specific no-buffer behavior upstream of Bividi image normalization.

The tool does not claim that USB BCD is the negotiated link speed.  It records
that SDK field as provenance only.  Likewise, a YUYV bandwidth calculation is a
payload-rate requirement, not proof of the actual USB link rate.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import re
import socket
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence

SCHEMA = "bividi.ar0234.yuyv_diagnostic.v1"


@dataclass
class Attempt:
    name: str
    purpose: str
    command: list[str]
    return_code: int | None = None
    frames: int = 0
    first_sequence: int | None = None
    last_sequence: int | None = None
    bytes_values: list[int] = field(default_factory=list)
    stdout_log: str = ""
    stderr_log: str = ""
    stderr_summary: str = ""

    @property
    def passed(self) -> bool:
        return self.return_code == 0 and self.frames > 0


def exe_name(base: str) -> str:
    return base + (".exe" if os.name == "nt" else "")


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def default_session() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + socket.gethostname()


def parse_modes(text: str) -> dict[str, int]:
    result: dict[str, int] = {}
    rx = re.compile(r"^\s*(\d+):\s+(\d+)x(\d+)@([0-9.]+)\s+(\S+)", re.MULTILINE)
    for match in rx.finditer(text):
        index = int(match.group(1))
        width = int(match.group(2))
        height = int(match.group(3))
        transport = match.group(5).lower()
        if width == 4000 and height == 1200 and transport in {"mjpeg", "yuyv"}:
            result.setdefault(transport, index)
    return result


def parse_usb_bcd(text: str) -> str | None:
    match = re.search(r"^\s*USB BCD:\s*(0x[0-9A-Fa-f]+)", text, re.MULTILINE)
    return match.group(1) if match else None


def parse_grab(text: str) -> tuple[int, int | None, int | None, list[int]]:
    seq: list[int] = []
    sizes: list[int] = []
    rx = re.compile(r"frame sequence=(\d+)\s+bytes=(\d+)")
    for match in rx.finditer(text):
        seq.append(int(match.group(1)))
        sizes.append(int(match.group(2)))
    return len(seq), (seq[0] if seq else None), (seq[-1] if seq else None), sizes


def run_attempt(root: Path, attempt: Attempt) -> Attempt:
    stdout_path = root / f"{attempt.name}.stdout.log"
    stderr_path = root / f"{attempt.name}.stderr.log"
    cp = subprocess.run(
        attempt.command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
    )
    stdout_path.write_text(cp.stdout, encoding="utf-8")
    stderr_path.write_text(cp.stderr, encoding="utf-8")
    attempt.return_code = cp.returncode
    attempt.stdout_log = str(stdout_path)
    attempt.stderr_log = str(stderr_path)
    attempt.stderr_summary = " | ".join(line.strip() for line in cp.stderr.splitlines() if line.strip())
    attempt.frames, attempt.first_sequence, attempt.last_sequence, attempt.bytes_values = parse_grab(cp.stdout)
    return attempt


def make_grab(
    grab: str,
    *,
    device: int,
    mode: int,
    frames: int,
    timeout_ms: int,
    no_trigger_config: bool = False,
) -> list[str]:
    command = [
        grab,
        "--device", str(device),
        "--mode", str(mode),
        "--frames", str(frames),
        "--timeout-ms", str(timeout_ms),
    ]
    if no_trigger_config:
        command.append("--no-trigger-config")
    return command


def classify(attempts: dict[str, Attempt]) -> tuple[str, str]:
    pre = attempts["D01_mjpeg_pre"].passed
    post = attempts["D05_mjpeg_post"].passed
    short = attempts["D02_yuyv_short"].passed
    long_default = attempts["D03_yuyv_long"].passed
    long_no_trigger = attempts["D04_yuyv_no_trigger"].passed

    if not pre or not post:
        return (
            "DEVICE_STREAM_UNHEALTHY",
            "MJPEG control acquisition failed before or after the YUYV attempts; do not isolate the fault to YUYV.",
        )
    if short:
        return (
            "YUYV_FUNCTIONAL",
            "YUYV produced raw frames within the normal timeout; the earlier A04 failure was not reproduced.",
        )
    if long_default:
        return (
            "YUYV_STARTUP_LATENCY",
            "YUYV failed the normal timeout but produced frames with a longer first-frame timeout.",
        )
    if long_no_trigger:
        return (
            "YUYV_TRIGGER_CONFIG_INTERACTION",
            "YUYV produced frames only when Bividi did not force free-run trigger mode.",
        )
    return (
        "YUYV_NO_BUFFER_UPSTREAM",
        "MJPEG remained healthy while every YUYV raw-grab attempt returned no usable frame. The failure is before OpenCV/Bividi YUYV normalization; investigate SDK mode availability, firmware/UVC behavior, and actual host-link bandwidth separately.",
    )


def render_report(
    *,
    root: Path,
    probe_log: Path,
    modes: dict[str, int],
    usb_bcd: str | None,
    attempts: dict[str, Attempt],
    classification: str,
    conclusion: str,
    yuyv_fps: float,
) -> str:
    payload_bytes = 4000 * 1200 * 2
    payload_bytes_s = payload_bytes * yuyv_fps
    payload_mib_s = payload_bytes_s / (1024 * 1024)
    payload_gbit_s = payload_bytes_s * 8 / 1_000_000_000

    lines = [
        "# DECXIN AR0234 YUYV Diagnostic Report",
        "",
        f"- Created: `{utc_now()}`",
        f"- Host: `{socket.gethostname()}` / `{platform.platform()}`",
        f"- Classification: **{classification}**",
        f"- Probe log: `{probe_log}`",
        f"- SDK USB BCD field: `{usb_bcd or 'not reported by current probe binary'}`",
        f"- Discovered modes: `{json.dumps(modes, sort_keys=True)}`",
        "",
        "## Result",
        "",
        conclusion,
        "",
        "## Attempt matrix",
        "",
        "| Attempt | Purpose | RC | Frames | Sequence | Evidence |",
        "|---|---|---:|---:|---|---|",
    ]
    for attempt in attempts.values():
        seq = "-" if attempt.first_sequence is None else f"{attempt.first_sequence}->{attempt.last_sequence}"
        evidence = attempt.stderr_summary or "raw frames received"
        lines.append(
            f"| {attempt.name} | {attempt.purpose} | {attempt.return_code} | {attempt.frames} | {seq} | {evidence} |"
        )
    lines += [
        "",
        "## YUYV payload-rate context",
        "",
        f"For 4000x1200 packed YUYV, one frame is `{payload_bytes:,}` bytes. At the advertised `{yuyv_fps:g} fps`, the uncompressed payload alone is approximately `{payload_mib_s:.2f} MiB/s` / `{payload_gbit_s:.3f} Gbit/s` before protocol overhead.",
        "",
        "This calculation is a required payload rate only. It does **not** establish the negotiated USB speed. The SDK `bcdUSB` field is also device-descriptor provenance, not by itself proof of the negotiated link speed.",
        "",
        "## Interpretation boundary",
        "",
        "- `NORI_E_NOBUFF` / `timeout/no-buffer` occurs at raw acquisition, before OpenCV conversion or DECXIN metadata decoding.",
        "- An advertised mode is not automatically proven streamable on the current host/port/firmware combination.",
        "- If all YUYV raw attempts fail while MJPEG controls pass, A05 should be considered blocked by A04 rather than a second independent decode defect.",
        "- Determine negotiated USB link speed with an OS/USB topology tool or equivalent independent evidence before attributing the failure to bandwidth.",
        "",
        f"Artifacts: `{root}`",
        "",
    ]
    return "\n".join(lines)


def self_test() -> int:
    probe = """Nori devices: 1\n  USB BCD:      0x0300\n    0: 4000x1200@60  mjpeg  raw=0x47504a4d\n    1: 4000x1200@30  yuyv  raw=0x32595559\n"""
    assert parse_modes(probe) == {"mjpeg": 0, "yuyv": 1}
    assert parse_usb_bcd(probe) == "0x0300"
    out = "frame sequence=1 bytes=9600000 host_ns=1 actual=4000x1200@30 yuyv\n"
    assert parse_grab(out) == (1, 1, 1, [9600000])
    print("AR0234 YUYV diagnostic self-test: PASS")
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Diagnose AR0234/Nori YUYV raw no-buffer behavior.")
    p.add_argument("--build-dir", type=Path, default=Path("build-nori-opencv/Release"))
    p.add_argument("--device", type=int, default=0)
    p.add_argument("--mjpeg-mode", type=int)
    p.add_argument("--yuyv-mode", type=int)
    p.add_argument("--normal-timeout-ms", type=int, default=2000)
    p.add_argument("--long-timeout-ms", type=int, default=10000)
    p.add_argument("--output-dir", type=Path, default=Path("artifacts/physical/nori/yuyv-diagnostic"))
    p.add_argument("--session-id", default=None)
    p.add_argument("--self-test", action="store_true")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.self_test:
        return self_test()

    session = args.session_id or default_session()
    root = args.output_dir / session
    root.mkdir(parents=True, exist_ok=False)

    probe = str((args.build_dir / exe_name("bividi-nori-probe")).resolve())
    grab = str((args.build_dir / exe_name("bividi-nori-grab")).resolve())
    probe_cp = subprocess.run(probe, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace")
    probe_log = root / "D00_probe.log"
    probe_log.write_text(probe_cp.stdout + probe_cp.stderr, encoding="utf-8")
    if probe_cp.returncode != 0:
        print(f"probe failed; see {probe_log}", file=sys.stderr)
        return 3

    modes = parse_modes(probe_cp.stdout)
    mjpeg_mode = args.mjpeg_mode if args.mjpeg_mode is not None else modes.get("mjpeg")
    yuyv_mode = args.yuyv_mode if args.yuyv_mode is not None else modes.get("yuyv")
    if mjpeg_mode is None or yuyv_mode is None:
        print("4000x1200 MJPEG/YUYV modes were not both discovered", file=sys.stderr)
        return 4

    yuyv_match = re.search(
        rf"^\s*{yuyv_mode}:\s+4000x1200@([0-9.]+)\s+yuyv",
        probe_cp.stdout,
        re.MULTILINE,
    )
    yuyv_fps = float(yuyv_match.group(1)) if yuyv_match else 30.0

    attempts = {
        "D01_mjpeg_pre": Attempt(
            "D01_mjpeg_pre", "healthy MJPEG control before YUYV tests",
            make_grab(grab, device=args.device, mode=mjpeg_mode, frames=10, timeout_ms=args.normal_timeout_ms),
        ),
        "D02_yuyv_short": Attempt(
            "D02_yuyv_short", "YUYV with normal first-frame timeout",
            make_grab(grab, device=args.device, mode=yuyv_mode, frames=3, timeout_ms=args.normal_timeout_ms),
        ),
        "D03_yuyv_long": Attempt(
            "D03_yuyv_long", "YUYV with extended first-frame timeout",
            make_grab(grab, device=args.device, mode=yuyv_mode, frames=3, timeout_ms=args.long_timeout_ms),
        ),
        "D04_yuyv_no_trigger": Attempt(
            "D04_yuyv_no_trigger", "YUYV without forcing free-run trigger configuration",
            make_grab(grab, device=args.device, mode=yuyv_mode, frames=3, timeout_ms=args.long_timeout_ms, no_trigger_config=True),
        ),
        "D05_mjpeg_post": Attempt(
            "D05_mjpeg_post", "healthy MJPEG control after YUYV tests",
            make_grab(grab, device=args.device, mode=mjpeg_mode, frames=10, timeout_ms=args.normal_timeout_ms),
        ),
    }

    for attempt in attempts.values():
        print(f"[{attempt.name}] {attempt.purpose}")
        run_attempt(root, attempt)
        print(f"  rc={attempt.return_code} frames={attempt.frames} stderr={attempt.stderr_summary or '-'}")

    classification, conclusion = classify(attempts)
    report = render_report(
        root=root,
        probe_log=probe_log,
        modes=modes,
        usb_bcd=parse_usb_bcd(probe_cp.stdout),
        attempts=attempts,
        classification=classification,
        conclusion=conclusion,
        yuyv_fps=yuyv_fps,
    )
    report_path = root / "report.md"
    report_path.write_text(report, encoding="utf-8")

    machine = {
        "schema": SCHEMA,
        "created_utc": utc_now(),
        "classification": classification,
        "conclusion": conclusion,
        "host": {"hostname": socket.gethostname(), "platform": platform.platform()},
        "device": args.device,
        "modes": modes,
        "usb_bcd": parse_usb_bcd(probe_cp.stdout),
        "advertised_yuyv_fps": yuyv_fps,
        "yuyv_payload_bytes_per_frame": 4000 * 1200 * 2,
        "attempts": [asdict(item) | {"passed": item.passed} for item in attempts.values()],
        "report": str(report_path),
    }
    json_path = root / "result.json"
    json_path.write_text(json.dumps(machine, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"classification: {classification}")
    print(f"report: {report_path}")
    print(f"result: {json_path}")
    return 0 if classification in {"YUYV_FUNCTIONAL", "YUYV_STARTUP_LATENCY", "YUYV_TRIGGER_CONFIG_INTERACTION"} else 7


if __name__ == "__main__":
    raise SystemExit(main())
