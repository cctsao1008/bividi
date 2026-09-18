from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import quote

PROFILE = "bividi.sensor_observation.mcap.v1"
ENVELOPE_SCHEMA = "bividi.mcap.sensor_observation.v1"
CONTRACT_VERSION = 1
OBSERVATION_TOPIC = "/bividi/observation"
IMAGE_ENCODING = "application/x-bividi-packed-image-v1"
TOOL_VERSION = "1"
UINT32_MAX = (1 << 32) - 1
UINT64_MAX = (1 << 64) - 1
INT32_MIN = -(1 << 31)
INT32_MAX = (1 << 31) - 1

_JSON_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": ENVELOPE_SCHEMA,
    "type": "object",
    "required": [
        "schema",
        "mcap_ordinal",
        "contract_version",
        "source_id",
        "evidence",
        "source_state",
        "validity",
        "sequence",
        "sequence_present",
        "continuity_epoch",
        "continuity",
        "timing",
        "calibration",
        "configuration_revision",
        "cameras",
        "imu",
        "stereo_pairs",
    ],
    "properties": {
        "schema": {"const": ENVELOPE_SCHEMA},
        "mcap_ordinal": {"type": "integer", "minimum": 0},
        "contract_version": {"const": CONTRACT_VERSION},
        "source_id": {"type": "string", "minLength": 1},
        "evidence": {"enum": ["unknown", "synthetic", "measured", "imported"]},
        "source_state": {"enum": ["available", "disconnected", "error"]},
        "validity": {"enum": ["valid", "degraded", "invalid"]},
        "sequence": {"type": "integer", "minimum": 0},
        "sequence_present": {"type": "boolean"},
        "continuity_epoch": {"type": "integer", "minimum": 0},
        "continuity": {"enum": ["continuous", "discontinuity", "reinitialized"]},
        "timing": {"type": "object"},
        "calibration": {"type": "object"},
        "configuration_revision": {"type": "string"},
        "cameras": {"type": "array"},
        "imu": {"type": "array"},
        "stereo_pairs": {"type": "array"},
    },
    "additionalProperties": False,
}


class McapAdapterError(ValueError):
    pass


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise McapAdapterError(f"{label} must be an object")
    return value


def _strict_keys(value: Mapping[str, Any], label: str, required: set[str]) -> None:
    missing = required.difference(value)
    extra = set(value).difference(required)
    if missing:
        raise McapAdapterError(f"{label} missing keys: {sorted(missing)}")
    if extra:
        raise McapAdapterError(f"{label} has unsupported keys: {sorted(extra)}")


def _string(value: Any, label: str, *, nonempty: bool = False) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        raise McapAdapterError(f"{label} must be {'non-empty ' if nonempty else ''}string")
    return value


def _bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise McapAdapterError(f"{label} must be boolean")
    return value


def _uint(value: Any, label: str, maximum: int = UINT64_MAX) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > maximum:
        raise McapAdapterError(f"{label} must be integer in [0, {maximum}]")
    return value


def _int32(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not (INT32_MIN <= value <= INT32_MAX):
        raise McapAdapterError(f"{label} must be int32")
    return value


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise McapAdapterError(f"{label} must be numeric")
    return float(value)


def _enum(value: Any, label: str, allowed: set[str]) -> str:
    text = _string(value, label)
    if text not in allowed:
        raise McapAdapterError(f"{label} unsupported value: {text!r}")
    return text


def _vector3(value: Any, label: str, parser) -> list[Any]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise McapAdapterError(f"{label} must have exactly 3 elements")
    return [parser(item, f"{label}[{i}]") for i, item in enumerate(value)]


def _timepoint(value: Any, label: str) -> dict[str, Any]:
    src = _require_mapping(value, label)
    required = {"ticks", "unit", "domain", "clock_id", "present"}
    _strict_keys(src, label, required)
    result = {
        "ticks": _uint(src["ticks"], f"{label}.ticks"),
        "unit": _enum(src["unit"], f"{label}.unit", {"unknown", "nanoseconds", "microseconds"}),
        "domain": _enum(src["domain"], f"{label}.domain", {"unknown", "host_monotonic", "device", "replay"}),
        "clock_id": _string(src["clock_id"], f"{label}.clock_id"),
        "present": _bool(src["present"], f"{label}.present"),
    }
    if result["present"] and (
        result["unit"] == "unknown" or result["domain"] == "unknown" or not result["clock_id"]
    ):
        raise McapAdapterError(f"{label} present timestamp lacks unit/domain/clock_id")
    return result


def _raw_timestamp(value: Any, label: str) -> dict[str, Any]:
    src = _require_mapping(value, label)
    required = {"raw_ticks", "bit_width", "unit", "clock_id", "present"}
    _strict_keys(src, label, required)
    result = {
        "raw_ticks": _uint(src["raw_ticks"], f"{label}.raw_ticks"),
        "bit_width": _uint(src["bit_width"], f"{label}.bit_width", 64),
        "unit": _enum(src["unit"], f"{label}.unit", {"unknown", "nanoseconds", "microseconds"}),
        "clock_id": _string(src["clock_id"], f"{label}.clock_id"),
        "present": _bool(src["present"], f"{label}.present"),
    }
    if result["present"] and (
        result["bit_width"] == 0 or result["unit"] == "unknown" or not result["clock_id"]
    ):
        raise McapAdapterError(f"{label} present raw timestamp lacks bit_width/unit/clock_id")
    return result


def _exposure(value: Any, label: str) -> dict[str, Any]:
    src = _require_mapping(value, label)
    required = {"start", "end", "raw_start", "raw_end"}
    _strict_keys(src, label, required)
    return {
        "start": _timepoint(src["start"], f"{label}.start"),
        "end": _timepoint(src["end"], f"{label}.end"),
        "raw_start": _raw_timestamp(src["raw_start"], f"{label}.raw_start"),
        "raw_end": _raw_timestamp(src["raw_end"], f"{label}.raw_end"),
    }


def _image(value: Any, label: str, *, require_data: bool) -> dict[str, Any]:
    src = _require_mapping(value, label)
    keys = {"width", "height", "row_stride", "bytes_per_pixel", "pixel_format"}
    if require_data:
        keys.add("data")
    _strict_keys(src, label, keys)
    width = _uint(src["width"], f"{label}.width", UINT32_MAX)
    height = _uint(src["height"], f"{label}.height", UINT32_MAX)
    bpp = _uint(src["bytes_per_pixel"], f"{label}.bytes_per_pixel", UINT32_MAX)
    stride = _uint(src["row_stride"], f"{label}.row_stride", UINT32_MAX)
    pixel_format = _enum(src["pixel_format"], f"{label}.pixel_format", {"gray8", "bgr24"})
    if width == 0 or height == 0 or bpp == 0:
        raise McapAdapterError(f"{label} geometry must be non-zero")
    expected_bpp = 1 if pixel_format == "gray8" else 3
    if bpp != expected_bpp:
        raise McapAdapterError(f"{label}.bytes_per_pixel does not match {pixel_format}")
    row_bytes = width * bpp
    if stride != row_bytes:
        raise McapAdapterError(
            f"{label} MCAP v1 supports only tightly packed images: row_stride={stride}, row_bytes={row_bytes}"
        )
    result = {
        "width": width,
        "height": height,
        "row_stride": stride,
        "bytes_per_pixel": bpp,
        "pixel_format": pixel_format,
    }
    if require_data:
        data = src["data"]
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise McapAdapterError(f"{label}.data must be bytes-like")
        payload = bytes(data)
        expected_size = stride * height
        if len(payload) != expected_size:
            raise McapAdapterError(
                f"{label}.data length {len(payload)} does not match tightly packed image size {expected_size}"
            )
        result["data"] = payload
    return result


def canonicalize_observation(value: Mapping[str, Any], *, require_image_data: bool = True) -> dict[str, Any]:
    src = _require_mapping(value, "observation")
    required = {
        "contract_version",
        "source_id",
        "evidence",
        "source_state",
        "validity",
        "sequence",
        "sequence_present",
        "continuity_epoch",
        "continuity",
        "timing",
        "calibration",
        "configuration_revision",
        "cameras",
        "imu",
        "stereo_pairs",
    }
    _strict_keys(src, "observation", required)
    contract_version = _uint(src["contract_version"], "observation.contract_version", UINT32_MAX)
    if contract_version != CONTRACT_VERSION:
        raise McapAdapterError(f"unsupported observation contract version: {contract_version}")

    timing = _require_mapping(src["timing"], "observation.timing")
    _strict_keys(timing, "observation.timing", {"host_receive", "replay_schedule"})
    calibration = _require_mapping(src["calibration"], "observation.calibration")
    _strict_keys(calibration, "observation.calibration", {"stereo", "imu", "camera_imu"})

    cameras_raw = src["cameras"]
    if not isinstance(cameras_raw, (list, tuple)):
        raise McapAdapterError("observation.cameras must be an array")
    cameras: list[dict[str, Any]] = []
    seen_streams: set[str] = set()
    for index, item in enumerate(cameras_raw):
        label = f"observation.cameras[{index}]"
        camera = _require_mapping(item, label)
        _strict_keys(camera, label, {"stream_id", "image", "frame_time", "exposure", "validity"})
        stream_id = _string(camera["stream_id"], f"{label}.stream_id", nonempty=True)
        if stream_id in seen_streams:
            raise McapAdapterError(f"duplicate camera stream_id: {stream_id}")
        seen_streams.add(stream_id)
        cameras.append(
            {
                "stream_id": stream_id,
                "image": _image(camera["image"], f"{label}.image", require_data=require_image_data),
                "frame_time": _timepoint(camera["frame_time"], f"{label}.frame_time"),
                "exposure": _exposure(camera["exposure"], f"{label}.exposure"),
                "validity": _enum(camera["validity"], f"{label}.validity", {"valid", "degraded", "invalid"}),
            }
        )

    imu_raw = src["imu"]
    if not isinstance(imu_raw, (list, tuple)):
        raise McapAdapterError("observation.imu must be an array")
    imu: list[dict[str, Any]] = []
    for index, item in enumerate(imu_raw):
        label = f"observation.imu[{index}]"
        sample = _require_mapping(item, label)
        _strict_keys(
            sample,
            label,
            {
                "sensor_id",
                "sample_time",
                "raw_time",
                "accel_raw_counts",
                "gyro_raw_counts",
                "raw_valid",
                "accel_m_s2",
                "gyro_rad_s",
                "si_valid",
                "validity",
            },
        )
        imu.append(
            {
                "sensor_id": _string(sample["sensor_id"], f"{label}.sensor_id", nonempty=True),
                "sample_time": _timepoint(sample["sample_time"], f"{label}.sample_time"),
                "raw_time": _raw_timestamp(sample["raw_time"], f"{label}.raw_time"),
                "accel_raw_counts": _vector3(sample["accel_raw_counts"], f"{label}.accel_raw_counts", _int32),
                "gyro_raw_counts": _vector3(sample["gyro_raw_counts"], f"{label}.gyro_raw_counts", _int32),
                "raw_valid": _bool(sample["raw_valid"], f"{label}.raw_valid"),
                "accel_m_s2": _vector3(sample["accel_m_s2"], f"{label}.accel_m_s2", _number),
                "gyro_rad_s": _vector3(sample["gyro_rad_s"], f"{label}.gyro_rad_s", _number),
                "si_valid": _bool(sample["si_valid"], f"{label}.si_valid"),
                "validity": _enum(sample["validity"], f"{label}.validity", {"valid", "degraded", "invalid"}),
            }
        )

    pairs_raw = src["stereo_pairs"]
    if not isinstance(pairs_raw, (list, tuple)):
        raise McapAdapterError("observation.stereo_pairs must be an array")
    stereo_pairs: list[dict[str, Any]] = []
    for index, item in enumerate(pairs_raw):
        label = f"observation.stereo_pairs[{index}]"
        pair = _require_mapping(item, label)
        _strict_keys(pair, label, {"pair_id", "synchronization"})
        stereo_pairs.append(
            {
                "pair_id": _string(pair["pair_id"], f"{label}.pair_id", nonempty=True),
                "synchronization": _enum(
                    pair["synchronization"],
                    f"{label}.synchronization",
                    {"unknown", "synchronized", "unsynchronized", "degraded"},
                ),
            }
        )

    return {
        "contract_version": contract_version,
        "source_id": _string(src["source_id"], "observation.source_id", nonempty=True),
        "evidence": _enum(src["evidence"], "observation.evidence", {"unknown", "synthetic", "measured", "imported"}),
        "source_state": _enum(src["source_state"], "observation.source_state", {"available", "disconnected", "error"}),
        "validity": _enum(src["validity"], "observation.validity", {"valid", "degraded", "invalid"}),
        "sequence": _uint(src["sequence"], "observation.sequence"),
        "sequence_present": _bool(src["sequence_present"], "observation.sequence_present"),
        "continuity_epoch": _uint(src["continuity_epoch"], "observation.continuity_epoch"),
        "continuity": _enum(src["continuity"], "observation.continuity", {"continuous", "discontinuity", "reinitialized"}),
        "timing": {
            "host_receive": _timepoint(timing["host_receive"], "observation.timing.host_receive"),
            "replay_schedule": _timepoint(timing["replay_schedule"], "observation.timing.replay_schedule"),
        },
        "calibration": {
            "stereo": _string(calibration["stereo"], "observation.calibration.stereo"),
            "imu": _string(calibration["imu"], "observation.calibration.imu"),
            "camera_imu": _string(calibration["camera_imu"], "observation.calibration.camera_imu"),
        },
        "configuration_revision": _string(src["configuration_revision"], "observation.configuration_revision"),
        "cameras": cameras,
        "imu": imu,
        "stereo_pairs": stereo_pairs,
    }


def _camera_topic(source_id: str, stream_id: str) -> str:
    return f"/bividi/source/{quote(source_id, safe='')}/camera/{quote(stream_id, safe='')}"


def _container_time_ns(ordinal: int) -> int:
    return ordinal * 1_000_000


def _import_mcap():
    try:
        from mcap.reader import make_reader
        from mcap.writer import CompressionType, Writer
    except ImportError as exc:
        raise McapAdapterError(
            "MCAP support requires the optional dependency. Install with: pip install -e '.[mcap]'"
        ) from exc
    return make_reader, CompressionType, Writer


def write_observations(path: str | Path, observations: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    _, CompressionType, Writer = _import_mcap()
    destination = Path(path)
    if destination.exists():
        raise McapAdapterError(f"refusing to overwrite existing MCAP: {destination}")
    canonical = [canonicalize_observation(item) for item in observations]
    if not canonical:
        raise McapAdapterError("at least one observation is required")
    if len(canonical) - 1 > UINT32_MAX:
        raise McapAdapterError("MCAP v1 adapter cannot encode more than 2^32 observations")

    schema_bytes = json.dumps(_JSON_SCHEMA, sort_keys=True, separators=(",", ":")).encode("utf-8")
    camera_channels: dict[tuple[str, str], tuple[int, str]] = {}
    source_ids = sorted({item["source_id"] for item in canonical})

    with destination.open("wb") as stream:
        writer = Writer(stream, compression=CompressionType.NONE)
        writer.start(profile=PROFILE, library=f"bividi-mcap-adapter/{TOOL_VERSION}")
        schema_id = writer.register_schema(name=ENVELOPE_SCHEMA, encoding="jsonschema", data=schema_bytes)
        observation_channel = writer.register_channel(
            schema_id=schema_id,
            topic=OBSERVATION_TOPIC,
            message_encoding="json",
            metadata={"bividi.contract_version": str(CONTRACT_VERSION)},
        )
        writer.add_metadata(
            name="bividi.mcap.contract",
            data={
                "profile": PROFILE,
                "observation_contract_version": str(CONTRACT_VERSION),
                "observation_envelope_schema": ENVELOPE_SCHEMA,
                "container_log_time": "deterministic container ordering clock only; not sensor or host time",
                "camera_payload": "tightly packed image bytes; source timestamps remain in observation envelope",
            },
        )

        for ordinal, observation in enumerate(canonical):
            envelope = copy.deepcopy(observation)
            envelope["schema"] = ENVELOPE_SCHEMA
            envelope["mcap_ordinal"] = ordinal
            envelope_cameras: list[dict[str, Any]] = []
            container_time = _container_time_ns(ordinal)

            for camera in observation["cameras"]:
                stream_id = camera["stream_id"]
                key = (observation["source_id"], stream_id)
                if key not in camera_channels:
                    topic = _camera_topic(*key)
                    channel_id = writer.register_channel(
                        schema_id=0,
                        topic=topic,
                        message_encoding=IMAGE_ENCODING,
                        metadata={
                            "bividi.source_id": observation["source_id"],
                            "bividi.stream_id": stream_id,
                            "bividi.payload_contract": "tight_rows_v1",
                        },
                    )
                    camera_channels[key] = (channel_id, topic)
                channel_id, topic = camera_channels[key]
                payload = camera["image"]["data"]
                writer.add_message(
                    channel_id=channel_id,
                    log_time=container_time,
                    publish_time=container_time,
                    sequence=ordinal,
                    data=payload,
                )
                camera_envelope = copy.deepcopy(camera)
                del camera_envelope["image"]["data"]
                camera_envelope["image"]["payload_topic"] = topic
                camera_envelope["image"]["payload_sequence"] = ordinal
                camera_envelope["image"]["payload_size_bytes"] = len(payload)
                camera_envelope["image"]["payload_sha256"] = hashlib.sha256(payload).hexdigest()
                envelope_cameras.append(camera_envelope)

            envelope["cameras"] = envelope_cameras
            writer.add_message(
                channel_id=observation_channel,
                log_time=container_time,
                publish_time=container_time,
                sequence=ordinal,
                data=json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            )

        writer.finish()

    return {
        "schema": "bividi.mcap.export.v1",
        "profile": PROFILE,
        "path": str(destination),
        "observations": len(canonical),
        "camera_channels": len(camera_channels),
        "source_ids": source_ids,
        "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        "timing_note": "MCAP log/publish time is a deterministic container-order clock; all producer clocks stay in the payload.",
    }


def _decode_envelope(data: bytes, sequence: int) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise McapAdapterError(f"invalid observation JSON at MCAP sequence {sequence}: {exc}") from exc
    src = _require_mapping(value, f"MCAP observation {sequence}")
    required_top = set(_JSON_SCHEMA["required"])
    _strict_keys(src, f"MCAP observation {sequence}", required_top)
    if src.get("schema") != ENVELOPE_SCHEMA:
        raise McapAdapterError(f"MCAP observation {sequence} has unsupported schema {src.get('schema')!r}")
    ordinal = _uint(src["mcap_ordinal"], f"MCAP observation {sequence}.mcap_ordinal", UINT32_MAX)
    if ordinal != sequence:
        raise McapAdapterError(f"MCAP observation ordinal {ordinal} does not match message sequence {sequence}")
    return dict(src)


def read_observations(path: str | Path) -> list[dict[str, Any]]:
    make_reader, _, _ = _import_mcap()
    source = Path(path)
    if not source.is_file():
        raise McapAdapterError(f"MCAP file does not exist: {source}")

    payloads: dict[tuple[str, int], bytes] = {}
    envelopes: dict[int, dict[str, Any]] = {}
    with source.open("rb") as stream:
        reader = make_reader(stream, validate_crcs=True)
        header = reader.get_header()
        if header.profile != PROFILE:
            raise McapAdapterError(f"unsupported MCAP profile {header.profile!r}; expected {PROFILE!r}")
        for schema, channel, message in reader.iter_messages(log_time_order=False):
            if channel.topic == OBSERVATION_TOPIC:
                if channel.message_encoding != "json" or schema is None:
                    raise McapAdapterError("observation channel must use JSON with a schema")
                if schema.name != ENVELOPE_SCHEMA or schema.encoding != "jsonschema":
                    raise McapAdapterError("observation channel schema identity mismatch")
                if message.sequence in envelopes:
                    raise McapAdapterError(f"duplicate observation message sequence: {message.sequence}")
                envelopes[message.sequence] = _decode_envelope(message.data, message.sequence)
                continue
            if channel.message_encoding == IMAGE_ENCODING:
                key = (channel.topic, message.sequence)
                if key in payloads:
                    raise McapAdapterError(f"duplicate image payload for topic={channel.topic} sequence={message.sequence}")
                payloads[key] = bytes(message.data)

    if not envelopes:
        raise McapAdapterError("MCAP contains no Bividi observation messages")
    expected_ordinals = list(range(len(envelopes)))
    if sorted(envelopes) != expected_ordinals:
        raise McapAdapterError(
            f"observation ordinals must be contiguous from zero; found {sorted(envelopes)}"
        )

    result: list[dict[str, Any]] = []
    consumed_payloads: set[tuple[str, int]] = set()
    for ordinal in expected_ordinals:
        envelope = copy.deepcopy(envelopes[ordinal])
        cameras = envelope["cameras"]
        if not isinstance(cameras, list):
            raise McapAdapterError(f"MCAP observation {ordinal}.cameras must be an array")
        restored_cameras: list[dict[str, Any]] = []
        for index, camera_raw in enumerate(cameras):
            label = f"MCAP observation {ordinal}.cameras[{index}]"
            camera = _require_mapping(camera_raw, label)
            _strict_keys(camera, label, {"stream_id", "image", "frame_time", "exposure", "validity"})
            image_raw = _require_mapping(camera["image"], f"{label}.image")
            image_keys = {
                "width",
                "height",
                "row_stride",
                "bytes_per_pixel",
                "pixel_format",
                "payload_topic",
                "payload_sequence",
                "payload_size_bytes",
                "payload_sha256",
            }
            _strict_keys(image_raw, f"{label}.image", image_keys)
            topic = _string(image_raw["payload_topic"], f"{label}.image.payload_topic", nonempty=True)
            payload_sequence = _uint(
                image_raw["payload_sequence"], f"{label}.image.payload_sequence", UINT32_MAX
            )
            if payload_sequence != ordinal:
                raise McapAdapterError(f"{label} payload sequence does not match observation ordinal")
            key = (topic, payload_sequence)
            if key not in payloads:
                raise McapAdapterError(f"missing camera payload for topic={topic} sequence={payload_sequence}")
            payload = payloads[key]
            expected_size = _uint(
                image_raw["payload_size_bytes"], f"{label}.image.payload_size_bytes", UINT64_MAX
            )
            if len(payload) != expected_size:
                raise McapAdapterError(f"{label} payload size mismatch")
            expected_hash = _string(image_raw["payload_sha256"], f"{label}.image.payload_sha256", nonempty=True)
            if hashlib.sha256(payload).hexdigest() != expected_hash:
                raise McapAdapterError(f"{label} payload SHA-256 mismatch")
            restored_camera = copy.deepcopy(dict(camera))
            restored_camera["image"] = {
                "width": image_raw["width"],
                "height": image_raw["height"],
                "row_stride": image_raw["row_stride"],
                "bytes_per_pixel": image_raw["bytes_per_pixel"],
                "pixel_format": image_raw["pixel_format"],
                "data": payload,
            }
            restored_cameras.append(restored_camera)
            consumed_payloads.add(key)

        del envelope["schema"]
        del envelope["mcap_ordinal"]
        envelope["cameras"] = restored_cameras
        result.append(canonicalize_observation(envelope, require_image_data=True))

    unused = set(payloads).difference(consumed_payloads)
    if unused:
        raise McapAdapterError(f"MCAP contains unreferenced camera payloads: {sorted(unused)}")
    return result


def semantic_digest(observation: Mapping[str, Any]) -> str:
    canonical = canonicalize_observation(observation)

    def encode(value: Any) -> Any:
        if isinstance(value, bytes):
            return {"__bytes_sha256__": hashlib.sha256(value).hexdigest(), "size": len(value)}
        if isinstance(value, dict):
            return {key: encode(item) for key, item in value.items()}
        if isinstance(value, list):
            return [encode(item) for item in value]
        return value

    payload = json.dumps(encode(canonical), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
