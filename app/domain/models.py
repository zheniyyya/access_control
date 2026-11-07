"""Доменні сутності моделі розмежування доступу.

Модуль не залежить ні від Qt, ні від файлової системи: тут лише структури
даних, перелічення та перевірка їхньої узгодженості. Усі сутності незмінні —
редагування створює нові екземпляри (методи ``with_*``).
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Protocol, TypeVar

MIN_CRITICALITY = 1
MAX_CRITICALITY = 3

# Позначення відсутності доступу в компактному записі операцій.
EMPTY_CODE = "–"
# Позначення відсутньої операції в позиційному записі клітинки матриці.
GAP_MARK = "·"
# Символи, які ігноруються під час розбору запису операцій («Ч–РВ», «Ч·Р·»).
_SEPARATORS = frozenset(" -–—−·")


class Operation(Enum):
    """Тип операції доступу.

    Значення члена — кортеж (скорочення, назва, вага, опис). Порядок
    оголошення задає порядок операцій у таблицях: Ч, З, Р, В.
    """

    short: str
    label: str
    weight: int
    description: str

    READ = ("Ч", "Читання", 1, "Перегляд даних")
    WRITE = ("З", "Запис", 2, "Створення нових записів і документів")
    EDIT = ("Р", "Редагування", 3, "Зміна наявних записів і документів")
    DELETE = ("В", "Видалення", 4, "Вилучення записів і документів")

    def __init__(self, short: str, label: str, weight: int, description: str) -> None:
        self.short = short
        self.label = label
        self.weight = weight
        self.description = description

    @classmethod
    def from_short(cls, short: str) -> Operation:
        """Повертає операцію за скороченням: «Ч», «З», «Р» або «В»."""
        for operation in cls:
            if operation.short == short.upper():
                return operation
        code_point = f" (U+{ord(short):04X})" if len(short) == 1 else ""
        allowed = ", ".join(operation.short for operation in cls)
        raise ValueError(
            f"невідомий код операції «{short}»{code_point}; "
            f"допустимі коди (кирилиця): {allowed}"
        )


OperationSet = frozenset[Operation]

NO_OPERATIONS: OperationSet = frozenset()
ALL_OPERATIONS: OperationSet = frozenset(Operation)
MODIFYING_OPERATIONS: OperationSet = frozenset(
    {Operation.WRITE, Operation.EDIT, Operation.DELETE}
)
TOTAL_WEIGHT: int = sum(operation.weight for operation in Operation)


def ordered(operations: Iterable[Operation]) -> list[Operation]:
    """Повертає операції у стандартному порядку: Ч, З, Р, В."""
    present = set(operations)
    return [operation for operation in Operation if operation in present]


def parse_operations(text: str) -> OperationSet:
    """Розбирає запис на кшталт «ЧЗРВ», «Ч–РВ» чи «–» у множину операцій.

    Пропуски, дефіси, тире та «·» ігноруються; невідомий символ — ValueError.
    """
    return frozenset(
        Operation.from_short(char) for char in text if char not in _SEPARATORS
    )


def operations_code(operations: Iterable[Operation]) -> str:
    """Компактний запис операцій: «ЧРВ»; порожня множина — «–»."""
    return "".join(operation.short for operation in ordered(operations)) or EMPTY_CODE


def operations_cell(operations: Iterable[Operation], gap: str = GAP_MARK) -> str:
    """Позиційний запис для клітинки матриці: «Ч·РВ» (відсутні операції — «·»)."""
    present = set(operations)
    return "".join(
        operation.short if operation in present else gap for operation in Operation
    )


def operations_weight(operations: Iterable[Operation]) -> int:
    """Сума ваг операцій (Ч = 1, З = 2, Р = 3, В = 4)."""
    return sum(operation.weight for operation in set(operations))


def operations_labels(operations: Iterable[Operation]) -> str:
    """Назви операцій малими літерами через кому: «читання, запис»."""
    return ", ".join(operation.label.lower() for operation in ordered(operations))


def _is_int(value: object) -> bool:
    """Перевіряє, що значення — ціле число (але не логічне)."""
    return isinstance(value, int) and not isinstance(value, bool)


@dataclass(frozen=True)
class Resource:
    """Інформаційний ресурс підприємства."""

    id: str
    name: str
    description: str
    criticality: int  # коефіцієнт критичності K (1–3)
    critical: bool  # ознака «критичний ресурс»

    def validate(self) -> list[str]:
        """Перевіряє поля ресурсу; повертає перелік помилок (порожній — усе гаразд)."""
        errors: list[str] = []
        if not self.id.strip():
            errors.append("Ресурс без ідентифікатора")
        if not self.name.strip():
            errors.append(f"Ресурс {self.id}: назва не може бути порожньою")
        if not _is_int(self.criticality) or not (
            MIN_CRITICALITY <= self.criticality <= MAX_CRITICALITY
        ):
            errors.append(
                f"Ресурс {self.id}: коефіцієнт критичності K має бути цілим числом "
                f"від {MIN_CRITICALITY} до {MAX_CRITICALITY}"
            )
        return errors


@dataclass(frozen=True)
class DutyFunction:
    """Службова функція ролі: операції над ресурсом, потрібні для її виконання."""

    name: str
    resource_id: str
    operations: OperationSet


@dataclass(frozen=True)
class Role:
    """Роль користувачів зі службовими функціями (основа для оптимізації)."""

    id: str
    name: str
    description: str
    functions: tuple[DutyFunction, ...] = ()

    def required_operations(self, resource_id: str) -> OperationSet:
        """Об'єднання операцій, потрібних службовим функціям ролі на ресурсі."""
        required: set[Operation] = set()
        for function in self.functions_for(resource_id):
            required |= function.operations
        return frozenset(required)

    def functions_for(self, resource_id: str) -> tuple[DutyFunction, ...]:
        """Службові функції ролі, що стосуються ресурсу."""
        return tuple(
            function for function in self.functions if function.resource_id == resource_id
        )

    def validate(self, resource_ids: Collection[str]) -> list[str]:
        """Перевіряє роль і її службові функції; повертає перелік помилок."""
        errors: list[str] = []
        if not self.id.strip():
            errors.append("Роль без ідентифікатора")
        if not self.name.strip():
            errors.append(f"Роль {self.id}: назва не може бути порожньою")
        for index, function in enumerate(self.functions, start=1):
            where = f"Роль «{self.name or self.id}», службова функція {index}"
            if not function.name.strip():
                errors.append(f"{where}: назва не може бути порожньою")
            if function.resource_id not in resource_ids:
                errors.append(f"{where}: ресурс «{function.resource_id}» не існує")
            if not function.operations:
                errors.append(f"{where}: потрібно обрати хоча б одну операцію")
        return errors


@dataclass(frozen=True)
class User:
    """Користувач (працівник або зовнішня особа) з однією роллю."""

    id: str
    full_name: str
    position: str
    role_id: str

    def validate(self, role_ids: Collection[str]) -> list[str]:
        """Перевіряє поля користувача; повертає перелік помилок."""
        errors: list[str] = []
        if not self.id.strip():
            errors.append("Користувач без ідентифікатора")
        if not self.full_name.strip():
            errors.append(f"Користувач {self.id}: ПІБ не може бути порожнім")
        if self.role_id not in role_ids:
            errors.append(f"Користувач {self.id}: роль «{self.role_id}» не існує")
        return errors


@dataclass(frozen=True)
class IndividualGrant:
    """Індивідуальний дозвіл користувачу поза його роллю."""

    operations: OperationSet
    reason: str  # причина надання


RolePermissions = dict[str, dict[str, OperationSet]]
UserGrants = dict[str, dict[str, IndividualGrant]]


@dataclass(frozen=True)
class AccessModel:
    """Модель доступу: права ролей та індивідуальні дозволи користувачів поза роллю.

    role_permissions: роль → ресурс → операції;
    user_grants: користувач → ресурс → індивідуальний дозвіл.
    """

    name: str
    role_permissions: RolePermissions = field(default_factory=dict)
    user_grants: UserGrants = field(default_factory=dict)

    def role_operations(self, role_id: str, resource_id: str) -> OperationSet:
        """Операції, надані ролі на ресурсі."""
        return self.role_permissions.get(role_id, {}).get(resource_id, NO_OPERATIONS)

    def grant(self, user_id: str, resource_id: str) -> IndividualGrant | None:
        """Індивідуальний дозвіл користувача на ресурс (None — дозволу немає)."""
        return self.user_grants.get(user_id, {}).get(resource_id)

    def grant_operations(self, user_id: str, resource_id: str) -> OperationSet:
        """Операції, надані користувачу індивідуальним дозволом на ресурсі."""
        grant = self.grant(user_id, resource_id)
        return grant.operations if grant is not None else NO_OPERATIONS

    def iter_grants(self) -> list[tuple[str, str, IndividualGrant]]:
        """Усі індивідуальні дозволи у вигляді (користувач, ресурс, дозвіл)."""
        return [
            (user_id, resource_id, grant)
            for user_id, row in self.user_grants.items()
            for resource_id, grant in row.items()
        ]

    @property
    def grant_operation_count(self) -> int:
        """Кількість операцій, наданих індивідуальними дозволами."""
        return sum(len(grant.operations) for _, _, grant in self.iter_grants())

    @property
    def grant_user_count(self) -> int:
        """Кількість користувачів, що мають індивідуальні дозволи."""
        return len({user_id for user_id, _, grant in self.iter_grants() if grant.operations})

    def with_role_operations(
        self, role_id: str, resource_id: str, operations: Iterable[Operation]
    ) -> AccessModel:
        """Нова модель, у якій роль має на ресурсі саме вказані операції."""
        permissions = {key: dict(row) for key, row in self.role_permissions.items()}
        permissions.setdefault(role_id, {})[resource_id] = frozenset(operations)
        return replace(self, role_permissions=permissions)

    def with_grant(
        self,
        user_id: str,
        resource_id: str,
        operations: Iterable[Operation],
        reason: str = "",
    ) -> AccessModel:
        """Нова модель зі зміненим індивідуальним дозволом (порожні операції — відкликання)."""
        grants = {key: dict(row) for key, row in self.user_grants.items()}
        row = grants.setdefault(user_id, {})
        selected = frozenset(operations)
        if selected:
            row[resource_id] = IndividualGrant(selected, reason)
        else:
            row.pop(resource_id, None)
            if not row:
                del grants[user_id]
        return replace(self, user_grants=grants)

    def renamed(self, name: str) -> AccessModel:
        """Копія моделі з іншою назвою."""
        return replace(self, name=name)

    def validate(
        self,
        role_ids: Collection[str],
        resource_ids: Collection[str],
        user_ids: Collection[str],
    ) -> list[str]:
        """Перевіряє посилання моделі на ролі, ресурси й користувачів."""
        errors: list[str] = []
        where = f"Модель «{self.name}»"
        for role_id, row in self.role_permissions.items():
            if role_id not in role_ids:
                errors.append(f"{where}: невідома роль «{role_id}» у правах ролей")
            for resource_id in row:
                if resource_id not in resource_ids:
                    errors.append(
                        f"{where}: невідомий ресурс «{resource_id}» у правах ролі «{role_id}»"
                    )
        for user_id, resource_id, grant in self.iter_grants():
            if user_id not in user_ids:
                errors.append(f"{where}: невідомий користувач «{user_id}» в індивідуальних дозволах")
            if resource_id not in resource_ids:
                errors.append(
                    f"{where}: невідомий ресурс «{resource_id}» в індивідуальному дозволі {user_id}"
                )
            if not grant.operations:
                errors.append(
                    f"{where}: індивідуальний дозвіл {user_id} / {resource_id} не містить операцій"
                )
        return errors


@dataclass(frozen=True)
class RuleBindings:
    """Прив'язка правил аналізу П1–П8 до конкретних ролей і ресурсів моделі.

    Правила сформульовано через «гостя», «журнал аудиту» тощо; тут вказано,
    які саме ідентифікатори моделі їм відповідають.
    """

    admin_role_id: str = "ADMIN"
    employee_role_id: str = "EMPLOYEE"
    guest_role_id: str = "GUEST"
    finance_resource_id: str = "R2"
    audit_log_resource_id: str = "R5"

    def validate(self, role_ids: Collection[str], resource_ids: Collection[str]) -> list[str]:
        """Перевіряє, що прив'язані ролі й ресурси існують у моделі."""
        errors: list[str] = []
        roles = (
            ("адміністратора", self.admin_role_id),
            ("співробітника", self.employee_role_id),
            ("гостя", self.guest_role_id),
        )
        for title, role_id in roles:
            if role_id not in role_ids:
                errors.append(f"Прив'язка правил: роль {title} «{role_id}» не існує")
        resources = (
            ("фінансової документації", self.finance_resource_id),
            ("журналу аудиту", self.audit_log_resource_id),
        )
        for title, resource_id in resources:
            if resource_id not in resource_ids:
                errors.append(f"Прив'язка правил: ресурс {title} «{resource_id}» не існує")
        return errors


class _Identified(Protocol):
    """Сутність з ідентифікатором."""

    @property
    def id(self) -> str: ...


_T = TypeVar("_T", bound=_Identified)


def _find(items: tuple[_T, ...], item_id: str, kind: str) -> _T:
    """Шукає сутність за ідентифікатором; KeyError — якщо її немає."""
    for item in items:
        if item.id == item_id:
            return item
    raise KeyError(f"{kind} «{item_id}» не знайдено")


def _replaced(items: tuple[_T, ...], new_item: _T, kind: str) -> tuple[_T, ...]:
    """Замінює сутність з тим самим ідентифікатором, зберігаючи порядок."""
    _find(items, new_item.id, kind)
    return tuple(new_item if item.id == new_item.id else item for item in items)


def _duplicates(ids: Iterable[str]) -> list[str]:
    """Ідентифікатори, що трапляються більше одного разу."""
    seen: set[str] = set()
    repeated: list[str] = []
    for item_id in ids:
        if item_id in seen and item_id not in repeated:
            repeated.append(item_id)
        seen.add(item_id)
    return repeated


@dataclass(frozen=True)
class Enterprise:
    """Підприємство: довідники, початкова модель доступу та прив'язка правил.

    Саме цей об'єкт зберігається у файл моделі та відкривається з нього.
    Оптимізована модель не зберігається — її будують зі службових функцій ролей.
    """

    name: str
    resources: tuple[Resource, ...]
    roles: tuple[Role, ...]
    users: tuple[User, ...]
    initial_model: AccessModel
    bindings: RuleBindings = field(default_factory=RuleBindings)
    principles: tuple[str, ...] = ()

    @property
    def resource_ids(self) -> list[str]:
        """Ідентифікатори ресурсів у порядку довідника."""
        return [resource.id for resource in self.resources]

    @property
    def role_ids(self) -> list[str]:
        """Ідентифікатори ролей у порядку довідника."""
        return [role.id for role in self.roles]

    @property
    def user_ids(self) -> list[str]:
        """Ідентифікатори користувачів у порядку довідника."""
        return [user.id for user in self.users]

    def resource(self, resource_id: str) -> Resource:
        """Ресурс за ідентифікатором."""
        return _find(self.resources, resource_id, "Ресурс")

    def role(self, role_id: str) -> Role:
        """Роль за ідентифікатором."""
        return _find(self.roles, role_id, "Роль")

    def user(self, user_id: str) -> User:
        """Користувач за ідентифікатором."""
        return _find(self.users, user_id, "Користувач")

    def role_of(self, user_id: str) -> Role:
        """Роль користувача."""
        return self.role(self.user(user_id).role_id)

    def users_of_role(self, role_id: str) -> tuple[User, ...]:
        """Користувачі, яким призначено роль."""
        return tuple(user for user in self.users if user.role_id == role_id)

    def critical_resources(self) -> tuple[Resource, ...]:
        """Ресурси з ознакою «критичний»."""
        return tuple(resource for resource in self.resources if resource.critical)

    def with_resource(self, resource: Resource) -> Enterprise:
        """Нова модель підприємства із заміненим ресурсом (за ідентифікатором)."""
        return replace(self, resources=_replaced(self.resources, resource, "Ресурс"))

    def with_role(self, role: Role) -> Enterprise:
        """Нова модель підприємства із заміненою роллю (за ідентифікатором)."""
        return replace(self, roles=_replaced(self.roles, role, "Роль"))

    def with_user(self, user: User) -> Enterprise:
        """Нова модель підприємства із заміненим користувачем (за ідентифікатором)."""
        return replace(self, users=_replaced(self.users, user, "Користувач"))

    def with_initial_model(self, model: AccessModel) -> Enterprise:
        """Нова модель підприємства з іншою початковою моделлю доступу."""
        return replace(self, initial_model=model)

    def validate(self) -> list[str]:
        """Повна перевірка узгодженості; повертає перелік помилок українською."""
        errors: list[str] = []
        if not self.resources:
            errors.append("Модель має містити хоча б один інформаційний ресурс")
        if not self.roles:
            errors.append("Модель має містити хоча б одну роль")
        if not self.users:
            errors.append("Модель має містити хоча б одного користувача")
        id_groups = (
            ("ресурсу", self.resource_ids),
            ("ролі", self.role_ids),
            ("користувача", self.user_ids),
        )
        for kind, ids in id_groups:
            for duplicate in _duplicates(ids):
                errors.append(f"Ідентифікатор {kind} «{duplicate}» повторюється")
        resource_ids = set(self.resource_ids)
        role_ids = set(self.role_ids)
        user_ids = set(self.user_ids)
        for resource in self.resources:
            errors.extend(resource.validate())
        for role in self.roles:
            errors.extend(role.validate(resource_ids))
        for user in self.users:
            errors.extend(user.validate(role_ids))
        errors.extend(self.initial_model.validate(role_ids, resource_ids, user_ids))
        errors.extend(self.bindings.validate(role_ids, resource_ids))
        return errors
