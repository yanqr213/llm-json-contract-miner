"""Input and output helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .models import LoadedSamples


def read_samples(paths: Iterable[str]) -> LoadedSamples:
    samples: List[Any] = []
    invalid: List[Dict[str, Any]] = []
    source_files: List[str] = []
    for raw_path in paths:
        path = Path(raw_path)
        source_files.append(str(path))
        if path.suffix.lower() == ".jsonl":
            loaded = read_jsonl(path)
        elif path.suffix.lower() == ".json":
            loaded = read_json(path)
        else:
            raise ValueError(f"unsupported input suffix: {path}")
        samples.extend(loaded.samples)
        invalid.extend(loaded.invalid_records)
    return LoadedSamples(samples=samples, invalid_records=invalid, source_files=source_files)


def read_json(path: Path) -> LoadedSamples:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return LoadedSamples(samples=[], invalid_records=[invalid_record(path, exc.lineno, exc.msg)], source_files=[str(path)])
    if isinstance(value, list):
        return LoadedSamples(samples=list(value), invalid_records=[], source_files=[str(path)])
    return LoadedSamples(samples=[value], invalid_records=[], source_files=[str(path)])


def read_jsonl(path: Path) -> LoadedSamples:
    samples: List[Any] = []
    invalid: List[Dict[str, Any]] = []
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            samples.append(json.loads(line))
        except json.JSONDecodeError as exc:
            invalid.append(invalid_record(path, index, exc.msg))
    return LoadedSamples(samples=samples, invalid_records=invalid, source_files=[str(path)])


def invalid_record(path: Path, line: int, message: str) -> Dict[str, Any]:
    return {"file": str(path), "line": line, "message": message}


def read_json_object(path: str) -> Dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False, sort_keys=True)
        handle.write("\n")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)

