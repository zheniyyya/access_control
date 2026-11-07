"""Тести збереження та відкриття моделей (JSON) і шляхів до файлів даних."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from app.domain.models import Enterprise
from app.domain.seed import variant7_path
from app.paths import resource_path
from app.storage.json_repo import (
    ModelFileError,
    enterprise_from_dict,
    enterprise_to_dict,
    load_enterprise,
    save_enterprise,
)


@pytest.fixture()
def data(enterprise: Enterprise) -> dict[str, Any]:
    return copy.deepcopy(enterprise_to_dict(enterprise))


def _write(path: Path, data: dict[str, Any]) -> Path:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_variant_file_exists() -> None:
    assert variant7_path().is_file()


def test_resource_path_respects_pyinstaller(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert resource_path("data/variant7.json") == tmp_path / "data" / "variant7.json"


def test_dict_round_trip(enterprise: Enterprise) -> None:
    assert enterprise_from_dict(enterprise_to_dict(enterprise)) == enterprise


def test_file_round_trip(enterprise: Enterprise, tmp_path: Path) -> None:
    path = tmp_path / "model.json"
    save_enterprise(enterprise, path)
    assert load_enterprise(path) == enterprise
    assert not (tmp_path / "model.json.tmp").exists()


def test_edited_model_round_trip(enterprise: Enterprise, tmp_path: Path) -> None:
    edited = enterprise.with_initial_model(
        enterprise.initial_model.with_grant("U06", "R3", set(), "").with_role_operations("GUEST", "R1", set())
    )
    path = tmp_path / "edited.json"
    save_enterprise(edited, path)
    loaded = load_enterprise(path)
    assert loaded == edited
    assert loaded != enterprise


def test_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text('{"name": "x",', encoding="utf-8")
    with pytest.raises(ModelFileError, match="не є коректним JSON"):
        load_enterprise(path)


def test_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(ModelFileError, match="не знайдено"):
        load_enterprise(tmp_path / "missing.json")


def test_not_utf8(tmp_path: Path) -> None:
    path = tmp_path / "cp1251.json"
    path.write_bytes('{"name": "Модель"}'.encode("cp1251"))
    with pytest.raises(ModelFileError, match="UTF-8"):
        load_enterprise(path)


def test_top_level_must_be_object(tmp_path: Path) -> None:
    path = tmp_path / "list.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ModelFileError, match="об'єкт JSON"):
        load_enterprise(path)


def test_missing_field(data: dict[str, Any], tmp_path: Path) -> None:
    del data["users"][0]["role"]
    with pytest.raises(ModelFileError, match=r"users\[0\]\.role"):
        load_enterprise(_write(tmp_path / "model.json", data))


def test_wrong_type(data: dict[str, Any], tmp_path: Path) -> None:
    data["resources"][0]["criticality"] = "3"
    with pytest.raises(ModelFileError, match="очікується ціле число"):
        load_enterprise(_write(tmp_path / "model.json", data))


def test_criticality_out_of_range(data: dict[str, Any], tmp_path: Path) -> None:
    data["resources"][1]["criticality"] = 5
    with pytest.raises(ModelFileError, match="від 1 до 3"):
        load_enterprise(_write(tmp_path / "model.json", data))


def test_unknown_role(data: dict[str, Any], tmp_path: Path) -> None:
    data["users"][2]["role"] = "BOSS"
    with pytest.raises(ModelFileError, match="роль «BOSS» не існує"):
        load_enterprise(_write(tmp_path / "model.json", data))


def test_latin_operation_code(data: dict[str, Any], tmp_path: Path) -> None:
    data["initial_model"]["role_permissions"]["ADMIN"]["R1"] = "ЧЗPB"  # латинські P і B
    with pytest.raises(ModelFileError, match="невідомий код операції"):
        load_enterprise(_write(tmp_path / "model.json", data))


def test_duplicate_grant(data: dict[str, Any], tmp_path: Path) -> None:
    data["initial_model"]["user_grants"].append(dict(data["initial_model"]["user_grants"][0]))
    with pytest.raises(ModelFileError, match="повторний індивідуальний дозвіл"):
        load_enterprise(_write(tmp_path / "model.json", data))


def test_duplicate_ids(data: dict[str, Any], tmp_path: Path) -> None:
    data["users"][1]["id"] = data["users"][0]["id"]
    with pytest.raises(ModelFileError, match="повторюється"):
        load_enterprise(_write(tmp_path / "model.json", data))


def test_unsupported_version(data: dict[str, Any], tmp_path: Path) -> None:
    data["format_version"] = 99
    with pytest.raises(ModelFileError, match="версія формату"):
        load_enterprise(_write(tmp_path / "model.json", data))


def test_optional_sections_have_defaults(data: dict[str, Any], tmp_path: Path) -> None:
    del data["rule_bindings"]
    del data["principles"]
    loaded = load_enterprise(_write(tmp_path / "model.json", data))
    assert loaded.bindings.guest_role_id == "GUEST"
    assert loaded.principles == ()
