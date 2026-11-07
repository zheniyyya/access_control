"""Збереження та відкриття моделей у форматі JSON.

Структура файлу (UTF-8):
    format_version — версія формату (1);
    name           — назва моделі підприємства;
    resources      — ресурси: id, name, description, criticality (K), critical;
    roles          — ролі: id, name, description, functions (name, resource, operations);
    users          — користувачі: id, full_name, position, role;
    initial_model  — початкова модель: role_permissions (роль → ресурс → «ЧЗРВ»)
                     та user_grants (user, resource, operations, reason);
    rule_bindings  — прив'язка правил П1–П8 до ролей і ресурсів (необов'язкове);
    principles     — принципи побудови еталонної моделі (необов'язкове).

Операції записуються кириличними скороченнями «Ч», «З», «Р», «В»; «–» — доступу немає.
Будь-яка проблема з файлом перетворюється на ModelFileError з повідомленням
українською, яке GUI показує користувачу.
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any, TypeVar, cast

from app.domain.models import (
    NO_OPERATIONS,
    AccessModel,
    DutyFunction,
    Enterprise,
    IndividualGrant,
    OperationSet,
    Resource,
    Role,
    RolePermissions,
    RuleBindings,
    User,
    UserGrants,
    operations_code,
    parse_operations,
)

FORMAT_VERSION = 1
DEFAULT_ENTERPRISE_NAME = "Модель підприємства"
DEFAULT_MODEL_NAME = "Початкова модель"
_MAX_LISTED_ERRORS = 15

# Відповідність ключів JSON полям RuleBindings.
_BINDING_KEYS: tuple[tuple[str, str], ...] = (
    ("admin_role", "admin_role_id"),
    ("employee_role", "employee_role_id"),
    ("guest_role", "guest_role_id"),
    ("finance_resource", "finance_resource_id"),
    ("audit_log_resource", "audit_log_resource_id"),
)

_TYPE_NAMES: dict[type, str] = {
    str: "рядок",
    int: "ціле число",
    bool: "логічне значення (true/false)",
    list: "список",
    dict: "об'єкт",
}

_T = TypeVar("_T")


class ModelFileError(Exception):
    """Помилка відкриття чи збереження файлу моделі; текст призначено користувачу."""


def _join(where: str, key: str) -> str:
    """Шлях до поля в повідомленні: «resources[0].criticality»."""
    return f"{where}.{key}" if where else key


def _json_type(value: Any) -> str:
    """Назва типу значення JSON українською."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "логічне значення"
    if isinstance(value, (int, float)):
        return "число"
    if isinstance(value, str):
        return "рядок"
    if isinstance(value, list):
        return "список"
    if isinstance(value, dict):
        return "об'єкт"
    return type(value).__name__


def _check_type(value: Any, kind: type[_T], where: str) -> _T:
    """Перевіряє тип значення; логічне значення не вважається цілим числом."""
    valid = isinstance(value, kind) and not (kind is int and isinstance(value, bool))
    if not valid:
        raise ModelFileError(
            f"Поле «{where}»: очікується {_TYPE_NAMES[kind]}, отримано {_json_type(value)}."
        )
    return cast(_T, value)


def _required(obj: dict[str, Any], key: str, kind: type[_T], where: str) -> _T:
    """Обов'язкове поле об'єкта JSON заданого типу."""
    if key not in obj:
        raise ModelFileError(f"Відсутнє обов'язкове поле «{_join(where, key)}».")
    return _check_type(obj[key], kind, _join(where, key))


def _optional(obj: dict[str, Any], key: str, kind: type[_T], where: str, default: _T) -> _T:
    """Необов'язкове поле об'єкта JSON; відсутнє або null — значення за замовчуванням."""
    if obj.get(key) is None:
        return default
    return _check_type(obj[key], kind, _join(where, key))


def _required_operations(obj: dict[str, Any], key: str, where: str) -> OperationSet:
    """Обов'язкове поле із записом операцій («ЧЗРВ»)."""
    text = _required(obj, key, str, where)
    try:
        return parse_operations(text)
    except ValueError as exc:
        raise ModelFileError(f"Поле «{_join(where, key)}»: {exc}.") from exc


def _parse_resource(raw: Any, where: str) -> Resource:
    obj = _check_type(raw, dict, where)
    return Resource(
        id=_required(obj, "id", str, where).strip(),
        name=_required(obj, "name", str, where).strip(),
        description=_optional(obj, "description", str, where, "").strip(),
        criticality=_required(obj, "criticality", int, where),
        critical=_required(obj, "critical", bool, where),
    )


def _parse_function(raw: Any, where: str) -> DutyFunction:
    obj = _check_type(raw, dict, where)
    return DutyFunction(
        name=_required(obj, "name", str, where).strip(),
        resource_id=_required(obj, "resource", str, where).strip(),
        operations=_required_operations(obj, "operations", where),
    )


def _parse_role(raw: Any, where: str) -> Role:
    obj = _check_type(raw, dict, where)
    functions_where = _join(where, "functions")
    functions = _optional(obj, "functions", list, where, [])
    return Role(
        id=_required(obj, "id", str, where).strip(),
        name=_required(obj, "name", str, where).strip(),
        description=_optional(obj, "description", str, where, "").strip(),
        functions=tuple(
            _parse_function(item, f"{functions_where}[{index}]")
            for index, item in enumerate(functions)
        ),
    )


def _parse_user(raw: Any, where: str) -> User:
    obj = _check_type(raw, dict, where)
    return User(
        id=_required(obj, "id", str, where).strip(),
        full_name=_required(obj, "full_name", str, where).strip(),
        position=_optional(obj, "position", str, where, "").strip(),
        role_id=_required(obj, "role", str, where).strip(),
    )


def _parse_model(raw: Any, where: str) -> AccessModel:
    obj = _check_type(raw, dict, where)
    permissions_where = _join(where, "role_permissions")
    permissions: RolePermissions = {}
    for role_id, row in _required(obj, "role_permissions", dict, where).items():
        row_where = _join(permissions_where, role_id)
        row_obj = _check_type(row, dict, row_where)
        permissions[role_id] = {
            resource_id: _required_operations(row_obj, resource_id, row_where)
            for resource_id in row_obj
        }
    grants: UserGrants = {}
    grants_where = _join(where, "user_grants")
    for index, item in enumerate(_optional(obj, "user_grants", list, where, [])):
        item_where = f"{grants_where}[{index}]"
        item_obj = _check_type(item, dict, item_where)
        user_id = _required(item_obj, "user", str, item_where).strip()
        resource_id = _required(item_obj, "resource", str, item_where).strip()
        if resource_id in grants.get(user_id, {}):
            raise ModelFileError(
                f"Поле «{item_where}»: повторний індивідуальний дозвіл {user_id} / {resource_id}."
            )
        grants.setdefault(user_id, {})[resource_id] = IndividualGrant(
            operations=_required_operations(item_obj, "operations", item_where),
            reason=_optional(item_obj, "reason", str, item_where, "").strip(),
        )
    return AccessModel(
        name=_optional(obj, "name", str, where, DEFAULT_MODEL_NAME).strip(),
        role_permissions=permissions,
        user_grants=grants,
    )


def _parse_bindings(raw: Any, where: str) -> RuleBindings:
    if raw is None:
        return RuleBindings()
    obj = _check_type(raw, dict, where)
    defaults = RuleBindings()
    values = {
        attribute: _optional(obj, key, str, where, getattr(defaults, attribute)).strip()
        for key, attribute in _BINDING_KEYS
    }
    return RuleBindings(**values)


def _complete_permissions(
    model: AccessModel, roles: tuple[Role, ...], resources: tuple[Resource, ...]
) -> AccessModel:
    """Доповнює права ролей порожніми клітинками, щоб матриця ролей була повною."""
    permissions = {role_id: dict(row) for role_id, row in model.role_permissions.items()}
    for role in roles:
        row = permissions.setdefault(role.id, {})
        for resource in resources:
            row.setdefault(resource.id, NO_OPERATIONS)
    return replace(model, role_permissions=permissions)


def _errors_message(errors: list[str]) -> str:
    """Текст повідомлення про помилки узгодженості моделі."""
    lines = [f"• {error}" for error in errors[:_MAX_LISTED_ERRORS]]
    if len(errors) > _MAX_LISTED_ERRORS:
        lines.append(f"… та ще {len(errors) - _MAX_LISTED_ERRORS}")
    return "Модель містить помилки:\n" + "\n".join(lines)


def enterprise_from_dict(data: Any) -> Enterprise:
    """Створює модель підприємства зі вмісту JSON з повною перевіркою узгодженості."""
    if not isinstance(data, dict):
        raise ModelFileError("Файл моделі має містити об'єкт JSON на верхньому рівні.")
    version = _optional(data, "format_version", int, "", FORMAT_VERSION)
    if version != FORMAT_VERSION:
        raise ModelFileError(
            f"Непідтримувана версія формату файлу: {version} (підтримується {FORMAT_VERSION})."
        )
    resources = tuple(
        _parse_resource(item, f"resources[{index}]")
        for index, item in enumerate(_required(data, "resources", list, ""))
    )
    roles = tuple(
        _parse_role(item, f"roles[{index}]")
        for index, item in enumerate(_required(data, "roles", list, ""))
    )
    users = tuple(
        _parse_user(item, f"users[{index}]")
        for index, item in enumerate(_required(data, "users", list, ""))
    )
    model = _parse_model(_required(data, "initial_model", dict, ""), "initial_model")
    principles = tuple(
        _check_type(item, str, f"principles[{index}]").strip()
        for index, item in enumerate(_optional(data, "principles", list, "", []))
    )
    enterprise = Enterprise(
        name=_optional(data, "name", str, "", DEFAULT_ENTERPRISE_NAME).strip(),
        resources=resources,
        roles=roles,
        users=users,
        initial_model=_complete_permissions(model, roles, resources),
        bindings=_parse_bindings(data.get("rule_bindings"), "rule_bindings"),
        principles=principles,
    )
    errors = enterprise.validate()
    if errors:
        raise ModelFileError(_errors_message(errors))
    return enterprise


def model_to_dict(model: AccessModel, enterprise: Enterprise) -> dict[str, Any]:
    """Перетворює модель доступу на словник; порядок ролей і ресурсів — як у довідниках."""
    grants: list[dict[str, str]] = []
    for user in enterprise.users:
        for resource in enterprise.resources:
            grant = model.grant(user.id, resource.id)
            if grant is not None:
                grants.append(
                    {
                        "user": user.id,
                        "resource": resource.id,
                        "operations": operations_code(grant.operations),
                        "reason": grant.reason,
                    }
                )
    return {
        "name": model.name,
        "role_permissions": {
            role.id: {
                resource.id: operations_code(model.role_operations(role.id, resource.id))
                for resource in enterprise.resources
            }
            for role in enterprise.roles
        },
        "user_grants": grants,
    }


def enterprise_to_dict(enterprise: Enterprise) -> dict[str, Any]:
    """Перетворює модель підприємства на словник для запису в JSON."""
    return {
        "format_version": FORMAT_VERSION,
        "name": enterprise.name,
        "resources": [
            {
                "id": resource.id,
                "name": resource.name,
                "description": resource.description,
                "criticality": resource.criticality,
                "critical": resource.critical,
            }
            for resource in enterprise.resources
        ],
        "roles": [
            {
                "id": role.id,
                "name": role.name,
                "description": role.description,
                "functions": [
                    {
                        "name": function.name,
                        "resource": function.resource_id,
                        "operations": operations_code(function.operations),
                    }
                    for function in role.functions
                ],
            }
            for role in enterprise.roles
        ],
        "users": [
            {
                "id": user.id,
                "full_name": user.full_name,
                "position": user.position,
                "role": user.role_id,
            }
            for user in enterprise.users
        ],
        "initial_model": model_to_dict(enterprise.initial_model, enterprise),
        "rule_bindings": {
            key: getattr(enterprise.bindings, attribute) for key, attribute in _BINDING_KEYS
        },
        "principles": list(enterprise.principles),
    }


def loads_enterprise(text: str, source: str = "моделі") -> Enterprise:
    """Розбирає текст JSON у модель підприємства."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ModelFileError(
            f"Файл «{source}» не є коректним JSON: рядок {exc.lineno}, "
            f"позиція {exc.colno} ({exc.msg})."
        ) from exc
    return enterprise_from_dict(data)


def load_enterprise(path: str | Path) -> Enterprise:
    """Відкриває модель з файлу JSON; будь-яка проблема — ModelFileError."""
    file_path = Path(path)
    try:
        text = file_path.read_text(encoding="utf-8-sig")
    except FileNotFoundError as exc:
        raise ModelFileError(f"Файл моделі не знайдено: {file_path}") from exc
    except UnicodeDecodeError as exc:
        raise ModelFileError(
            f"Файл «{file_path.name}» має бути збережений у кодуванні UTF-8."
        ) from exc
    except OSError as exc:
        raise ModelFileError(
            f"Не вдалося прочитати файл «{file_path}»: {exc.strerror or exc}"
        ) from exc
    return loads_enterprise(text, source=file_path.name)


def save_enterprise(enterprise: Enterprise, path: str | Path) -> None:
    """Зберігає модель у файл JSON (через тимчасовий файл, щоб не пошкодити наявний)."""
    errors = enterprise.validate()
    if errors:
        raise ModelFileError(_errors_message(errors))
    text = json.dumps(enterprise_to_dict(enterprise), ensure_ascii=False, indent=2) + "\n"
    file_path = Path(path)
    temp_path = file_path.with_name(file_path.name + ".tmp")
    try:
        temp_path.write_text(text, encoding="utf-8")
        os.replace(temp_path, file_path)
    except OSError as exc:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise ModelFileError(
            f"Не вдалося зберегти файл «{file_path}»: {exc.strerror or exc}"
        ) from exc
