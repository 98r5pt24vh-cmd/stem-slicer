#!/usr/bin/env python3
"""Persistent NDJSON adapter between Electron and the headless Slicer engines."""

from __future__ import annotations

from array import array
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import redirect_stdout
from dataclasses import asdict, replace
from functools import lru_cache
from itertools import combinations
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import random
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import unicodedata
from urllib.parse import quote
from urllib.request import Request, urlopen
import uuid


SOURCE_ROOT = Path(
    os.environ.get(
        "STEM_SLICER_SOURCE_ROOT",
        "/Users/nrgy/Documents/Stem Slicer Repository",
    )
).expanduser().resolve()
if not SOURCE_ROOT.is_dir():
    raise SystemExit(f"Stem Slicer source root is unavailable: {SOURCE_ROOT}")
sys.path.insert(0, str(SOURCE_ROOT))


def _default_accepted_cache_root() -> Path:
    if os.name == "nt":
        cache_base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        cache_base = Path.home() / "Library" / "Caches"
    else:
        cache_base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return cache_base / "Stem Slicer" / "1.9"


ACCEPTED_CACHE_ROOT = Path(
    os.environ.get("STEM_SLICER_ACCEPTED_CACHE_ROOT", _default_accepted_cache_root())
).expanduser().resolve()

_write_lock = threading.Lock()
_analyzer = None
_classifier = None
_midi_converter = None
_generation_sessions: dict[str, dict] = {}
_generation_catalog_cache: dict[tuple[object, ...], dict] = {}
_verified_cloud_cache: dict[str, tuple[int, int, str]] = {}
_verified_cloud_cache_lock = threading.Lock()
_VERIFIED_CLOUD_CACHE_LIMIT = 8_192
_PRIMARY_PRODUCER = "+NRGY"
_COMPACT_KEY = re.compile(r"^[A-G](?:#|b|♯|♭)?(?:(?:m|min|minor|maj|major))?$", re.IGNORECASE)
_MODE_TOKEN = re.compile(r"^(?:m|min|minor|maj|major)$", re.IGNORECASE)


def _hidden_process_kwargs() -> dict[str, object]:
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "startupinfo": startupinfo,
        "creationflags": subprocess.CREATE_NO_WINDOW,
    }


def _key_token_count(tokens: list[str], index: int) -> int:
    token = tokens[index] if 0 <= index < len(tokens) else ""
    if not _COMPACT_KEY.fullmatch(token):
        return 0
    tonic_only = re.fullmatch(r"[A-G](?:#|b|♯|♭)?", token, re.IGNORECASE)
    following = tokens[index + 1] if index + 1 < len(tokens) else ""
    return 2 if tonic_only and _MODE_TOKEN.fullmatch(following) else 1


def _normalise_primary_producer(value) -> str:
    return str(value or "").strip() or _PRIMARY_PRODUCER


def _producer_identity_key(value) -> str:
    normalized = " ".join(unicodedata.normalize("NFKC", str(value or "")).strip().split())
    return normalized.removeprefix("@").casefold()


def _producer_identity_signature(values) -> tuple[tuple[str, tuple[str, ...]], ...]:
    identities = []
    for raw_identity in values or ():
        if not isinstance(raw_identity, dict):
            continue
        canonical_name = " ".join(str(raw_identity.get("canonicalName") or "").strip().split())
        if not canonical_name:
            continue
        aliases = tuple(
            " ".join(str(alias or "").strip().split())
            for alias in raw_identity.get("aliases") or ()
            if str(alias or "").strip()
        )
        identities.append((canonical_name, aliases))
    return tuple(identities)


@lru_cache(maxsize=64)
def _producer_identity_resolver(
    identities: tuple[tuple[str, tuple[str, ...]], ...],
    primary_producer: str,
) -> tuple[dict[str, str], tuple[tuple[str, int], ...]]:
    primary = _normalise_primary_producer(primary_producer)
    claims: dict[str, set[str]] = {}
    canonical_names: dict[str, str] = {}

    def add_claim(alias, canonical_name) -> None:
        alias_key = _producer_identity_key(alias)
        canonical = str(canonical_name or "").strip()
        if canonical.casefold() == primary.casefold():
            canonical = primary
        canonical_key = _producer_identity_key(canonical)
        if not alias_key or not canonical_key:
            return
        canonical_names[canonical_key] = canonical
        claims.setdefault(alias_key, set()).add(canonical_key)

    add_claim(primary, primary)
    for canonical_name, aliases in identities:
        add_claim(canonical_name, canonical_name)
        for alias in aliases:
            add_claim(alias, canonical_name)

    resolved = {
        alias_key: canonical_names[next(iter(owners))]
        for alias_key, owners in claims.items()
        if len(owners) == 1 and next(iter(owners)) in canonical_names
    }
    patterns = tuple(
        sorted(
            ((alias_key, len(alias_key.split(" "))) for alias_key in resolved),
            key=lambda item: (-item[1], -len(item[0])),
        )
    )
    return resolved, patterns


def _canonical_producer(value, identities=(), primary_producer: str = _PRIMARY_PRODUCER) -> str:
    primary = _normalise_primary_producer(primary_producer)
    normalized = " ".join(str(value or "").strip().split())
    resolved, _patterns = _producer_identity_resolver(tuple(identities), primary)
    return resolved.get(_producer_identity_key(normalized), primary if normalized.casefold() == primary.casefold() else normalized)


def _parse_producer_tokens(tokens: list[str], identities=(), primary_producer: str = _PRIMARY_PRODUCER) -> list[str]:
    resolved, patterns = _producer_identity_resolver(tuple(identities), _normalise_primary_producer(primary_producer))
    credits = []
    index = 0
    while index < len(tokens):
        match = next(
            (
                (alias_key, token_count)
                for alias_key, token_count in patterns
                if index + token_count <= len(tokens)
                and _producer_identity_key(" ".join(tokens[index : index + token_count])) == alias_key
            ),
            None,
        )
        if match:
            credits.append(resolved[match[0]])
            index += match[1]
        else:
            credits.append(tokens[index])
            index += 1
    return credits


def _without_musical_key_tokens(tokens: list[str]) -> list[str]:
    retained = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        following = tokens[index + 1] if index + 1 < len(tokens) else ""
        tonic_with_mode = (
            re.fullmatch(r"[A-G](?:#|b|♯|♭)?", token, re.IGNORECASE)
            and _MODE_TOKEN.fullmatch(following)
        )
        if tonic_with_mode:
            index += 2
            continue
        if _COMPACT_KEY.fullmatch(token):
            index += 1
            continue
        retained.append(token)
        index += 1
    return retained


def _unique_producers(values, *, include_primary: bool = False, primary_producer: str = _PRIMARY_PRODUCER) -> list[str]:
    primary = _normalise_primary_producer(primary_producer)
    credits = []
    seen = set()
    if include_primary:
        credits.append(primary)
        seen.add(primary.casefold())
    for raw_value in values:
        value = str(raw_value or "").strip()
        if not value:
            continue
        if value.casefold() == primary.casefold():
            value = primary
        if value.casefold() in seen:
            continue
        seen.add(value.casefold())
        credits.append(value)
    return credits


@lru_cache(maxsize=65_536)
def _source_provenance(
    filename: str,
    primary_producer: str = _PRIMARY_PRODUCER,
    producer_identities: tuple[tuple[str, tuple[str, ...]], ...] = (),
) -> dict[str, object]:
    primary = _normalise_primary_producer(primary_producer)
    stem = Path(str(filename or "")).stem
    source = re.sub(r"(?:[_\s-])(?:layer\s*)?l?\d+$", "", stem, flags=re.IGNORECASE).strip()
    tokens = [token for token in re.split(r"\s+", source) if token]
    if not tokens:
        return {"loop_name": "Source loop", "producers": [primary]}
    leading_index = 0
    if tokens[0].isdigit() and int(tokens[0]) > 300:
        leading_index = 1
    leading_key_tokens = _key_token_count(tokens, leading_index)
    bpm_index = next(
        (
            index
            for index, token in enumerate(tokens)
            if index >= leading_index
            and token.isdigit()
            and 40 <= int(token) <= 300
        ),
        -1,
    )
    if bpm_index < 0:
        fallback = " ".join(tokens[leading_index + leading_key_tokens :]).strip()
        return {"loop_name": fallback or source or "Source loop", "producers": [primary]}
    loop_name = " ".join(tokens[leading_index + leading_key_tokens : bpm_index]).strip() or "Source loop"
    producer_start = bpm_index + 1
    if leading_key_tokens == 0:
        producer_start += _key_token_count(tokens, producer_start)
    return {
        "loop_name": loop_name,
        "producers": _unique_producers(
            _parse_producer_tokens(
                _without_musical_key_tokens(tokens[producer_start:]),
                producer_identities,
                primary,
            ),
            primary_producer=primary,
        ) or [primary],
    }


def _record_producers(record: dict, primary_producer: str = _PRIMARY_PRODUCER, producer_identities=()) -> list[str]:
    explicit = record.get("producers")
    if isinstance(explicit, (list, tuple)):
        producers = _unique_producers(
            (
                _canonical_producer(producer, producer_identities, primary_producer)
                for producer in explicit
            ),
            primary_producer=primary_producer,
        )
        if producers:
            return producers
    filename = str(record.get("filename") or "").strip()
    if not filename:
        filename = Path(str(record.get("path") or "")).name
    return list(_source_provenance(
        filename,
        _normalise_primary_producer(primary_producer),
        tuple(producer_identities),
    )["producers"])


def _external_producers(values, primary_producer: str = _PRIMARY_PRODUCER) -> list[str]:
    primary = _normalise_primary_producer(primary_producer)
    return [
        producer
        for producer in _unique_producers(values, primary_producer=primary)
        if producer.casefold() != primary.casefold()
    ]


def _filter_records_by_allowed_producers(
    records: list[dict],
    *,
    allowed_producers,
    primary_producer: str = _PRIMARY_PRODUCER,
    producer_identities=(),
) -> list[dict]:
    """Keep solo material plus sources credited only to allowed collaborators."""

    primary = _normalise_primary_producer(primary_producer)
    allowed_names = _unique_producers(
        (
            _canonical_producer(producer, producer_identities, primary)
            for producer in allowed_producers or ()
        ),
        primary_producer=primary,
    )
    if allowed_names:
        allowed_keys = {producer.casefold() for producer in allowed_names}
        allowed_keys.add(primary.casefold())
        return [
            record
            for record in records
            if all(producer.casefold() in allowed_keys for producer in _record_producers(record, primary, producer_identities))
        ]
    return records


def _records_for_source_pool(
    local_records: list[dict],
    cloud_records: list[dict],
    source_pool: str,
) -> tuple[list[dict], list[dict]]:
    if source_pool == "cloud-only":
        return list(cloud_records), list(cloud_records)
    if source_pool == "local-only":
        return list(local_records), []
    return [*local_records, *cloud_records], list(cloud_records)


def _catalog_snapshot(database: Path) -> tuple[tuple[int, int], tuple[int, int]]:
    """Track both the SQLite file and its WAL without opening them for writes."""

    def signature(path: Path) -> tuple[int, int]:
        try:
            stat = path.stat()
        except FileNotFoundError:
            return (0, 0)
        return (int(stat.st_mtime_ns), int(stat.st_size))

    return signature(database), signature(database.with_name(f"{database.name}-wal"))


def _invalidate_generation_catalog(database: Path) -> None:
    database_key = str(database)
    for key in tuple(_generation_catalog_cache):
        if key[0] == database_key:
            _generation_catalog_cache.pop(key, None)


def _load_generation_catalog(
    database: Path,
    roots: list[str],
    candidate_type,
    *,
    allowed_producers=(),
    primary_producer: str = _PRIMARY_PRODUCER,
    producer_identities=(),
):
    """Load and validate one catalogue snapshot once per persistent bridge.

    Generate used to deserialize and stat every indexed path on every click.
    SQLite/WAL changes invalidate this cache; selected files are checked again
    immediately before rendering to cover external file removals.
    """

    primary = _normalise_primary_producer(primary_producer)
    identity_signature = _producer_identity_signature(producer_identities)
    allowed_key = tuple(
        sorted(
            _canonical_producer(producer, identity_signature, primary).casefold()
            for producer in _unique_producers(allowed_producers or (), primary_producer=primary)
        )
    )
    cache_key = (str(database), tuple(sorted(roots)), (primary.casefold(), *allowed_key), identity_signature)
    snapshot = _catalog_snapshot(database)
    cached = _generation_catalog_cache.get(cache_key)
    if cached is not None and cached["snapshot"] == snapshot:
        return cached, True

    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(layer_cache)")
        }
        conditions: list[str] = []
        parameters: list[str] = []
        if "manual_excluded" in columns:
            conditions.append("COALESCE(manual_excluded, 0) = 0")
        if roots:
            conditions.append(f"library_root IN ({','.join('?' for _ in roots)})")
            parameters.extend(roots)
        query = "SELECT * FROM layer_cache"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        records = [dict(row) for row in connection.execute(query, parameters)]
    records = _filter_records_by_allowed_producers(
        records,
        allowed_producers=allowed_producers,
        primary_producer=primary,
        producer_identities=identity_signature,
    )
    for record in records:
        record["producers"] = _record_producers(record, primary, identity_signature)

    candidates_by_path = {}
    for record in records:
        raw_path = str(record.get("path") or "")
        if not raw_path or not Path(raw_path).is_file():
            continue
        try:
            candidates_by_path[raw_path] = candidate_type.from_record(record)
        except Exception:
            continue
    source_metadata_by_path = {
        str(Path(str(record.get("path") or "")).expanduser().resolve()): record
        for record in records
        if record.get("path")
    }
    entry = {
        "snapshot": _catalog_snapshot(database),
        "records": records,
        "candidates_by_path": candidates_by_path,
        "source_metadata_by_path": source_metadata_by_path,
    }
    _invalidate_generation_catalog(database)
    _generation_catalog_cache[cache_key] = entry
    return entry, False


def _normalise_allowed_credit_counts(payload: dict) -> list[int]:
    counts = sorted({
        int(value)
        for value in payload.get("allowedCreditCounts") or ()
        if str(value).strip().isdigit() and 0 <= int(value) <= 3
    })
    if 0 in counts:
        return [0]
    if counts:
        return counts
    legacy_count = max(0, int(payload.get("maxProducerCount") or 0))
    if legacy_count in (1, 2, 3):
        return [legacy_count]
    return [1, 2]


def _candidate_producers(candidate, producer_overrides=None, primary_producer: str = _PRIMARY_PRODUCER) -> list[str]:
    overrides = producer_overrides or {}
    explicit = overrides.get(candidate.identity)
    if explicit:
        return _unique_producers(explicit, primary_producer=primary_producer)
    return list(_source_provenance(candidate.path.name, _normalise_primary_producer(primary_producer))["producers"])


def _candidate_external_producer_keys(candidate, producer_overrides=None, primary_producer: str = _PRIMARY_PRODUCER) -> frozenset[str]:
    return frozenset(
        producer.casefold()
        for producer in _external_producers(
            _candidate_producers(candidate, producer_overrides, primary_producer),
            primary_producer,
        )
    )


def _collaborator_pool_specs(
    candidates,
    *,
    allowed_credit_counts: list[int],
    required_producers,
    locked_identities,
    seed: int,
    producer_overrides=None,
    primary_producer: str = _PRIMARY_PRODUCER,
):
    """Build final-credit groups while retaining solo layers inside mixed pools."""

    display_names: dict[str, str] = {}
    external_by_identity = {}
    for candidate in candidates:
        external_names = _external_producers(
            _candidate_producers(candidate, producer_overrides, primary_producer),
            primary_producer,
        )
        external_keys = frozenset(producer.casefold() for producer in external_names)
        external_by_identity[candidate.identity] = external_keys
        for producer in external_names:
            display_names.setdefault(producer.casefold(), producer)

    required_keys = {
        producer.casefold()
        for producer in _external_producers(required_producers or (), primary_producer)
    }
    available_keys = set(display_names)
    unavailable_required = sorted(required_keys - available_keys)
    if unavailable_required:
        raise ValueError(
            "Required collaborators have no eligible layers in the active libraries: "
            + ", ".join(unavailable_required)
        )

    locked_keys: set[str] = set()
    for identity in locked_identities or ():
        if identity:
            locked_keys.update(external_by_identity.get(str(identity), ()))
    fixed_keys = required_keys | locked_keys
    rng = random.Random(seed)
    mode_order = list(allowed_credit_counts)
    rng.shuffle(mode_order)
    specs = []
    for credit_count in mode_order:
        if credit_count == 0:
            specs.append((credit_count, fixed_keys, tuple(candidates), required_keys, display_names))
            continue
        external_slots = credit_count - 1
        if len(fixed_keys) > external_slots:
            continue
        optional_keys = sorted(available_keys - fixed_keys)
        groups = [
            frozenset((*fixed_keys, *selection))
            for selection in combinations(optional_keys, external_slots - len(fixed_keys))
        ]
        rng.shuffle(groups)
        # A very large collaborator catalogue must not make one Generate click
        # attempt thousands of complete policy selections before it can fail.
        for group in groups[:128]:
            pool = tuple(
                candidate
                for candidate in candidates
                if external_by_identity[candidate.identity].issubset(group)
            )
            if not pool:
                continue
            specs.append((credit_count, group, pool, required_keys, display_names))
    return specs


def _selection_collaborator_state(
    plan,
    required_keys: set[str],
    producer_overrides=None,
    primary_producer: str = _PRIMARY_PRODUCER,
):
    external_by_selection = [
        _candidate_external_producer_keys(
            selection.candidate,
            producer_overrides,
            primary_producer,
        )
        for selection in plan.selections
    ]
    present = set().union(*external_by_selection) if external_by_selection else set()
    required_layer_count = sum(
        bool(external_keys & required_keys)
        for external_keys in external_by_selection
    )
    return present, required_layer_count


def _select_constrained_collaborator_plan(
    candidates,
    request,
    *,
    target_external_keys: frozenset[str],
    required_keys: set[str],
    required_contribution_percent: int,
    select_generation,
    producer_overrides=None,
    primary_producer: str = _PRIMARY_PRODUCER,
):
    """Select normally, then replace unlocked slots until credit rules match."""

    plan = select_generation(candidates, request)
    required_layer_target = 0
    if required_keys:
        required_layer_target = min(
            len(request.categories),
            max(
                len(required_keys),
                math.floor(
                    len(request.categories) * required_contribution_percent / 100.0
                    + 0.5
                ),
            ),
        )

    def score(candidate_plan):
        present, required_layer_count = _selection_collaborator_state(
            candidate_plan,
            required_keys,
            producer_overrides,
            primary_producer,
        )
        missing_count = len(target_external_keys - present)
        share_distance = (
            abs(required_layer_count - required_layer_target)
            if required_keys
            else 0
        )
        return missing_count, share_distance

    original_locked = tuple(request.locked_identities_by_slot)
    candidate_by_identity = {candidate.identity: candidate for candidate in candidates}
    maximum_attempts = max(1, len(request.categories) * 4)
    for _ in range(maximum_attempts):
        current_score = score(plan)
        if current_score == (0, 0):
            return replace(plan, request=request)
        present, current_required_layers = _selection_collaborator_state(
            plan,
            required_keys,
            producer_overrides,
            primary_producer,
        )
        missing = target_external_keys - present
        if missing:
            target_candidates = tuple(
                candidate
                for candidate in candidates
                if _candidate_external_producer_keys(
                    candidate,
                    producer_overrides,
                    primary_producer,
                ) & missing
            )
        elif current_required_layers < required_layer_target:
            target_candidates = tuple(
                candidate
                for candidate in candidates
                if _candidate_external_producer_keys(
                    candidate,
                    producer_overrides,
                    primary_producer,
                ) & required_keys
            )
        else:
            target_candidates = tuple(
                candidate
                for candidate in candidates
                if not (
                    _candidate_external_producer_keys(
                        candidate,
                        producer_overrides,
                        primary_producer,
                    ) & required_keys
                )
            )

        best_plan = None
        best_score = current_score
        for slot_index in range(len(request.categories)):
            if original_locked[slot_index] is not None:
                continue
            trial_locks = tuple(
                None if index == slot_index else selection.candidate.identity
                for index, selection in enumerate(plan.selections)
            )
            locked_candidates = tuple(
                candidate_by_identity[identity]
                for identity in trial_locks
                if identity is not None and identity in candidate_by_identity
            )
            trial_pool = tuple({
                candidate.identity: candidate
                for candidate in (*locked_candidates, *target_candidates)
            }.values())
            try:
                trial_plan = select_generation(
                    trial_pool,
                    replace(request, locked_identities_by_slot=trial_locks),
                )
            except ValueError:
                continue
            trial_score = score(trial_plan)
            if trial_score < best_score:
                best_plan = trial_plan
                best_score = trial_score
        if best_plan is None:
            break
        plan = best_plan

    raise ValueError(
        "No compatible layer combination can satisfy the selected collaborator credits "
        "and contribution share."
    )


def _generation_producers(
    selections,
    producer_overrides=None,
    primary_producer: str = _PRIMARY_PRODUCER,
) -> list[str]:
    return _unique_producers(
        (
            producer
            for selection in selections
            for producer in _candidate_producers(
                selection.candidate,
                producer_overrides,
                primary_producer,
            )
        ),
        include_primary=True,
        primary_producer=primary_producer,
    )


def _compact_generation_key(key_name: str) -> str:
    normalized = str(key_name or "").strip().replace("♯", "#").replace("♭", "b")
    match = re.fullmatch(
        r"([A-G](?:#|b)?)(?:\s*(major|maj|minor|min|m))?",
        normalized,
        flags=re.IGNORECASE,
    )
    if not match:
        return re.sub(r"\s+", "", normalized) or "Key"
    tonic = f"{match.group(1)[0].upper()}{match.group(1)[1:]}"
    mode = (match.group(2) or "major").casefold()
    return f"{tonic}{'m' if mode in {'minor', 'min', 'm'} else ''}"


def _generation_display_name(
    generation_number: int,
    target_bpm: float,
    target_key: str,
    producers,
    primary_producer: str = _PRIMARY_PRODUCER,
) -> str:
    return (
        f"L Gen{max(1, int(generation_number)):02d}_"
        f"{int(round(float(target_bpm)))}_"
        f"{_compact_generation_key(target_key)} "
        f"{' '.join(_unique_producers(producers, include_primary=True, primary_producer=primary_producer))}"
    )


def _rename_generation_master(rendered, display_name: str):
    invalid_filename = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
    filename_stem = invalid_filename.sub("_", str(display_name)).strip(" .") or "Generated Loop"
    desired_path = rendered.output_directory / f"{filename_stem}.mp3"
    if rendered.master_path == desired_path:
        return rendered
    if desired_path.exists():
        raise RuntimeError(f"Refusing to overwrite an existing generated master: {desired_path}")

    manifest = json.loads(rendered.manifest_path.read_text(encoding="utf-8"))
    outputs = manifest.get("outputs")
    if not isinstance(outputs, dict):
        raise RuntimeError("The generated-loop manifest has no output map.")
    outputs["master"] = desired_path.name
    outputs["presentation"] = desired_path.name
    temporary_manifest = rendered.manifest_path.with_name(
        f".{uuid.uuid4().hex}-{rendered.manifest_path.name}"
    )
    temporary_manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(rendered.master_path, desired_path)
    os.replace(temporary_manifest, rendered.manifest_path)
    return replace(rendered, master_path=desired_path, presentation_path=desired_path)


def send(payload: dict) -> None:
    with _write_lock:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        sys.stdout.flush()


def engine_status(component: str, state: str, message: str) -> None:
    send(
        {
            "type": "engine-status",
            "component": component,
            "state": state,
            "message": message,
        }
    )


def progress(job_id: str, message: str, current: int, total: int, phase: str) -> None:
    percent = 100 if total <= 0 else round(100 * max(0, min(current, total)) / total)
    send(
        {
            "id": job_id,
            "type": "progress",
            "message": message,
            "phase": phase,
            "current": current,
            "total": total,
            "percent": percent,
        }
    )


def progress_percent(job_id: str, message: str, percent: int, phase: str) -> None:
    value = max(0, min(int(percent), 100))
    send(
        {
            "id": job_id,
            "type": "progress",
            "message": message,
            "phase": phase,
            "current": value,
            "total": 100,
            "percent": value,
        }
    )


def require_file(value: object, *, mp3_only: bool = False) -> Path:
    path = Path(str(value or "")).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"Audio file does not exist: {path}")
    if mp3_only and path.suffix.casefold() != ".mp3":
        raise ValueError("Layer extraction accepts one MP3 loop.")
    return path


def require_folder(value: object) -> Path:
    path = Path(str(value or "")).expanduser().resolve()
    if not path.is_dir():
        raise ValueError(f"Folder does not exist: {path}")
    return path


def output_folder(value: object) -> Path:
    path = Path(str(value or "")).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_name(value: str) -> str:
    cleaned = "".join("-" if char in '\\/:*?\"<>|' else char for char in str(value))
    return " ".join(cleaned.strip().strip(".").split()) or "Untitled"


def unique_session_folder(category: str, base_name: str) -> Path:
    root = Path.home() / "Documents" / "Stem Slicer" / category
    root.mkdir(parents=True, exist_ok=True)
    clean = safe_name(base_name)
    candidate = root / clean
    if not candidate.exists():
        candidate.mkdir()
        return candidate
    stamp = time.strftime("%y-%m-%d %H-%M-%S")
    for suffix in (stamp, f"{stamp}-{uuid.uuid4().hex[:6]}"):
        candidate = root / f"{clean} — {suffix}"
        if not candidate.exists():
            candidate.mkdir()
            return candidate
    raise RuntimeError("Could not create a unique output folder.")


def unique_file(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 10_000):
        candidate = path.with_name(f"{path.stem} {index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not create a unique output file for {path.name}")


class AnalyzerClient:
    def __init__(self) -> None:
        analyzer_root = SOURCE_ROOT / "analyzer"
        command = [
            sys.executable,
            "-u",
            str(analyzer_root / "openkeyscan_analyzer_server.py"),
            "--device",
            "cpu",
            "--workers",
            "1",
        ]
        self.process = subprocess.Popen(
            command,
            cwd=analyzer_root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
            **_hidden_process_kwargs(),
        )
        self.messages: queue.Queue[dict | None] = queue.Queue()
        self.stderr_lines: list[str] = []
        self.lock = threading.Lock()
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        ready = self._next_message(300.0)
        if not ready or ready.get("type") != "ready":
            self.close()
            raise RuntimeError("The OpenKeyScan engine did not become ready.")

    def _read_stdout(self) -> None:
        assert self.process.stdout is not None
        try:
            for line in self.process.stdout:
                try:
                    self.messages.put(json.loads(line))
                except json.JSONDecodeError:
                    continue
        finally:
            self.messages.put(None)

    def _read_stderr(self) -> None:
        assert self.process.stderr is not None
        for line in self.process.stderr:
            self.stderr_lines.append(line.rstrip())
            if len(self.stderr_lines) > 200:
                del self.stderr_lines[:100]

    def _next_message(self, timeout: float) -> dict | None:
        try:
            message = self.messages.get(timeout=timeout)
        except queue.Empty as error:
            detail = "\n".join(self.stderr_lines[-12:])
            raise TimeoutError(f"Key analysis timed out. {detail}".strip()) from error
        if message is None:
            detail = "\n".join(self.stderr_lines[-12:])
            raise RuntimeError(f"The key engine stopped unexpectedly. {detail}".strip())
        return message

    def analyze(self, path: Path) -> dict:
        from engine import find_ffmpeg

        with self.lock:
            request_id = uuid.uuid4().hex
            request = {
                "id": request_id,
                "path": str(path),
                "bpm_mode": "quick_scan_loop",
                "structure_ffmpeg_path": find_ffmpeg(),
            }
            if self.process.stdin is None:
                raise RuntimeError("The key engine input is unavailable.")
            self.process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
            self.process.stdin.flush()
            while True:
                message = self._next_message(240.0)
                if message.get("id") != request_id:
                    continue
                if message.get("status") == "error":
                    raise RuntimeError(str(message.get("error") or "Key analysis failed."))
                if message.get("status") == "success":
                    return message

    def close(self) -> None:
        process = self.process
        if process.poll() is not None:
            return
        if process.stdin:
            process.stdin.close()
        try:
            process.wait(timeout=12)
        except subprocess.TimeoutExpired:
            process.terminate()


def analyzer() -> AnalyzerClient:
    global _analyzer
    if _analyzer is None:
        _analyzer = AnalyzerClient()
    return _analyzer


def classifier():
    global _classifier
    if _classifier is None:
        from mert_client import MertLayerClassifier

        _classifier = MertLayerClassifier(
            python_executable=sys.executable,
            artifact_path=SOURCE_ROOT / "models" / "layer_roles_v4_2.joblib",
            hf_cache_dir=SOURCE_ROOT / "models" / "huggingface",
            feature_cache_path=ACCEPTED_CACHE_ROOT / "generate" / "features.sqlite3",
            device=os.environ.get("STEM_SLICER_MERT_DEVICE", "cpu"),
        )
    return _classifier


def midi_converter():
    global _midi_converter
    if _midi_converter is None:
        from midi_conversion import MidiConverter

        _midi_converter = MidiConverter()
    return _midi_converter


ROMAN = ("I", "II", "III", "IV", "V", "VI", "VII")
MODE_NAMES = ("Ionian", "Dorian", "Phrygian", "Lydian", "Mixolydian", "Aeolian", "Locrian")
MAJOR_INTERVALS = (0, 2, 4, 5, 7, 9, 11)
SHARP_PITCHES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def scan_payload(source: Path, raw: dict) -> dict:
    from audio_convert import expanded_key_name
    from key_detection import format_camelot

    camelot = str(raw["camelot"])
    detected_compact = format_camelot(camelot, "detected", "sharps")
    relative_mode = "relative_minor" if camelot.endswith("B") else "relative_major"
    relative_compact = format_camelot(camelot, relative_mode, "sharps")
    major_compact = format_camelot(camelot, "relative_major", "sharps")
    major_tonic = major_compact.removesuffix("m")
    tonic = SHARP_PITCHES.index(major_tonic)
    modes = []
    for mode_index in range(7):
        note = SHARP_PITCHES[(tonic + MAJOR_INTERVALS[mode_index]) % 12]
        modes.append(
            {
                "degreeMajor": ROMAN[mode_index],
                "degreeMinor": ROMAN[(mode_index - 5) % 7],
                "key": note,
                "mode": MODE_NAMES[mode_index],
            }
        )
    return {
        "source": str(source),
        "bpm": int(round(float(raw.get("bpm") or 0))),
        "detectedKey": expanded_key_name(detected_compact),
        "relativeKey": expanded_key_name(relative_compact),
        "camelot": camelot,
        "openKey": str(raw.get("openkey") or ""),
        "bpmConfidence": (
            float(raw["bpm_confidence"])
            if raw.get("bpm_confidence") is not None
            else None
        ),
        "bpmSource": str(raw.get("bpm_source") or raw.get("bpm_decision") or "audio"),
        "relativeModes": modes,
        "raw": raw,
    }


def waveform_peaks(path: Path, points: int = 72) -> list[float]:
    from engine import find_ffmpeg

    ffmpeg = find_ffmpeg()
    completed = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-ac",
            "1",
            "-ar",
            "8000",
            "-f",
            "s16le",
            "-",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
        **_hidden_process_kwargs(),
    )
    samples = array("h")
    raw = completed.stdout[: len(completed.stdout) // 2 * 2]
    samples.frombytes(raw)
    if not samples:
        return [0.0] * points
    stride = max(1, len(samples) // points)
    values = [
        max(abs(value) for value in samples[index : index + stride])
        for index in range(0, len(samples), stride)
    ][:points]
    maximum = max(values) or 1
    return [value / maximum for value in values] + [0.0] * max(0, points - len(values))


def audio_duration(path: Path) -> float:
    from engine import find_ffmpeg, find_ffprobe, get_duration

    ffmpeg = find_ffmpeg()
    return float(get_duration(str(path), ffmpeg, find_ffprobe(ffmpeg)) or 0.0)


def artifact_payload(
    path: Path,
    *,
    bpm: int,
    key: str,
    duration: float | None = None,
    peaks: list[float] | None = None,
    midi_path: Path | None = None,
    category: str | None = None,
    alternate_key: str | None = None,
    source_path: Path | None = None,
) -> dict:
    return {
        "path": str(path),
        "name": path.name,
        "displayName": path.stem,
        "bpm": int(bpm),
        "key": key or "—",
        "duration": float(duration if duration is not None else audio_duration(path)),
        "bytes": path.stat().st_size,
        "peaks": list(peaks if peaks is not None else waveform_peaks(path)),
        "midiPath": str(midi_path) if midi_path else None,
        "category": category,
        "alternateKey": alternate_key,
        "sourcePath": str(source_path) if source_path else None,
    }


def target_selection(payload: dict, scan: dict) -> tuple[int | None, str | None]:
    target_bpm = int(payload.get("targetBpm") or 0) if payload.get("targetBpmEnabled") else None
    target_key = str(payload.get("targetKey") or "") if payload.get("targetKeyEnabled") else None
    if target_bpm is not None and not 1 <= target_bpm <= 999:
        raise ValueError("Target BPM must be a valid positive value.")
    return target_bpm, target_key


def target_key_for_source(source_key: str, target_pair: str | None) -> str:
    if not target_pair:
        return source_key
    parts = [part.strip() for part in target_pair.split("/")]
    if source_key.casefold().endswith(" minor") and len(parts) > 1:
        return parts[1]
    return parts[0]


def build_output_stem(source: Path, scan: dict, payload: dict) -> str:
    from filename_templates import parse_loop_filename, render_name

    target_bpm, target_key = target_selection(payload, scan)
    parts = parse_loop_filename(str(source))
    parts["extension"] = ".mp3"
    parts["BPM"] = str(target_bpm or scan["bpm"])
    parts["KEY"] = target_key_for_source(scan["detectedKey"], target_key)
    return Path(render_name(parts, ("LOOP NAME", "BPM", "KEY", "PROD NAME"))).stem


def add_midi(
    job_id: str,
    artifacts: list[dict],
    phase: str,
    *,
    start_percent: int = 0,
    end_percent: int = 99,
) -> None:
    if not artifacts:
        return
    converter = midi_converter()
    total = len(artifacts)
    for index, artifact in enumerate(artifacts, 1):
        audio_path = Path(artifact["path"])
        midi_path = unique_file(audio_path.with_suffix(".mid"))
        starting_percent = start_percent + round(((index - 1) / total) * (end_percent - start_percent))
        progress_percent(
            job_id,
            f"Creating MIDI {index}/{total}: {audio_path.name}",
            starting_percent,
            phase,
        )
        try:
            with redirect_stdout(sys.stderr):
                converter.convert(str(audio_path), str(midi_path), bpm=int(artifact["bpm"]))
            artifact["midiPath"] = str(midi_path)
        except Exception as error:
            artifact["midiPath"] = None
            artifact["midiError"] = str(error)
        percent = start_percent + round((index / total) * (end_percent - start_percent))
        send(
            {
                "id": job_id,
                "type": "progress",
                "message": f"MIDI {index}/{total}: {audio_path.name}",
                "phase": phase,
                "current": index,
                "total": total,
                "percent": percent,
            }
        )
        send({"id": job_id, "type": "artifact", "message": audio_path.name, "artifact": artifact})


def quick_scan(job_id: str, payload: dict) -> dict:
    source = require_file(payload.get("source"))
    progress(job_id, "Analyzing musical key and tempo", 1, 20, "engine")
    raw = analyzer().analyze(source)
    result = scan_payload(source, raw)
    progress(job_id, f"Detected {result['bpm']} BPM · {result['detectedKey']}", 1, 1, "analysis")
    return result


def quick_extract(job_id: str, payload: dict) -> dict:
    from audio_convert import ConversionRequest, convert_audio
    from engine import process_single_file
    from filename_templates import parse_loop_filename

    source = require_file(payload.get("source"), mp3_only=True)
    destination = unique_session_folder("Quick Extract", source.stem)
    target_active = bool(payload.get("targetBpmEnabled") or payload.get("targetKeyEnabled"))
    scan = None
    output_stem = source.stem
    started = time.perf_counter()
    if target_active:
        progress(job_id, "Analyzing source BPM and key", 0, 4, "analysis")
        scan = scan_payload(source, analyzer().analyze(source))
        output_stem = build_output_stem(source, scan, payload)
    progress(job_id, "Detecting and exporting layers", 1, 4, "extraction")
    diagnostics = process_single_file(str(source), str(destination), output_stem)
    exported = [
        row
        for row in diagnostics
        if row.get("event") == "exported" and row.get("output_exists")
    ]
    if not exported:
        raise RuntimeError("No layer could be extracted from this loop.")

    if scan is not None:
        target_bpm, target_key = target_selection(payload, scan)

        def convert_row(row: dict):
            source_layer = destination / row["output_name"]
            staged = destination / f".{uuid.uuid4().hex}-{source_layer.name}"
            result = convert_audio(
                ConversionRequest(
                    source=source_layer,
                    destination=staged,
                    source_bpm=scan["bpm"],
                    target_bpm=target_bpm,
                    source_key=scan["detectedKey"],
                    target_key=target_key,
                )
            )
            os.replace(staged, source_layer)
            return row, result

        progress(job_id, "Applying target BPM and key", 2, 4, "conversion")
        with ThreadPoolExecutor(max_workers=min(4, len(exported))) as executor:
            converted = list(executor.map(convert_row, exported))
        conversion_by_name = {row["output_name"]: result for row, result in converted}
    else:
        conversion_by_name = {}

    parsed = parse_loop_filename(str(source))
    artifacts = []
    for row in exported:
        path = destination / row["output_name"]
        artifacts.append(
            artifact_payload(
                path,
                bpm=int((target_selection(payload, scan)[0] if scan else None) or row.get("bpm") or parsed.get("BPM") or 140),
                key=(target_key_for_source(scan["detectedKey"], target_selection(payload, scan)[1]) if scan else parsed.get("KEY") or "—"),
                duration=(float(row.get("duration_seconds") or 0) / float(conversion_by_name[row["output_name"]].speed_ratio) if row["output_name"] in conversion_by_name else float(row.get("duration_seconds") or 0)),
                peaks=list(row.get("waveform_peaks") or waveform_peaks(path)),
                source_path=source,
            )
        )
    progress(job_id, f"{len(artifacts)} audio layers ready", 3, 4, "audio")
    add_midi(job_id, artifacts, "midi", start_percent=75, end_percent=99)
    progress(job_id, "Quick Extract complete", 4, 4, "complete")
    return {
        "outputFolder": str(destination),
        "layers": artifacts,
        "elapsedSeconds": time.perf_counter() - started,
    }


def quick_convert(job_id: str, payload: dict) -> dict:
    from audio_convert import ConversionRequest, convert_audio

    source = require_file(payload.get("source"))
    if not payload.get("targetBpmEnabled") and not payload.get("targetKeyEnabled"):
        raise ValueError("Enable Target BPM, Target Key, or both before converting.")
    destination = unique_session_folder("Quick Convert", source.stem)
    started = time.perf_counter()
    progress(job_id, "Analyzing source BPM and key", 0, 3, "analysis")
    scan = scan_payload(source, analyzer().analyze(source))
    target_bpm, target_key = target_selection(payload, scan)
    stem = build_output_stem(source, scan, payload)
    output = unique_file(destination / f"{stem}.mp3")
    progress(job_id, "Converting BPM and key", 1, 3, "conversion")
    convert_audio(
        ConversionRequest(
            source=source,
            destination=output,
            source_bpm=scan["bpm"],
            target_bpm=target_bpm,
            source_key=scan["detectedKey"],
            target_key=target_key,
        ),
        progress=lambda message: send(
            {
                "id": job_id,
                "type": "progress",
                "message": message,
                "phase": "conversion",
                "current": 2,
                "total": 3,
                "percent": 67,
            }
        ),
    )
    artifact = artifact_payload(
        output,
        bpm=target_bpm or scan["bpm"],
        key=target_key_for_source(scan["detectedKey"], target_key),
        source_path=source,
    )
    send({"id": job_id, "type": "artifact", "message": output.name, "artifact": artifact})
    progress(job_id, "Quick Convert complete", 3, 3, "complete")
    return {
        "outputFolder": str(destination),
        "artifact": artifact,
        "sourceBpm": scan["bpm"],
        "sourceKey": scan["detectedKey"],
        "targetBpm": target_bpm or scan["bpm"],
        "targetKey": target_key_for_source(scan["detectedKey"], target_key),
        "elapsedSeconds": time.perf_counter() - started,
    }


def batch(job_id: str, payload: dict) -> dict:
    from audio_convert import ConversionRequest, convert_audio
    from engine import process_audio
    from filename_templates import parse_loop_filename, render_name
    from key_detection import format_camelot

    source = require_folder(payload.get("sourceFolder"))
    destination = output_folder(payload.get("outputFolder"))
    files = sorted(source.glob("*.mp3"))
    if not files:
        raise ValueError("No MP3 files were found in the source folder.")
    extraction = bool(payload.get("extractionEnabled"))
    key_analysis = bool(payload.get("keyAnalysisEnabled"))
    conversion = bool(payload.get("conversionEnabled"))
    if not (extraction or key_analysis or conversion):
        raise ValueError("Enable at least one batch operation.")
    if conversion and not (payload.get("targetBpmEnabled") or payload.get("targetKeyEnabled")):
        raise ValueError("Enable Target BPM, Target Key, or both for conversion.")

    analyses: dict[str, dict | Exception] = {}
    raw_results: dict[str, dict | Exception] = {}
    failures: list[dict] = []
    needs_analysis = key_analysis or conversion
    analysis_steps = len(files) if needs_analysis else 0
    process_steps = len(files)
    total = max(1, analysis_steps + process_steps + (len(files) if conversion else 0))
    current = 0
    if needs_analysis:
        for file in files:
            try:
                raw = analyzer().analyze(file)
                scan = scan_payload(file, raw)
                analyses[file.name] = scan
                raw_results[file.name] = raw
                message = f"Analyzed {scan['bpm']} BPM · {scan['detectedKey']}: {file.name}"
            except Exception as error:
                analyses[file.name] = error
                raw_results[file.name] = error
                failures.append({"source": file.name, "message": str(error)})
                message = f"Analysis unavailable: {file.name}"
            current += 1
            progress(job_id, message, current, total, "analysis")

    output_stems: dict[str, str] = {}
    token_order = tuple(str(item).upper() for item in payload.get("tokenOrder") or ("LOOP NAME", "BPM", "KEY", "PROD NAME"))
    for file in files:
        parts = parse_loop_filename(file.name)
        scan = analyses.get(file.name)
        if isinstance(scan, dict):
            if conversion:
                target_bpm, target_key = target_selection(payload, scan)
                parts["BPM"] = str(target_bpm or scan["bpm"])
                parts["KEY"] = target_key_for_source(scan["detectedKey"], target_key)
            elif key_analysis:
                mode = str(payload.get("keyMode") or "detected")
                accidentals = str(payload.get("accidentals") or "sharps")
                parts["KEY"] = format_camelot(str(scan["camelot"]), mode, accidentals)
            output_stems[file.name] = Path(render_name(parts, token_order)).stem
        else:
            output_stems[file.name] = file.stem
    if len(set(output_stems.values())) != len(output_stems):
        raise RuntimeError("The selected filename structure creates duplicate output names.")

    manifest = None
    engine_failures = []
    if extraction or (key_analysis and not conversion):
        state = {"error": "", "manifest": None, "failures": []}

        def report_engine(done: int, engine_total: int, status: str) -> None:
            fraction = done / engine_total if engine_total else 0
            mapped = current + round(fraction * process_steps)
            progress(job_id, status, mapped, total, "extraction" if extraction else "naming")

        settings = {
            "enabled": key_analysis,
            "extract_enabled": extraction,
            "destination_mode": str(payload.get("destinationMode") or "copy_to_output"),
            "token_order": token_order,
            "mode": str(payload.get("keyMode") or "detected"),
            "accidentals": str(payload.get("accidentals") or "sharps"),
            "analysis_results": raw_results,
            "output_stems_override": output_stems,
        }
        process_audio(
            str(source),
            str(destination),
            report_engine,
            lambda items, item_manifest: state.update(failures=list(items), manifest=item_manifest),
            lambda message: state.update(error=str(message)),
            settings,
            analyzer=None,
        )
        if state["error"]:
            raise RuntimeError(state["error"])
        engine_failures = [
            {"source": str(item[0]), "message": str(item[1])}
            for item in state["failures"]
        ]
        failures.extend(engine_failures)
        manifest = state["manifest"]
        current += process_steps

    outputs_by_source = dict((manifest or {}).get("outputs_by_source") or {})
    if conversion:
        if extraction:
            conversion_items = [
                (file, Path(layer))
                for file in files
                for layer in outputs_by_source.get(file.name, [])
            ]
        else:
            conversion_items = [(file, file) for file in files]
        conversion_total = max(1, len(conversion_items))
        converted_outputs: dict[str, list[str]] = {file.name: [] for file in files}
        for index, (source_file, audio_file) in enumerate(conversion_items, 1):
            scan = analyses.get(source_file.name)
            if not isinstance(scan, dict):
                continue
            try:
                target_bpm, target_key = target_selection(payload, scan)
                final_name = audio_file.name if extraction else f"{output_stems[source_file.name]}.mp3"
                final = destination / final_name
                staged = destination / f".{uuid.uuid4().hex}-{final_name}"
                convert_audio(
                    ConversionRequest(
                        source=audio_file,
                        destination=staged,
                        source_bpm=scan["bpm"],
                        target_bpm=target_bpm,
                        source_key=scan["detectedKey"],
                        target_key=target_key,
                    )
                )
                os.replace(staged, final)
                converted_outputs[source_file.name].append(str(final))
            except Exception as error:
                failures.append({"source": source_file.name, "message": str(error)})
            mapped = current + round(index / conversion_total * max(1, total - current))
            progress(job_id, f"Converted: {audio_file.name}", mapped, total, "conversion")
        outputs_by_source = converted_outputs
    elif not extraction and key_analysis:
        outputs_by_source = {
            file.name: [str(destination / f"{output_stems[file.name]}.mp3")]
            for file in files
        }

    outputs = [path for paths in outputs_by_source.values() for path in paths]
    progress(job_id, "Batch complete", total, total, "complete")
    return {
        "outputFolder": str(destination),
        "files": len(files),
        "outputs": outputs,
        "failures": failures,
    }


def library_scan(job_id: str, payload: dict) -> dict:
    from key_confidence import KeyConfidenceIndex
    from layer_library import LayerLibrary, require_extracted_layer_folder

    root = require_folder(payload.get("root"))
    progress_percent(job_id, "Checking folder contents", 0, "checking")
    inspection = require_extracted_layer_folder(root)
    database = Path(str(payload.get("databasePath") or "")).expanduser().resolve()
    accepted_root = ACCEPTED_CACHE_ROOT
    try:
        database.relative_to(accepted_root)
    except ValueError as error:
        raise ValueError("Generate scans must use the active 1.9 cache.") from error
    database.parent.mkdir(parents=True, exist_ok=True)
    key_metadata = database.parent / "key-confidence-v2"
    inventory_path = key_metadata / "original_loop_inventory.json"
    results_path = key_metadata / "key_confidence_results_v2.json"
    if inventory_path.is_file() and results_path.is_file():
        key_confidence_index = KeyConfidenceIndex.from_files(
            library_root=root,
            inventory_path=inventory_path,
            results_path=results_path,
        )
    else:
        key_confidence_index = KeyConfidenceIndex()
    library = LayerLibrary(
        root,
        database,
        classifier=classifier(),
        key_confidence_index=key_confidence_index,
    )

    def report(item) -> None:
        phase_label = {
            "inventory": "Inventorying library",
            "metadata": "Reading metadata",
            "classify": "Classifying layers",
            "complete": "Library ready",
            "cancelled": "Scan cancelled",
        }.get(item.phase, str(item.phase).title())
        message = f"{phase_label}: {item.relative_path}" if item.relative_path else phase_label
        progress(job_id, message, int(item.completed), int(item.total), str(item.phase))

    result = library.scan(progress=report, atomic=True)
    return {
        "root": result.library_root,
        "totalFiles": inspection.audio_file_count,
        "added": max(0, result.hashed_count - result.cached_count),
        "updated": result.hashed_count,
        "unchanged": result.cached_count,
        "removed": 0,
        "issues": len(result.issues),
    }


def generation_artifacts(
    rendered,
    request,
    midi_by_identity: dict[str, str] | None = None,
    source_metadata_by_path: dict[str, dict] | None = None,
) -> list[dict]:
    duration = rendered.timeline.loop_frames / rendered.timeline.sample_rate
    artifacts = []
    midi_paths = midi_by_identity or {}
    metadata_by_path = source_metadata_by_path or {}
    for stem in rendered.stem_results:
        selection = stem.selection
        source_path = str(selection.candidate.path.resolve())
        source_metadata = metadata_by_path.get(source_path, {})
        provenance = _source_provenance(selection.candidate.path.name)
        explicit_producers = source_metadata.get("producers")
        if isinstance(explicit_producers, (list, tuple)):
            producers = _unique_producers(explicit_producers) or list(provenance["producers"])
        else:
            producers = list(provenance["producers"])
        source_loop_name = str(source_metadata.get("source_loop_name") or provenance["loop_name"])
        alternate = selection.candidate.alternate_scanned_key
        alternate_mode = selection.candidate.alternate_scanned_mode or ""
        detected_key = selection.candidate.scanned_key or selection.candidate.source_key
        detected_mode = (
            selection.candidate.scanned_mode
            if selection.candidate.scanned_key
            else selection.candidate.source_mode
        )
        artifact = artifact_payload(
            stem.output_path,
            bpm=int(round(request.plan.request.target_bpm)),
            key=request.plan.request.target_key,
            duration=duration,
            peaks=list(stem.waveform_peaks),
            category=selection.category,
            alternate_key=(f"{alternate} {alternate_mode}".strip() if alternate else None),
            source_path=selection.candidate.path,
        )
        artifact.update(
            {
                "identity": selection.candidate.identity,
                "sourceFile": selection.candidate.path.name,
                "sourceLoopId": selection.candidate.source_loop_id,
                "sourceLoopName": source_loop_name,
                "producers": producers,
                "libraryRoot": source_metadata.get("library_root"),
                "sourceOrigin": _source_origin(source_metadata),
                "cloudLayerId": source_metadata.get("cloud_layer_id"),
                "cloudOwnerId": source_metadata.get("cloud_owner_id"),
                "sourceSha256": source_metadata.get("sha256"),
                "sourceDetectedKey": " ".join(
                    item for item in (detected_key, detected_mode) if item
                ),
                "sourceKeyRank": selection.source_key_rank,
                "octave": int(selection.manual_pitch_semitones // 12),
                "locked": (
                    request.plan.request.locked_identities_by_slot[selection.slot_index]
                    == selection.candidate.identity
                ),
            }
        )
        midi_path = midi_paths.get(selection.candidate.identity)
        if midi_path:
            artifact["midiPath"] = midi_path
        artifacts.append(artifact)
    return artifacts


def _source_origin(source_metadata: dict) -> str:
    library_root = str(source_metadata.get("library_root") or "")
    return (
        "cloud"
        if source_metadata.get("cloud_object_path")
        or source_metadata.get("cloud_layer_id")
        or library_root.startswith("cloud://")
        else "local"
    )


def _annotate_generation_manifest_origins(
    manifest_path: Path,
    source_metadata_by_path: dict[str, dict],
) -> None:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        layers = manifest.get("layers")
        if not isinstance(layers, list):
            return
        for layer in layers:
            if not isinstance(layer, dict):
                continue
            source_path = str(layer.get("source_path") or "")
            if not source_path:
                continue
            metadata = source_metadata_by_path.get(str(Path(source_path).expanduser().resolve()), {})
            layer["source_origin"] = _source_origin(metadata)
            if metadata.get("cloud_layer_id"):
                layer["cloud_layer_id"] = metadata["cloud_layer_id"]
            if metadata.get("cloud_owner_id"):
                layer["cloud_owner_id"] = metadata["cloud_owner_id"]
        temporary = manifest_path.with_name(f".{manifest_path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, manifest_path)
    except (OSError, TypeError, ValueError):
        return


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _remember_verified_cloud_file(destination: Path, expected_sha256: str) -> None:
    if not expected_sha256:
        return
    try:
        details = destination.stat()
    except OSError:
        return
    cache_key = str(destination)
    fingerprint = (details.st_size, details.st_mtime_ns, expected_sha256)
    with _verified_cloud_cache_lock:
        if (
            cache_key not in _verified_cloud_cache
            and len(_verified_cloud_cache) >= _VERIFIED_CLOUD_CACHE_LIMIT
        ):
            _verified_cloud_cache.pop(next(iter(_verified_cloud_cache)))
        _verified_cloud_cache[cache_key] = fingerprint


def _cloud_cache_file_is_ready(
    destination: Path,
    *,
    expected_size: int,
    expected_sha256: str,
) -> bool:
    try:
        details = destination.stat()
    except OSError:
        return False
    if not destination.is_file() or (expected_size and details.st_size != expected_size):
        return False
    if not expected_sha256:
        return True
    fingerprint = (details.st_size, details.st_mtime_ns, expected_sha256)
    with _verified_cloud_cache_lock:
        if _verified_cloud_cache.get(str(destination)) == fingerprint:
            return True
    if _sha256_file(destination) != expected_sha256:
        return False
    _remember_verified_cloud_file(destination, expected_sha256)
    return True


def _annotate_generation_manifest_performance(
    manifest_path: Path,
    elapsed_seconds: float,
    timings: dict[str, float],
) -> None:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["performance"] = {
            "total_seconds": elapsed_seconds,
            **{
                re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower(): seconds
                for name, seconds in timings.items()
            },
        }
        temporary = manifest_path.with_name(f".{manifest_path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, manifest_path)
    except (OSError, TypeError, ValueError):
        return


def _materialize_cloud_selections(
    job_id: str,
    selections,
    source_metadata_by_path: dict[str, dict],
    cloud_auth: dict,
) -> None:
    remote = []
    for selection in selections:
        destination = selection.candidate.path.expanduser().resolve()
        record = source_metadata_by_path.get(str(destination), {})
        object_path = str(record.get("cloud_object_path") or "").strip()
        if object_path:
            remote.append((selection, destination, record, object_path))
    if not remote:
        return

    project_url = str(cloud_auth.get("projectUrl") or "").strip().rstrip("/")
    publishable_key = str(cloud_auth.get("publishableKey") or "").strip()
    access_token = str(cloud_auth.get("accessToken") or "").strip()
    bucket = str(cloud_auth.get("bucket") or "cloud-layers").strip()
    if not project_url.startswith(("https://", "http://localhost", "http://127.0.0.1")):
        raise ValueError("The Cloud project URL is invalid.")
    if not publishable_key or not access_token:
        raise ValueError("The Cloud session expired before the selected layers could download.")

    completed = 0
    completed_lock = threading.Lock()

    def download(item) -> None:
        nonlocal completed
        _selection, destination, record, object_path = item
        expected_sha256 = str(record.get("sha256") or "").strip().lower()
        expected_size = int(record.get("byte_size") or 0)
        if _cloud_cache_file_is_ready(
            destination,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
        ):
            with completed_lock:
                completed += 1
                current = completed
            progress_percent(
                job_id,
                f"Cloud layer {current}/{len(remote)} ready from local cache",
                12 + round((current / len(remote)) * 3),
                "cloud-download",
            )
            return

        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.part")
        url = (
            f"{project_url}/storage/v1/object/authenticated/"
            f"{quote(bucket, safe='')}/{quote(object_path, safe='/')}"
        )
        request = Request(
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "apikey": publishable_key,
            },
        )
        digest = hashlib.sha256()
        byte_count = 0
        with urlopen(request, timeout=90) as response, temporary.open("wb") as output:
            for chunk in iter(lambda: response.read(1024 * 1024), b""):
                output.write(chunk)
                digest.update(chunk)
                byte_count += len(chunk)
        if expected_size and byte_count != expected_size:
            raise ValueError(f"Cloud layer download is incomplete: {record.get('filename') or object_path}")
        if expected_sha256 and digest.hexdigest() != expected_sha256:
            raise ValueError(f"Cloud layer checksum mismatch: {record.get('filename') or object_path}")
        os.replace(temporary, destination)
        _remember_verified_cloud_file(destination, expected_sha256)
        with completed_lock:
            completed += 1
            current = completed
        progress_percent(
            job_id,
            f"Downloaded Cloud layer {current}/{len(remote)}",
            12 + round((current / len(remote)) * 3),
            "cloud-download",
        )

    progress_percent(job_id, f"Downloading {len(remote)} selected Cloud layers", 12, "cloud-download")
    with ThreadPoolExecutor(max_workers=min(3, len(remote))) as executor:
        futures = [executor.submit(download, item) for item in remote]
        for future in as_completed(futures):
            future.result()


def generation(job_id: str, payload: dict) -> dict:
    from generation_policy import GenerationRequest, LayerCandidate, select_generation
    from generation_renderer import (
        BungeePCMBackend,
        FFmpegMP3Encoder,
        RenderRequest,
        render_generation,
    )

    generation_started = time.perf_counter()
    primary_producer = _normalise_primary_producer(payload.get("primaryProducer"))
    producer_identities = _producer_identity_signature(payload.get("producerIdentities"))
    database = Path(str(payload.get("databasePath") or "")).expanduser().resolve()
    if not database.is_file():
        raise ValueError("The Generate library cache is unavailable.")
    roots = [str(Path(item).expanduser().resolve()) for item in payload.get("libraryRoots") or []]
    catalog_started = time.perf_counter()
    catalog, catalog_cached = _load_generation_catalog(
        database,
        roots,
        LayerCandidate,
        allowed_producers=payload.get("allowedProducers"),
        primary_producer=primary_producer,
        producer_identities=producer_identities,
    )
    catalog_seconds = time.perf_counter() - catalog_started
    local_records = list(catalog["records"])
    cloud_records = [
        dict(record)
        for record in payload.get("cloudLayers") or ()
        if isinstance(record, dict)
    ]
    cloud_records = _filter_records_by_allowed_producers(
        cloud_records,
        allowed_producers=payload.get("allowedProducers"),
        primary_producer=primary_producer,
        producer_identities=producer_identities,
    )
    for record in cloud_records:
        record["producers"] = _record_producers(record, primary_producer, producer_identities)
    source_pool = str(payload.get("sourcePool") or "mixed")
    records, cloud_records = _records_for_source_pool(
        local_records,
        cloud_records,
        source_pool,
    )
    excluded_source_loops = {
        (
            str(Path(str(item.get("libraryRoot") or "")).expanduser().resolve()),
            str(item.get("sourceLoopId") or "").strip(),
        )
        for item in payload.get("excludedSourceLoops") or ()
        if isinstance(item, dict)
        and str(item.get("libraryRoot") or "").strip()
        and str(item.get("sourceLoopId") or "").strip()
    }
    quarantined_count = 0
    if excluded_source_loops:
        eligible_records = []
        for record in records:
            source_identity = (
                str(Path(str(record.get("library_root") or "")).expanduser().resolve()),
                str(record.get("source_loop_id") or "").strip(),
            )
            if source_identity in excluded_source_loops:
                quarantined_count += 1
            else:
                eligible_records.append(record)
        records = eligible_records
    categories = tuple(str(item) for item in payload.get("categories") or ())
    if not records:
        if source_pool == "cloud-only":
            raise ValueError(
                "Cloud only is active, but no enabled Cloud layer matches the current selection."
            )
        raise ValueError("No indexed layer matches the current collaborator selection.")
    quarantine_label = f" · {quarantined_count} quarantined" if quarantined_count else ""
    cache_label = " · warm cache" if catalog_cached else ""
    progress_percent(
        job_id,
        f"Loaded {len(records)} allowed indexed layers{quarantine_label}{cache_label}",
        3,
        "selection",
    )
    request = GenerationRequest(
        categories=categories,
        target_bpm=float(payload.get("targetBpm") or 140),
        target_key=str(payload.get("targetKey") or "A minor"),
        bars=int(payload.get("bars") or 8),
        seed=int(payload.get("seed") or 0),
        # Imported layer packs often carry an explicit filename key without a
        # matching precomputed confidence row. Safe analyzed layers remain the
        # first pool; filename-keyed layers are available only as the reserve.
        allow_uncertain_key_reserve=True,
        locked_identities_by_slot=tuple(payload.get("lockedIdentitiesBySlot") or ()),
        excluded_identities=frozenset(str(item) for item in payload.get("excludedIdentities") or ()),
    )
    candidates_by_path = dict(catalog["candidates_by_path"])
    source_metadata_by_path = dict(catalog["source_metadata_by_path"])
    for record in cloud_records:
        raw_path = str(record.get("path") or "")
        if not raw_path:
            continue
        try:
            candidate = LayerCandidate.from_record(record)
        except Exception:
            continue
        candidates_by_path[raw_path] = candidate
        source_metadata_by_path[str(Path(raw_path).expanduser().resolve())] = record
    candidates = [
        candidates_by_path[raw_path]
        for record in records
        if (raw_path := str(record.get("path") or "")) in candidates_by_path
    ]
    skipped = len(records) - len(candidates)
    producer_overrides = {
        candidate.identity: _record_producers(record, primary_producer, producer_identities)
        for record in records
        if (raw_path := str(record.get("path") or ""))
        and (candidate := candidates_by_path.get(raw_path)) is not None
    }
    if not candidates:
        raise ValueError("No scanned layer has enough BPM/key metadata to generate.")
    allowed_credit_counts = _normalise_allowed_credit_counts(payload)
    required_contribution_percent = min(
        100,
        max(10, int(payload.get("requiredContributionPercent") or 20)),
    )
    progress_percent(
        job_id,
        f"Selecting compatible layers ({skipped} metadata rows skipped)",
        8,
        "selection",
    )
    selection_started = time.perf_counter()

    def select_plan(active_candidates):
        pool_specs = _collaborator_pool_specs(
            active_candidates,
            allowed_credit_counts=allowed_credit_counts,
            required_producers=payload.get("requiredProducers"),
            locked_identities=request.locked_identities_by_slot,
            seed=request.seed,
            producer_overrides=producer_overrides,
            primary_producer=primary_producer,
        )
        if not pool_specs:
            modes = ", ".join(
                "Any" if count == 0 else "Solo" if count == 1 else "Duo" if count == 2 else "Trio"
                for count in allowed_credit_counts
            )
            raise ValueError(
                f"No collaborator group can satisfy the enabled final-loop modes ({modes})."
            )
        last_selection_error: Exception | None = None
        for _credit_count, external_group, candidate_pool, required_keys, display_names in pool_specs:
            try:
                selected_plan = _select_constrained_collaborator_plan(
                    candidate_pool,
                    request,
                    target_external_keys=external_group,
                    required_keys=required_keys,
                    required_contribution_percent=required_contribution_percent,
                    select_generation=select_generation,
                    producer_overrides=producer_overrides,
                    primary_producer=primary_producer,
                )
            except ValueError as exc:
                last_selection_error = exc
                continue
            present, _required_layer_count = _selection_collaborator_state(
                selected_plan,
                required_keys,
                producer_overrides,
                primary_producer,
            )
            selected_producers = [
                display_names.get(key, key)
                for key in sorted(present)
            ]
            return selected_plan, selected_producers
        if last_selection_error is not None:
            raise last_selection_error
        raise ValueError("No compatible collaborator combination could fill this recipe.")

    plan, selected_external_producers = select_plan(candidates)
    selection_seconds = time.perf_counter() - selection_started
    cloud_started = time.perf_counter()
    _materialize_cloud_selections(
        job_id,
        plan.selections,
        source_metadata_by_path,
        dict(payload.get("cloudAuth") or {}),
    )
    cloud_seconds = time.perf_counter() - cloud_started
    missing_selected_paths = {
        selection.candidate.path
        for selection in plan.selections
        if not selection.candidate.path.is_file()
    }
    if missing_selected_paths:
        # External deletion without a catalogue rescan is rare.  Preserve the
        # previous behavior by doing one full refresh and selecting an existing
        # alternative instead of failing during the audio transform.
        _invalidate_generation_catalog(database)
        candidates = [candidate for candidate in candidates if candidate.path.is_file()]
        skipped = len(records) - len(candidates)
        if not candidates:
            raise ValueError("No indexed source file is still available on disk.")
        reselection_started = time.perf_counter()
        plan, selected_external_producers = select_plan(candidates)
        selection_seconds += time.perf_counter() - reselection_started
    collaborator_label = (
        f" · {primary_producer} + {' + '.join(selected_external_producers)}"
        if selected_external_producers
        else " · solo"
    )
    progress_percent(
        job_id,
        f"Selected {len(plan.selections)} compatible layers{collaborator_label} in {selection_seconds:.2f}s",
        12,
        "selection",
    )
    generation_number = max(1, int(payload.get("generationNumber") or 1))
    producers = _generation_producers(
        plan.selections,
        producer_overrides,
        primary_producer,
    )
    display_name = _generation_display_name(
        generation_number,
        request.target_bpm,
        request.target_key,
        producers,
        primary_producer,
    )
    class ReportingBackend:
        def __init__(self) -> None:
            self.backend = BungeePCMBackend()
            self.started = 0
            self.completed = 0
            self.total = len(plan.selections)
            self.lock = threading.Lock()
            self.first_started: float | None = None
            self.last_completed: float | None = None

        @property
        def wall_seconds(self) -> float:
            if self.first_started is None or self.last_completed is None:
                return 0.0
            return max(0.0, self.last_completed - self.first_started)

        def transform(self, selection, *, target_bpm: float, sample_rate: int, channels: int):
            with self.lock:
                started = time.perf_counter()
                if self.first_started is None:
                    self.first_started = started
                self.started += 1
                item_number = self.started
                start = 15 + round(((item_number - 1) / max(1, self.total)) * 48)
            progress_percent(
                job_id,
                f"Rendering layer {item_number}/{self.total}: {selection.category}",
                start,
                "render",
            )
            audio = self.backend.transform(
                selection,
                target_bpm=target_bpm,
                sample_rate=sample_rate,
                channels=channels,
            )
            with self.lock:
                self.last_completed = max(self.last_completed or 0.0, time.perf_counter())
                self.completed += 1
                completed_count = self.completed
                completed = 15 + round((completed_count / max(1, self.total)) * 48)
            progress_percent(
                job_id,
                f"Rendered layer {completed_count}/{self.total}: {selection.category}",
                completed,
                "render",
            )
            return audio

    class ReportingEncoder:
        def __init__(self) -> None:
            self.encoder = FFmpegMP3Encoder()
            self.started = 0
            self.completed = 0
            self.total = len(plan.selections) + 1
            self.lock = threading.Lock()
            self.first_started: float | None = None
            self.last_completed: float | None = None

        @property
        def wall_seconds(self) -> float:
            if self.first_started is None or self.last_completed is None:
                return 0.0
            return max(0.0, self.last_completed - self.first_started)

        def encode(self, destination, audio, *, sample_rate: int, bitrate_bps: int) -> None:
            with self.lock:
                started = time.perf_counter()
                if self.first_started is None:
                    self.first_started = started
                self.started += 1
                item_number = self.started
                start = 64 + round(((item_number - 1) / max(1, self.total)) * 15)
            progress_percent(
                job_id,
                f"Encoding audio {item_number}/{self.total}: {destination.name}",
                start,
                "encode",
            )
            self.encoder.encode(
                destination,
                audio,
                sample_rate=sample_rate,
                bitrate_bps=bitrate_bps,
            )
            with self.lock:
                self.last_completed = max(self.last_completed or 0.0, time.perf_counter())
                self.completed += 1
                completed_count = self.completed
                completed = 64 + round((completed_count / max(1, self.total)) * 15)
            progress_percent(
                job_id,
                f"Encoded audio {completed_count}/{self.total}: {destination.name}",
                completed,
                "encode",
            )

    render_request = RenderRequest(
        plan=plan,
        output_root=Path.home() / "Documents" / "Stem Slicer" / "Generated Loops",
        generation_name=display_name,
    )
    reporting_backend = ReportingBackend()
    reporting_encoder = ReportingEncoder()
    render_started = time.perf_counter()
    rendered = render_generation(
        render_request,
        backend=reporting_backend,
        encoder=reporting_encoder,
        transform_workers=max(1, min(4, int(payload.get("transformWorkers") or 4))),
        encode_workers=max(1, min(4, int(payload.get("encodeWorkers") or 4))),
    )
    render_seconds = time.perf_counter() - render_started
    transform_seconds = reporting_backend.wall_seconds
    encode_seconds = reporting_encoder.wall_seconds
    render_overhead_seconds = max(0.0, render_seconds - transform_seconds - encode_seconds)
    artifact_started = time.perf_counter()
    rendered = _rename_generation_master(rendered, display_name)
    artifacts = generation_artifacts(
        rendered,
        render_request,
        source_metadata_by_path=source_metadata_by_path,
    )
    _annotate_generation_manifest_origins(rendered.manifest_path, source_metadata_by_path)
    artifact_seconds = time.perf_counter() - artifact_started
    midi_started = time.perf_counter()
    add_midi(job_id, artifacts, "midi", start_percent=80, end_percent=99)
    midi_seconds = time.perf_counter() - midi_started
    midi_by_identity = {
        str(artifact.get("identity")): str(artifact["midiPath"])
        for artifact in artifacts
        if artifact.get("identity") and artifact.get("midiPath")
    }
    session_key = str(rendered.output_directory)
    _generation_sessions[session_key] = {
        "request": render_request,
        "result": rendered,
        "midi": midi_by_identity,
        "source_metadata": source_metadata_by_path,
        "generation_number": generation_number,
        "display_name": display_name,
        "producers": producers,
        "primary_producer": primary_producer,
    }
    while len(_generation_sessions) > 4:
        _generation_sessions.pop(next(iter(_generation_sessions)))
    progress(job_id, "Generation complete", 10, 10, "complete")
    elapsed_seconds = time.perf_counter() - generation_started
    measured_seconds = (
        catalog_seconds
        + selection_seconds
        + cloud_seconds
        + render_seconds
        + artifact_seconds
        + midi_seconds
    )
    timings = {
        "catalogSeconds": catalog_seconds,
        "selectionSeconds": selection_seconds,
        "cloudSeconds": cloud_seconds,
        "renderSeconds": render_seconds,
        "transformSeconds": transform_seconds,
        "encodeSeconds": encode_seconds,
        "renderOverheadSeconds": render_overhead_seconds,
        "artifactSeconds": artifact_seconds,
        "midiSeconds": midi_seconds,
        "otherSeconds": max(0.0, elapsed_seconds - measured_seconds),
    }
    _annotate_generation_manifest_performance(rendered.manifest_path, elapsed_seconds, timings)
    return {
        "outputDirectory": str(rendered.output_directory),
        "masterPath": str(rendered.master_path),
        "manifestPath": str(rendered.manifest_path),
        "seed": request.seed,
        "targetBpm": request.target_bpm,
        "targetKey": request.target_key,
        "generationNumber": generation_number,
        "displayName": display_name,
        "producers": producers,
        "elapsedSeconds": elapsed_seconds,
        "selectionSeconds": selection_seconds,
        "timings": timings,
        "layers": artifacts,
    }


def generation_update(job_id: str, payload: dict) -> dict:
    from generation_policy import plan_with_manual_pitch, plan_with_source_key_rank
    from generation_renderer import rerender_selected_layer

    session_key = str(Path(str(payload.get("outputDirectory") or "")).expanduser().resolve())
    session = _generation_sessions.get(session_key)
    if session is None:
        raise ValueError("This generated stack is no longer active. Generate it again before editing a card.")
    identity = str(payload.get("identity") or "").strip()
    if not identity:
        raise ValueError("The generated layer identity is unavailable.")
    slot_index = int(payload.get("slotIndex") or 0)
    render_request = session["request"]
    rendered = session["result"]
    update = str(payload.get("update") or "")
    if update == "octave":
        octave = int(payload.get("octave") or 0)
        if octave not in (-1, 0, 1):
            raise ValueError("Octave must be -1, 0 or +1.")
        updated_plan = plan_with_manual_pitch(
            render_request.plan,
            slot_index=slot_index,
            identity=identity,
            semitones=octave * 12,
        )
    elif update == "source-key":
        source_key_rank = int(payload.get("sourceKeyRank") or 1)
        updated_plan = plan_with_source_key_rank(
            render_request.plan,
            slot_index=slot_index,
            identity=identity,
            source_key_rank=source_key_rank,
        )
    else:
        raise ValueError("Unsupported generated-layer update.")
    updated_request = replace(render_request, plan=updated_plan)

    def report(message: str, completed: int, total: int) -> None:
        progress(job_id, message, completed, max(1, total + 1), "rerender")

    updated_result = rerender_selected_layer(
        updated_request,
        rendered,
        slot_index=slot_index,
        identity=identity,
        progress=report,
    )
    midi_by_identity = dict(session.get("midi") or {})
    target_stem = next(
        item for item in updated_result.stem_results
        if item.selection.candidate.identity == identity
    )
    midi_target = Path(midi_by_identity.get(identity) or target_stem.output_path.with_suffix(".mid"))
    staged_midi = midi_target.with_name(f".{uuid.uuid4().hex}-{midi_target.name}")
    progress(job_id, "Updating MIDI", 2, 3, "midi")
    with redirect_stdout(sys.stderr):
        midi_converter().convert(
            str(target_stem.output_path),
            str(staged_midi),
            bpm=int(round(updated_request.plan.request.target_bpm)),
        )
    os.replace(staged_midi, midi_target)
    midi_by_identity[identity] = str(midi_target)
    artifacts = generation_artifacts(
        updated_result,
        updated_request,
        midi_by_identity,
        session.get("source_metadata") or {},
    )
    session.update({"request": updated_request, "result": updated_result, "midi": midi_by_identity})
    progress(job_id, "Layer update complete", 3, 3, "complete")
    return {
        "outputDirectory": str(updated_result.output_directory),
        "masterPath": str(updated_result.master_path),
        "manifestPath": str(updated_result.manifest_path),
        "seed": updated_request.plan.request.seed,
        "targetBpm": updated_request.plan.request.target_bpm,
        "targetKey": updated_request.plan.request.target_key,
        "generationNumber": session.get("generation_number"),
        "displayName": session.get("display_name"),
        "producers": session.get("producers") or [
            _normalise_primary_producer(session.get("primary_producer"))
        ],
        "layers": artifacts,
    }


HANDLERS = {
    "quick-scan": quick_scan,
    "quick-extract": quick_extract,
    "quick-convert": quick_convert,
    "batch": batch,
    "library-scan": library_scan,
    "generate": generation,
    "generate-update": generation_update,
}


def execute(command: dict) -> None:
    job_id = str(command.get("id") or "")
    kind = str(command.get("kind") or "")
    payload = command.get("payload") or {}
    if not job_id or kind not in HANDLERS or not isinstance(payload, dict):
        send({"id": job_id, "type": "error", "error": "Invalid engine request."})
        return
    try:
        result = HANDLERS[kind](job_id, payload)
        send({"id": job_id, "type": "result", "message": "Complete", "result": result})
    except Exception as error:
        traceback.print_exc(file=sys.stderr)
        send(
            {
                "id": job_id,
                "type": "error",
                "message": str(error),
                "error": f"{type(error).__name__}: {error}",
            }
        )


def close_engines() -> None:
    if _analyzer is not None:
        _analyzer.close()
    if _classifier is not None:
        try:
            _classifier.close()
        except Exception:
            pass


def main() -> int:
    # Load Basic Pitch/ONNX before render engines alter the process-wide native
    # library environment, then perform a real OpenKeyScan warm-up. The
    # Electron window remains visible while this background process starts.
    engine_status("categorization", "on-demand", "Loads when a library needs categorization.")
    engine_status("midi", "starting", "Loading MIDI conversion…")
    try:
        midi_converter()
    except Exception as error:
        engine_status("midi", "failed", str(error))
        raise
    engine_status("midi", "ready", "Ready for audio-to-MIDI conversion.")

    engine_status("musicalAnalysis", "starting", "Warming up key and tempo analysis…")
    warmup_audio = SOURCE_ROOT / "assets" / "key-and-bpm-engine-warmup.wav"
    try:
        if not warmup_audio.is_file():
            raise FileNotFoundError(f"Musical-analysis warm-up audio is missing: {warmup_audio}")
        analyzer().analyze(warmup_audio)
    except Exception as error:
        engine_status("musicalAnalysis", "failed", str(error))
        raise
    engine_status("musicalAnalysis", "ready", "Ready for key and tempo analysis.")

    send(
        {
            "type": "ready",
            "python": sys.executable,
            "version": sys.version.split()[0],
            "sourceRoot": str(SOURCE_ROOT),
        }
    )
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="StemSlicerEngine")
    futures = []
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                command = json.loads(line)
            except json.JSONDecodeError:
                send({"id": "", "type": "error", "error": "Invalid JSON request."})
                continue
            if command.get("type") == "shutdown":
                break
            futures.append(executor.submit(execute, command))
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
        close_engines()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
