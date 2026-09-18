from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "bividi.replay_artifact_fault_recipe.v1"
APPLICATION_SCHEMA = "bividi.replay_artifact_fault_application.v1"
UINT64_MAX = (1 << 64) - 1

_ACTIONS = {
    "delete_file",
    "truncate_file",
    "xor_byte",
    "replace_text",
    "replace_bytes_hex",
}
_EXPECTED = {
    "reject_artifact",
    "decode_failure",
    "schema_reject",
    "integrity_reject",
}


class ReplayArtifactFaultError(ValueError):
    pass


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReplayArtifactFaultError(f"{label} must be an object")
    return value


def _strict_keys(value: Mapping[str, Any], label: str, required: set[str], optional: set[str] | None = None) -> None:
    optional = optional or set()
    missing = required.difference(value)
    extra = set(value).difference(required | optional)
    if missing:
        raise ReplayArtifactFaultError(f"{label} missing keys: {sorted(missing)}")
    if extra:
        raise ReplayArtifactFaultError(f"{label} has unsupported keys: {sorted(extra)}")


def _string(value: Any, label: str, *, nonempty: bool = False) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        raise ReplayArtifactFaultError(f"{label} must be {'non-empty ' if nonempty else ''}string")
    return value


def _uint64(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise ReplayArtifactFaultError(f"{label} must be uint64")
    if isinstance(value, str):
        if not value or not value.isdigit():
            raise ReplayArtifactFaultError(f"{label} decimal string must contain digits only")
        parsed = int(value, 10)
    elif isinstance(value, int):
        parsed = value
    else:
        raise ReplayArtifactFaultError(f"{label} must be uint64 integer or decimal string")
    if not 0 <= parsed <= UINT64_MAX:
        raise ReplayArtifactFaultError(f"{label} must be in [0, {UINT64_MAX}]")
    return parsed


def _relative_target(value: Any, label: str) -> str:
    text = _string(value, label, nonempty=True)
    path = Path(text)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ReplayArtifactFaultError(f"{label} must be a normalized relative path without '.' or '..'")
    return path.as_posix()


def _validate_rule(value: Any, index: int) -> dict[str, Any]:
    label = f"recipe.rules[{index}]"
    src = _mapping(value, label)
    common = {"id", "target", "action", "expected_disposition"}
    action = _string(src.get("action"), f"{label}.action", nonempty=True)
    if action not in _ACTIONS:
        raise ReplayArtifactFaultError(f"{label}.action unsupported value: {action!r}")

    action_fields: dict[str, set[str]] = {
        "delete_file": set(),
        "truncate_file": {"size_bytes"},
        "xor_byte": {"offset", "mask"},
        "replace_text": {"old", "new"},
        "replace_bytes_hex": {"data_hex"},
    }
    _strict_keys(src, label, common | action_fields[action])

    expected = _string(src["expected_disposition"], f"{label}.expected_disposition", nonempty=True)
    if expected not in _EXPECTED:
        raise ReplayArtifactFaultError(
            f"{label}.expected_disposition unsupported value: {expected!r}"
        )

    result: dict[str, Any] = {
        "id": _string(src["id"], f"{label}.id", nonempty=True),
        "target": _relative_target(src["target"], f"{label}.target"),
        "action": action,
        "expected_disposition": expected,
    }
    if action == "truncate_file":
        result["size_bytes"] = _uint64(src["size_bytes"], f"{label}.size_bytes")
    elif action == "xor_byte":
        result["offset"] = _uint64(src["offset"], f"{label}.offset")
        mask = _uint64(src["mask"], f"{label}.mask")
        if not 1 <= mask <= 255:
            raise ReplayArtifactFaultError(f"{label}.mask must be in [1, 255]")
        result["mask"] = mask
    elif action == "replace_text":
        result["old"] = _string(src["old"], f"{label}.old", nonempty=True)
        result["new"] = _string(src["new"], f"{label}.new")
    elif action == "replace_bytes_hex":
        data_hex = _string(src["data_hex"], f"{label}.data_hex")
        if len(data_hex) % 2 != 0:
            raise ReplayArtifactFaultError(f"{label}.data_hex must contain an even number of hex digits")
        try:
            bytes.fromhex(data_hex)
        except ValueError as exc:
            raise ReplayArtifactFaultError(f"{label}.data_hex is not valid hex") from exc
        result["data_hex"] = data_hex.lower()
    return result


def validate_recipe(value: Any) -> dict[str, Any]:
    src = _mapping(value, "recipe")
    _strict_keys(src, "recipe", {"schema", "seed", "rules"})
    if src["schema"] != SCHEMA:
        raise ReplayArtifactFaultError(
            f"unsupported recipe schema {src['schema']!r}; expected {SCHEMA!r}"
        )
    seed = _uint64(src["seed"], "recipe.seed")
    raw_rules = src["rules"]
    if not isinstance(raw_rules, list) or not raw_rules:
        raise ReplayArtifactFaultError("recipe.rules must be a non-empty array")
    rules = [_validate_rule(item, index) for index, item in enumerate(raw_rules)]
    ids = [item["id"] for item in rules]
    if len(ids) != len(set(ids)):
        raise ReplayArtifactFaultError("recipe rule ids must be unique")
    return {"schema": SCHEMA, "seed": seed, "rules": rules}


def load_recipe(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReplayArtifactFaultError(f"cannot read artifact fault recipe {source}: {exc}") from exc
    return validate_recipe(value)


def recipe_sha256(recipe: Mapping[str, Any]) -> str:
    canonical = validate_recipe(recipe)
    data = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def tree_digest(root: str | Path) -> str:
    base = Path(root)
    if not base.is_dir():
        raise ReplayArtifactFaultError(f"tree digest root is not a directory: {base}")
    digest = hashlib.sha256()
    for path in sorted((item for item in base.rglob("*") if item.is_file()), key=lambda p: p.relative_to(base).as_posix()):
        relative = path.relative_to(base).as_posix().encode("utf-8")
        payload = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(hashlib.sha256(payload).digest())
    return digest.hexdigest()


def _contained_file(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve(strict=False)
    root_resolved = root.resolve(strict=True)
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise ReplayArtifactFaultError(f"fault target escapes output root: {relative}") from exc
    if not candidate.is_file():
        raise ReplayArtifactFaultError(f"fault target is not an existing regular file: {relative}")
    return candidate


def _apply_rule(root: Path, rule: Mapping[str, Any]) -> dict[str, Any]:
    target = _contained_file(root, str(rule["target"]))
    before = target.read_bytes()
    before_hash = hashlib.sha256(before).hexdigest()
    action = str(rule["action"])

    if action == "delete_file":
        target.unlink()
        after = None
    elif action == "truncate_file":
        size = int(rule["size_bytes"])
        if size > len(before):
            raise ReplayArtifactFaultError(
                f"rule {rule['id']} truncate size {size} exceeds current file size {len(before)}"
            )
        after = before[:size]
        target.write_bytes(after)
    elif action == "xor_byte":
        offset = int(rule["offset"])
        if offset >= len(before):
            raise ReplayArtifactFaultError(
                f"rule {rule['id']} xor offset {offset} is outside file size {len(before)}"
            )
        mutated = bytearray(before)
        mutated[offset] ^= int(rule["mask"])
        after = bytes(mutated)
        target.write_bytes(after)
    elif action == "replace_text":
        try:
            text = before.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ReplayArtifactFaultError(
                f"rule {rule['id']} target is not UTF-8 text: {rule['target']}"
            ) from exc
        old = str(rule["old"])
        count = text.count(old)
        if count != 1:
            raise ReplayArtifactFaultError(
                f"rule {rule['id']} replace_text requires exactly one match, found {count}"
            )
        after = text.replace(old, str(rule["new"]), 1).encode("utf-8")
        target.write_bytes(after)
    elif action == "replace_bytes_hex":
        after = bytes.fromhex(str(rule["data_hex"]))
        target.write_bytes(after)
    else:  # validate_recipe makes this unreachable.
        raise ReplayArtifactFaultError(f"unsupported action: {action}")

    return {
        "id": rule["id"],
        "target": rule["target"],
        "action": action,
        "expected_disposition": rule["expected_disposition"],
        "before_size_bytes": len(before),
        "before_sha256": before_hash,
        "after_size_bytes": None if after is None else len(after),
        "after_sha256": None if after is None else hashlib.sha256(after).hexdigest(),
    }


def apply_recipe(source_root: str | Path, output_root: str | Path, recipe: Mapping[str, Any]) -> dict[str, Any]:
    source = Path(source_root)
    output = Path(output_root)
    canonical = validate_recipe(recipe)
    if not source.is_dir():
        raise ReplayArtifactFaultError(f"source root is not a directory: {source}")
    if output.exists():
        raise ReplayArtifactFaultError(f"refusing to overwrite output root: {output}")

    source_digest = tree_digest(source)
    shutil.copytree(source, output)
    try:
        applications = [_apply_rule(output, rule) for rule in canonical["rules"]]
        output_digest = tree_digest(output)
    except Exception:
        shutil.rmtree(output, ignore_errors=True)
        raise

    return {
        "schema": APPLICATION_SCHEMA,
        "recipe_schema": SCHEMA,
        "recipe_sha256": recipe_sha256(canonical),
        "seed": canonical["seed"],
        "source_tree_sha256": source_digest,
        "output_tree_sha256": output_digest,
        "rules_applied": applications,
        "source_unchanged_after_copy": tree_digest(source) == source_digest,
    }
