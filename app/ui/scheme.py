"""Структурна схема системи доступу на QGraphicsScene: Користувачі → Ролі → Ресурси.

Розташування обчислюється власним алгоритмом (без graphviz): користувачі
згруповані за ролями, кожна роль стоїть навпроти своєї групи, ресурси рівномірно
розподілені по висоті. Ребра — кубічні криві Безьє; точки підключення на сторонах
вузлів упорядковано за висотою протилежного кінця, тому біля вузлів ребра не
перетинаються. Підписи ребер розміщуються так, щоб не накладатися.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen
from PySide6.QtSvg import QSvgGenerator
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsSceneHoverEvent,
    QGraphicsSimpleTextItem,
    QStyleOptionGraphicsItem,
    QWidget,
)

from app import palette
from app.domain.models import NO_OPERATIONS, AccessModel, Enterprise, OperationSet, operations_code
from app.services.formatting import count_phrase
from app.services.matrix import CellLevel, cell_level

# Геометрія схеми (пікселі сцени).
GROUP_X = 0.0
GROUP_WIDTH = 280.0
USER_WIDTH = 256.0
USER_HEIGHT = 26.0
USER_GAP = 6.0
GROUP_HEADER = 30.0
GROUP_PADDING = 10.0
GROUP_GAP = 18.0
ROLE_X = 450.0
ROLE_WIDTH = 210.0
ROLE_HEIGHT = 72.0
RESOURCE_X = 930.0
RESOURCE_WIDTH = 290.0
RESOURCE_HEIGHT = 64.0
RESOURCE_MIN_GAP = 16.0
COLUMN_TITLE_Y = 38.0
CONTENT_TOP = 76.0
SCENE_MARGIN = 24.0
DIMMED_OPACITY = 0.12

EDGE_WIDTH: dict[CellLevel, float] = {
    CellLevel.NONE: 1.0,
    CellLevel.READ: 1.6,
    CellLevel.MODIFY: 2.4,
    CellLevel.DELETE: 3.2,
}
MEMBER_WIDTH = 1.2
GRANT_WIDTH = 1.8
ROLE_LABEL_POSITIONS = (0.5, 0.42, 0.58, 0.34, 0.66, 0.26, 0.74)
GRANT_LABEL_POSITIONS = (0.8, 0.86, 0.74, 0.9, 0.68, 0.94)

Segment = tuple[str, QFont, str]  # текст, шрифт, колір


def _font(pixel_size: int, bold: bool = False) -> QFont:
    """Шрифт інтерфейсу заданого розміру в пікселях сцени."""
    font = QFont(QApplication.font())
    font.setPixelSize(pixel_size)
    font.setBold(bold)
    return font


def _rounded(rect: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


def _curve(start: QPointF, end: QPointF) -> QPainterPath:
    """Кубічна крива Безьє з горизонтальними дотичними на кінцях."""
    path = QPainterPath(start)
    bend = (end.x() - start.x()) * 0.5
    path.cubicTo(QPointF(start.x() + bend, start.y()), QPointF(end.x() - bend, end.y()), end)
    return path


def _label_rect(text: str, font: QFont, center: QPointF) -> QRectF:
    metrics = QFontMetricsF(font)
    width = metrics.horizontalAdvance(text) + 12.0
    height = metrics.height() + 4.0
    return QRectF(center.x() - width / 2, center.y() - height / 2, width, height)


class NodeKind(Enum):
    """Тип вузла схеми."""

    USER = "user"
    ROLE = "role"
    RESOURCE = "resource"


class SchemeNode(QGraphicsItem):
    """Вузол схеми: заокруглений прямокутник з рядками тексту; наведення підсвічує зв'язки."""

    def __init__(
        self,
        kind: NodeKind,
        entity_id: str,
        rect: QRectF,
        lines: list[list[Segment]],
        *,
        fill: str,
        border: str,
        border_width: float,
        radius: float,
        tooltip: str,
    ) -> None:
        super().__init__()
        self.kind = kind
        self.entity_id = entity_id
        self.key = f"{kind.value}:{entity_id}"
        self.rect = rect
        self._lines = lines
        self._fill = fill
        self._border = border
        self._border_width = border_width
        self._radius = radius
        self.setToolTip(tooltip)
        self.setAcceptHoverEvents(True)
        self.setZValue(3)

    def boundingRect(self) -> QRectF:
        margin = self._border_width / 2 + 1.0
        return self.rect.adjusted(-margin, -margin, margin, margin)

    def paint(
        self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None
    ) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(self._border), self._border_width))
        painter.setBrush(QColor(self._fill))
        painter.drawRoundedRect(self.rect, self._radius, self._radius)
        heights = [max(QFontMetricsF(font).height() for _text, font, _color in line) for line in self._lines]
        spacing = 2.0
        y = self.rect.center().y() - (sum(heights) + spacing * (len(heights) - 1)) / 2
        padding = 10.0
        right = self.rect.right() - padding
        for line, height in zip(self._lines, heights):
            x = self.rect.left() + padding
            for text, font, color in line:
                metrics = QFontMetricsF(font)
                shown = metrics.elidedText(text, Qt.TextElideMode.ElideRight, max(right - x, 0.0))
                painter.setFont(font)
                painter.setPen(QColor(color))
                painter.drawText(
                    QRectF(x, y, max(right - x, 0.0), height),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    shown,
                )
                x += metrics.horizontalAdvance(shown)
            y += height + spacing

    def left_port(self, slot: int, slots: int) -> QPointF:
        """Точка підключення на лівій стороні (slot з slots, згори донизу)."""
        return QPointF(self.rect.left(), self.rect.top() + self.rect.height() * (slot + 1) / (slots + 1))

    def right_port(self, slot: int, slots: int) -> QPointF:
        """Точка підключення на правій стороні (slot з slots, згори донизу)."""
        return QPointF(self.rect.right(), self.rect.top() + self.rect.height() * (slot + 1) / (slots + 1))

    def hoverEnterEvent(self, event: QGraphicsSceneHoverEvent) -> None:
        scene = self.scene()
        if isinstance(scene, SchemeScene):
            scene.highlight(self.key)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event: QGraphicsSceneHoverEvent) -> None:
        scene = self.scene()
        if isinstance(scene, SchemeScene):
            scene.clear_highlight()
        super().hoverLeaveEvent(event)


class EdgeLabel(QGraphicsItem):
    """Підпис ребра: операції в заокругленій рамці."""

    def __init__(
        self,
        text: str,
        center: QPointF,
        *,
        font: QFont,
        ink: str,
        fill: str,
        border: str,
        dashed: bool = False,
    ) -> None:
        super().__init__()
        self._text = text
        self._font = font
        self._ink = ink
        self._fill = fill
        self._border = border
        self._dashed = dashed
        self.rect = _label_rect(text, font, center)
        self.setZValue(4)

    def boundingRect(self) -> QRectF:
        return self.rect.adjusted(-1.0, -1.0, 1.0, 1.0)

    def paint(
        self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None
    ) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(self._border), 1.0)
        if self._dashed:
            pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(QColor(self._fill))
        painter.drawRoundedRect(self.rect, 4.0, 4.0)
        painter.setFont(self._font)
        painter.setPen(QColor(self._ink))
        painter.drawText(self.rect, Qt.AlignmentFlag.AlignCenter, self._text)


@dataclass
class _EdgeSpec:
    """Ребро до розміщення: тип, кінці, операції та обчислені точки підключення."""

    kind: str  # "member" — належність до ролі, "role" — права ролі, "grant" — індивідуальний дозвіл
    source: SchemeNode
    target: SchemeNode
    operations: OperationSet
    start: QPointF = field(default_factory=QPointF)
    end: QPointF = field(default_factory=QPointF)


class SchemeScene(QGraphicsScene):
    """Сцена структурної схеми для заданої моделі доступу."""

    def __init__(self, enterprise: Enterprise, model: AccessModel, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.setBackgroundBrush(QColor(palette.SURFACE))
        self.model_name = model.name
        self._links: dict[str, set[int]] = {}
        self._dimmable: list[QGraphicsItem] = []
        self._obstacles: list[QRectF] = []
        self._label_rects: list[QRectF] = []
        self._build(enterprise, model)
        self.setSceneRect(
            self.itemsBoundingRect().adjusted(-SCENE_MARGIN, -SCENE_MARGIN, SCENE_MARGIN, SCENE_MARGIN)
        )

    def highlight(self, key: str) -> None:
        """Підсвічує вузол і всі його зв'язки, приглушуючи решту схеми."""
        active = self._links.get(key)
        if not active:
            return
        for item in self._dimmable:
            item.setOpacity(1.0 if id(item) in active else DIMMED_OPACITY)

    def clear_highlight(self) -> None:
        """Повертає звичайний вигляд схеми."""
        for item in self._dimmable:
            item.setOpacity(1.0)

    def _add_text(self, text: str, font: QFont, color: str, position: QPointF) -> QGraphicsSimpleTextItem:
        item = self.addSimpleText(text, font)
        item.setBrush(QColor(color))
        item.setPos(position)
        return item

    def _add_node(self, node: SchemeNode) -> SchemeNode:
        self.addItem(node)
        self._dimmable.append(node)
        self._obstacles.append(node.rect)
        return node

    def _build(self, enterprise: Enterprise, model: AccessModel) -> None:
        self._add_text(f"Структурна схема системи доступу — {model.name}", _font(18, True), palette.INK, QPointF(GROUP_X, 0.0))
        for x, title in (
            (GROUP_X, "Користувачі (згруповані за ролями)"),
            (ROLE_X, "Ролі"),
            (RESOURCE_X, "Інформаційні ресурси"),
        ):
            self._add_text(title, _font(13, True), palette.INK_SECONDARY, QPointF(x, COLUMN_TITLE_Y))
        users, groups = self._add_users(enterprise)
        users_bottom = max((rect.bottom() for rect in groups.values()), default=CONTENT_TOP)
        roles = self._add_roles(enterprise, model, groups)
        resources = self._add_resources(enterprise, users_bottom)
        resources_bottom = max((node.rect.bottom() for node in resources.values()), default=CONTENT_TOP)
        built = self._add_edges(enterprise, model, users, roles, resources)
        self._register_links(enterprise, users, roles, resources, built)
        self._add_legend(max(users_bottom, resources_bottom) + 36.0)

    def _add_users(self, enterprise: Enterprise) -> tuple[dict[str, SchemeNode], dict[str, QRectF]]:
        nodes: dict[str, SchemeNode] = {}
        groups: dict[str, QRectF] = {}
        id_font, name_font, header_font = _font(12, True), _font(12), _font(12, True)
        y = CONTENT_TOP
        for role in enterprise.roles:
            members = enterprise.users_of_role(role.id)
            rows = max(len(members), 1)
            height = GROUP_HEADER + 2 * GROUP_PADDING + rows * USER_HEIGHT + (rows - 1) * USER_GAP
            rect = QRectF(GROUP_X, y, GROUP_WIDTH, height)
            frame = QGraphicsPathItem(_rounded(rect, 8.0))
            frame.setPen(QPen(QColor(palette.GRIDLINE), 1.0))
            frame.setBrush(QColor(palette.PAGE))
            frame.setZValue(0)
            self.addItem(frame)
            people = count_phrase(len(members), "користувач", "користувачі", "користувачів")
            self._add_text(f"{role.name} · {people}", header_font, palette.INK_SECONDARY, QPointF(rect.left() + 12.0, rect.top() + 7.0))
            user_y = rect.top() + GROUP_HEADER + GROUP_PADDING
            for user in members:
                node_rect = QRectF(GROUP_X + (GROUP_WIDTH - USER_WIDTH) / 2, user_y, USER_WIDTH, USER_HEIGHT)
                nodes[user.id] = self._add_node(
                    SchemeNode(
                        NodeKind.USER,
                        user.id,
                        node_rect,
                        [[(user.id, id_font, palette.INK), (f"  {user.full_name}", name_font, palette.INK)]],
                        fill=palette.WHITE,
                        border=palette.AXIS,
                        border_width=1.0,
                        radius=5.0,
                        tooltip=f"{user.id} {user.full_name}\n{user.position}\nРоль: {role.name}",
                    )
                )
                user_y += USER_HEIGHT + USER_GAP
            groups[role.id] = rect
            y += height + GROUP_GAP
        return nodes, groups

    def _add_roles(
        self, enterprise: Enterprise, model: AccessModel, groups: dict[str, QRectF]
    ) -> dict[str, SchemeNode]:
        nodes: dict[str, SchemeNode] = {}
        name_font, detail_font = _font(14, True), _font(11)
        for role in enterprise.roles:
            center = groups[role.id].center().y()
            rect = QRectF(ROLE_X, center - ROLE_HEIGHT / 2, ROLE_WIDTH, ROLE_HEIGHT)
            allowed = sum(len(model.role_operations(role.id, resource.id)) for resource in enterprise.resources)
            members = len(enterprise.users_of_role(role.id))
            nodes[role.id] = self._add_node(
                SchemeNode(
                    NodeKind.ROLE,
                    role.id,
                    rect,
                    [
                        [(role.name, name_font, palette.INK)],
                        [(f"користувачів: {members}", detail_font, palette.INK_SECONDARY)],
                        [(f"дозволено операцій: {allowed}", detail_font, palette.INK_SECONDARY)],
                    ],
                    fill=palette.tint(palette.ACCENT, 0.10),
                    border=palette.ACCENT,
                    border_width=1.5,
                    radius=10.0,
                    tooltip=f"Роль «{role.name}»\n{role.description}\nСлужбових функцій: {len(role.functions)}",
                )
            )
        return nodes

    def _add_resources(self, enterprise: Enterprise, bottom: float) -> dict[str, SchemeNode]:
        nodes: dict[str, SchemeNode] = {}
        resources = enterprise.resources
        count = len(resources)
        span = max(bottom - CONTENT_TOP, count * RESOURCE_HEIGHT + (count - 1) * RESOURCE_MIN_GAP)
        gap = (span - count * RESOURCE_HEIGHT) / (count - 1) if count > 1 else 0.0
        top = CONTENT_TOP if count > 1 else CONTENT_TOP + (span - RESOURCE_HEIGHT) / 2
        id_font, detail_font, name_font = _font(13, True), _font(11), _font(12)
        for index, resource in enumerate(resources):
            rect = QRectF(RESOURCE_X, top + index * (RESOURCE_HEIGHT + gap), RESOURCE_WIDTH, RESOURCE_HEIGHT)
            details = f" · K = {resource.criticality}" + (" · критичний" if resource.critical else "")
            tooltip = f"{resource.id} «{resource.name}»\n{resource.description}\nКоефіцієнт критичності K = {resource.criticality}"
            if resource.critical:
                tooltip += "\nКритичний ресурс"
            nodes[resource.id] = self._add_node(
                SchemeNode(
                    NodeKind.RESOURCE,
                    resource.id,
                    rect,
                    [
                        [(resource.id, id_font, palette.INK), (details, detail_font, palette.INK_SECONDARY)],
                        [(resource.name, name_font, palette.INK)],
                    ],
                    fill=palette.WHITE,
                    border=palette.STATUS_CRITICAL if resource.critical else palette.AXIS,
                    border_width=3.0 if resource.critical else 1.2,
                    radius=8.0,
                    tooltip=tooltip,
                )
            )
        return nodes

    @staticmethod
    def _assign_ports(specs: list[_EdgeSpec]) -> None:
        """Розподіляє точки підключення так, щоб ребра біля вузлів не перетиналися."""
        outgoing: dict[str, list[_EdgeSpec]] = {}
        incoming: dict[str, list[_EdgeSpec]] = {}
        for spec in specs:
            outgoing.setdefault(spec.source.key, []).append(spec)
            incoming.setdefault(spec.target.key, []).append(spec)
        for edges in outgoing.values():
            edges.sort(key=lambda spec: spec.target.rect.center().y())
            for slot, spec in enumerate(edges):
                spec.start = spec.source.right_port(slot, len(edges))
        for edges in incoming.values():
            edges.sort(key=lambda spec: spec.start.y())
            for slot, spec in enumerate(edges):
                spec.end = spec.target.left_port(slot, len(edges))

    def _place_label(self, path: QPainterPath, text: str, font: QFont, positions: tuple[float, ...]) -> QPointF:
        """Перша позиція вздовж ребра, де підпис не перекриває вузли й інші підписи."""
        for position in positions:
            center = path.pointAtPercent(position)
            rect = _label_rect(text, font, center).adjusted(-3.0, -3.0, 3.0, 3.0)
            if not any(rect.intersects(other) for other in self._label_rects + self._obstacles):
                self._label_rects.append(rect)
                return center
        center = path.pointAtPercent(positions[0])
        self._label_rects.append(_label_rect(text, font, center))
        return center

    def _add_edges(
        self,
        enterprise: Enterprise,
        model: AccessModel,
        users: dict[str, SchemeNode],
        roles: dict[str, SchemeNode],
        resources: dict[str, SchemeNode],
    ) -> list[tuple[_EdgeSpec, list[QGraphicsItem]]]:
        specs = [_EdgeSpec("member", users[user.id], roles[user.role_id], NO_OPERATIONS) for user in enterprise.users]
        for role in enterprise.roles:
            for resource in enterprise.resources:
                operations = model.role_operations(role.id, resource.id)
                if operations:
                    specs.append(_EdgeSpec("role", roles[role.id], resources[resource.id], operations))
        for user in enterprise.users:
            for resource in enterprise.resources:
                grant_operations = model.grant_operations(user.id, resource.id)
                if grant_operations:
                    specs.append(_EdgeSpec("grant", users[user.id], resources[resource.id], grant_operations))
        self._assign_ports(specs)
        label_font = _font(11, True)
        built: list[tuple[_EdgeSpec, list[QGraphicsItem]]] = []
        for spec in specs:
            path = _curve(spec.start, spec.end)
            edge = QGraphicsPathItem(path)
            items: list[QGraphicsItem] = [edge]
            if spec.kind == "member":
                pen = QPen(QColor(palette.AXIS), MEMBER_WIDTH)
                edge.setZValue(1)
            elif spec.kind == "role":
                level = cell_level(spec.operations)
                pen = QPen(QColor(palette.CELL_STROKE[level]), EDGE_WIDTH[level])
                edge.setZValue(2)
                text = operations_code(spec.operations)
                center = self._place_label(path, text, label_font, ROLE_LABEL_POSITIONS)
                items.append(
                    EdgeLabel(
                        text, center, font=label_font, ink=palette.INK,
                        fill=palette.CELL_FILL[level], border=palette.CELL_STROKE[level],
                    )
                )
            else:
                pen = QPen(QColor(palette.STATUS_CRITICAL), GRANT_WIDTH)
                pen.setDashPattern([5.0, 3.0])
                edge.setZValue(1.5)
                text = "+" + operations_code(spec.operations)
                center = self._place_label(path, text, label_font, GRANT_LABEL_POSITIONS)
                items.append(
                    EdgeLabel(
                        text, center, font=label_font, ink=palette.GRANT_INK,
                        fill=palette.WHITE, border=palette.STATUS_CRITICAL, dashed=True,
                    )
                )
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            edge.setPen(pen)
            for item in items:
                if item is not edge:
                    self.addItem(item)
            self.addItem(edge)
            self._dimmable.extend(items)
            built.append((spec, items))
        return built

    def _register_links(
        self,
        enterprise: Enterprise,
        users: dict[str, SchemeNode],
        roles: dict[str, SchemeNode],
        resources: dict[str, SchemeNode],
        built: list[tuple[_EdgeSpec, list[QGraphicsItem]]],
    ) -> None:
        """Для кожного вузла запам'ятовує елементи, які підсвічуються при наведенні."""
        member: dict[str, list[QGraphicsItem]] = {}
        role_edges: dict[str, list[tuple[list[QGraphicsItem], str]]] = {}
        user_grants: dict[str, list[tuple[list[QGraphicsItem], str]]] = {}
        resource_grants: dict[str, list[tuple[list[QGraphicsItem], str]]] = {}
        for spec, edge_group in built:
            source, target = spec.source.entity_id, spec.target.entity_id
            if spec.kind == "member":
                member[source] = edge_group
            elif spec.kind == "role":
                role_edges.setdefault(source, []).append((edge_group, target))
            else:
                user_grants.setdefault(source, []).append((edge_group, target))
                resource_grants.setdefault(target, []).append((edge_group, source))

        def users_with_membership(role_id: str) -> list[QGraphicsItem]:
            linked: list[QGraphicsItem] = []
            for user in enterprise.users_of_role(role_id):
                linked += [users[user.id], *member.get(user.id, [])]
            return linked

        for user in enterprise.users:
            items: list[QGraphicsItem] = [users[user.id], roles[user.role_id], *member.get(user.id, [])]
            for edge_items, resource_id in role_edges.get(user.role_id, []) + user_grants.get(user.id, []):
                items += [*edge_items, resources[resource_id]]
            self._links[users[user.id].key] = {id(item) for item in items}
        for role in enterprise.roles:
            items = [roles[role.id], *users_with_membership(role.id)]
            for edge_items, resource_id in role_edges.get(role.id, []):
                items += [*edge_items, resources[resource_id]]
            self._links[roles[role.id].key] = {id(item) for item in items}
        for resource in enterprise.resources:
            items = [resources[resource.id]]
            for role in enterprise.roles:
                for edge_items, resource_id in role_edges.get(role.id, []):
                    if resource_id == resource.id:
                        items += [*edge_items, roles[role.id], *users_with_membership(role.id)]
            for edge_items, user_id in resource_grants.get(resource.id, []):
                items += [*edge_items, users[user_id]]
            self._links[resources[resource.id].key] = {id(item) for item in items}

    def _add_legend(self, top: float) -> None:
        """Умовні позначення під схемою (потрапляють і в експорт)."""
        self._add_text("Умовні позначення", _font(12, True), palette.INK_SECONDARY, QPointF(GROUP_X, top))
        entries: list[tuple[str, str, float, bool, str]] = [
            ("line", palette.CELL_STROKE[CellLevel.READ], EDGE_WIDTH[CellLevel.READ], False, "права ролі: лише читання (Ч)"),
            ("line", palette.CELL_STROKE[CellLevel.MODIFY], EDGE_WIDTH[CellLevel.MODIFY], False, "права ролі: є запис / редагування (З, Р)"),
            ("line", palette.CELL_STROKE[CellLevel.DELETE], EDGE_WIDTH[CellLevel.DELETE], False, "права ролі: є видалення (В)"),
            ("line", palette.STATUS_CRITICAL, GRANT_WIDTH, True, "індивідуальний дозвіл поза роллю"),
            ("line", palette.AXIS, MEMBER_WIDTH, False, "належність користувача до ролі"),
            ("box", palette.STATUS_CRITICAL, 3.0, False, "критичний ресурс"),
        ]
        font = _font(12)
        for index, (kind, color, width, dashed, text) in enumerate(entries):
            x = GROUP_X + (index % 3) * 420.0
            y = top + 28.0 + (index // 3) * 26.0
            pen = QPen(QColor(color), width)
            if dashed:
                pen.setDashPattern([5.0, 3.0])
            if kind == "line":
                sample = QPainterPath(QPointF(x, y + 8.0))
                sample.lineTo(QPointF(x + 40.0, y + 8.0))
                self.addPath(sample, pen)
            else:
                self.addPath(_rounded(QRectF(x + 2.0, y, 36.0, 16.0), 4.0), pen)
            self._add_text(text, font, palette.INK_SECONDARY, QPointF(x + 52.0, y))


def render_image(scene: QGraphicsScene, scale: float = 2.0) -> QImage:
    """Растрове зображення всієї сцени (scale — множник роздільності)."""
    if isinstance(scene, SchemeScene):
        scene.clear_highlight()
    source = scene.sceneRect()
    image = QImage(
        max(int(source.width() * scale), 1),
        max(int(source.height() * scale), 1),
        QImage.Format.Format_ARGB32_Premultiplied,
    )
    image.fill(QColor(palette.SURFACE))
    painter = QPainter(image)
    painter.setRenderHints(
        QPainter.RenderHint.Antialiasing
        | QPainter.RenderHint.TextAntialiasing
        | QPainter.RenderHint.SmoothPixmapTransform
    )
    scene.render(painter, QRectF(0.0, 0.0, image.width(), image.height()), source)
    painter.end()
    return image


def _with_suffix(path: str | Path, suffix: str) -> Path:
    """Шлях із потрібним розширенням (додається, якщо користувач його не вказав)."""
    target = Path(path)
    return target if target.suffix.lower() == suffix else target.with_name(target.name + suffix)


def export_png(scene: QGraphicsScene, path: str | Path, scale: float = 2.0) -> Path:
    """Зберігає схему в PNG (за замовчуванням удвічі більшої роздільності); повертає шлях."""
    target = _with_suffix(path, ".png")
    if not render_image(scene, scale).save(str(target)):
        raise OSError(f"Не вдалося записати файл «{target}».")
    return target


def export_svg(scene: QGraphicsScene, path: str | Path, title: str) -> Path:
    """Зберігає схему у векторному форматі SVG; повертає шлях."""
    target = _with_suffix(path, ".svg")
    if isinstance(scene, SchemeScene):
        scene.clear_highlight()
    source = scene.sceneRect()
    width, height = int(source.width()), int(source.height())
    generator = QSvgGenerator()
    generator.setFileName(str(target))
    generator.setSize(QSize(width, height))
    generator.setViewBox(QRectF(0.0, 0.0, width, height))
    generator.setTitle(title)
    generator.setDescription("Структурна схема: користувачі → ролі → інформаційні ресурси")
    painter = QPainter()
    if not painter.begin(generator):
        raise OSError(f"Не вдалося записати файл «{target}».")
    painter.fillRect(QRectF(0.0, 0.0, width, height), QColor(palette.SURFACE))
    scene.render(painter, QRectF(0.0, 0.0, width, height), source)
    painter.end()
    return target
