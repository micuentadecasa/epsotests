"""Deterministic visual abstract reasoning question generation.

The generator deliberately keeps the scene model, rules, rendered SVG, answer
mutations, and explanation together.  A question is therefore portable JSON:
it can be reviewed, regenerated from its seed, or rendered without a browser or
an image library.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import html
import json
import math
import random
from typing import Any, Iterable, Mapping, Sequence


PALETTE = ("#2563eb", "#dc2626", "#16a34a", "#9333ea", "#ea580c", "#0891b2")
SHAPES = ("circle", "square", "triangle", "diamond", "star")


def _clamp(value: float, low: float = 0.08, high: float = 0.92) -> float:
    return max(low, min(high, float(value)))


def _wrap_angle(value: float) -> float:
    result = float(value) % 360
    return 0.0 if result == 0 else result


def _as_number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _jsonable(value: Any) -> Any:
    if isinstance(value, Rule):
        return value.to_dict()
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


@dataclass(frozen=True)
class Element:
    """A vector primitive in normalized scene coordinates.

    ``x`` and ``y`` are in the range 0..1.  Child elements use coordinates
    relative to their containing element.  Keeping all attributes explicit
    makes scene serialization stable and gives distractors useful mutation
    targets beyond just changing a shape.
    """

    id: str
    shape: str = "circle"
    x: float = 0.5
    y: float = 0.5
    size: float = 0.22
    rotation: float = 0.0
    fill: str = "#2563eb"
    shaded: bool = True
    stroke: str = "#111827"
    line_count: int = 1
    symmetry: int = 1
    marker: str | None = None
    marker_position: float = 0.5
    children: tuple["Element", ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "shape": self.shape,
            "x": round(self.x, 6),
            "y": round(self.y, 6),
            "size": round(self.size, 6),
            "rotation": round(_wrap_angle(self.rotation), 6),
            "fill": self.fill,
            "shaded": self.shaded,
            "stroke": self.stroke,
            "lineCount": int(self.line_count),
            "symmetry": int(self.symmetry),
            "marker": self.marker,
            "markerPosition": round(self.marker_position, 6),
            "children": [child.to_dict() for child in self.children],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Element":
        return cls(
            id=str(data["id"]),
            shape=str(data.get("shape", "circle")),
            x=_as_number(data.get("x"), 0.5),
            y=_as_number(data.get("y"), 0.5),
            size=_as_number(data.get("size"), 0.22),
            rotation=_as_number(data.get("rotation"), 0),
            fill=str(data.get("fill", "#2563eb")),
            shaded=bool(data.get("shaded", True)),
            stroke=str(data.get("stroke", "#111827")),
            line_count=max(1, int(data.get("lineCount", data.get("line_count", 1)))),
            symmetry=max(1, int(data.get("symmetry", 1))),
            marker=data.get("marker"),
            marker_position=_as_number(
                data.get("markerPosition", data.get("marker_position")), 0.5
            ),
            children=tuple(cls.from_dict(child) for child in data.get("children", [])),
        )


@dataclass(frozen=True)
class Scene:
    """A deterministic collection of vector elements."""

    elements: tuple[Element, ...] = field(default_factory=tuple)
    background: str = "#ffffff"

    def to_dict(self) -> dict[str, Any]:
        return {
            "background": self.background,
            "elements": [element.to_dict() for element in self.elements],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Scene":
        return cls(
            elements=tuple(Element.from_dict(item) for item in data.get("elements", [])),
            background=str(data.get("background", "#ffffff")),
        )

    def signature(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class Rule:
    """A serializable visual transformation.

    ``parameters`` intentionally remains a JSON-shaped mapping rather than an
    enum or a set of subclasses.  This lets callers store new difficulty
    parameters without changing the question schema.
    """

    kind: str
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", str(self.kind))
        object.__setattr__(self, "parameters", dict(self.parameters))

    @property
    def params(self) -> Mapping[str, Any]:
        """Short alias useful to callers constructing rule inspectors."""

        return self.parameters

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "parameters": _jsonable(dict(self.parameters))}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Rule":
        return cls(str(data["kind"]), dict(data.get("parameters", data.get("params", {}))))


# Small constructors keep generated rule data readable while Rule remains the
# only representation crossing the JSON boundary.
def make_rule(kind: str, **parameters: Any) -> Rule:
    return Rule(kind, parameters)


def rotation(degrees: float = 90) -> Rule:
    return Rule("rotation", {"degrees": degrees})


def reflection(axis: str = "vertical") -> Rule:
    return Rule("reflection", {"axis": axis})


def translation(dx: float = 0.1, dy: float = 0.0) -> Rule:
    return Rule("translation", {"dx": dx, "dy": dy})


def alternation(property: str = "shaded") -> Rule:
    return Rule("alternation", {"property": property})


def element_count(delta: int = 1) -> Rule:
    return Rule("element-count", {"delta": delta})


def shape_change(shapes: Sequence[str] = SHAPES) -> Rule:
    return Rule("shape-change", {"shapes": list(shapes)})


def fill(shaded: bool | None = None) -> Rule:
    return Rule("fill", {} if shaded is None else {"shaded": shaded})


def color_change(colors: Sequence[str] = PALETTE) -> Rule:
    return Rule("color-change", {"colors": list(colors)})


def symmetry(order: int = 2) -> Rule:
    return Rule("symmetry", {"order": order})


def nesting(action: str = "add") -> Rule:
    return Rule("nesting", {"action": action})


def line_count(delta: int = 1) -> Rule:
    return Rule("line-count", {"delta": delta})


def serialize_rule(rule: Rule) -> dict[str, Any]:
    return rule.to_dict()


def deserialize_rule(data: Mapping[str, Any]) -> Rule:
    return Rule.from_dict(data)


def serialize_scene(scene: Scene) -> dict[str, Any]:
    return scene.to_dict()


def deserialize_scene(data: Mapping[str, Any]) -> Scene:
    return Scene.from_dict(data)


def _target_indices(scene: Scene, parameters: Mapping[str, Any]) -> list[int]:
    target = parameters.get("target", "all")
    if target in ("all", None):
        return list(range(len(scene.elements)))
    if isinstance(target, int) and 0 <= target < len(scene.elements):
        return [target]
    return [index for index, element in enumerate(scene.elements) if element.id == str(target)]


def _with_element(scene: Scene, index: int, element: Element) -> Scene:
    elements = list(scene.elements)
    elements[index] = element
    return replace(scene, elements=tuple(elements))


def _apply_rotation(scene: Scene, degrees: float, frame_index: int, parameters: Mapping[str, Any]) -> Scene:
    amount = degrees * frame_index
    for index in _target_indices(scene, parameters):
        element = scene.elements[index]
        scene = _with_element(scene, index, replace(element, rotation=_wrap_angle(element.rotation + amount)))
    return scene


def _apply_translation(
    scene: Scene, dx: float, dy: float, frame_index: int, parameters: Mapping[str, Any]
) -> Scene:
    for index in _target_indices(scene, parameters):
        element = scene.elements[index]
        scene = _with_element(
            scene,
            index,
            replace(element, x=_clamp(element.x + dx * frame_index), y=_clamp(element.y + dy * frame_index)),
        )
    return scene


def _apply_reflection(scene: Scene, axis: str, parameters: Mapping[str, Any], frame_index: int) -> Scene:
    if frame_index == 0 or frame_index % 2 == 0:
        return scene
    axis = axis.lower()
    for index in _target_indices(scene, parameters):
        element = scene.elements[index]
        if axis in ("vertical", "y"):
            changed = replace(
                element,
                x=_clamp(1 - element.x),
                rotation=_wrap_angle(-element.rotation),
                marker_position=(1 - element.marker_position) % 1,
            )
        elif axis in ("horizontal", "x"):
            changed = replace(
                element,
                y=_clamp(1 - element.y),
                rotation=_wrap_angle(-element.rotation),
                marker_position=(0.5 - element.marker_position) % 1,
            )
        else:
            changed = replace(
                element,
                x=_clamp(1 - element.x),
                y=_clamp(1 - element.y),
                marker_position=(element.marker_position + 0.5) % 1,
            )
        scene = _with_element(scene, index, changed)
    return scene


def _apply_alternation(scene: Scene, parameters: Mapping[str, Any], frame_index: int) -> Scene:
    if frame_index == 0:
        return scene
    property_name = str(parameters.get("property", "shaded"))
    values = parameters.get("values")
    for index in _target_indices(scene, parameters):
        element = scene.elements[index]
        if values:
            value = values[frame_index % len(values)]
        elif property_name in ("shaded", "fill"):
            value = element.shaded if frame_index % 2 == 0 else not element.shaded
        else:
            value = None
        if property_name == "shaded":
            changed = replace(element, shaded=bool(value))
        elif property_name == "fill":
            fill_value = value if isinstance(value, str) else PALETTE[frame_index % len(PALETTE)]
            changed = replace(element, fill=fill_value, shaded=True)
        elif property_name == "shape":
            changed = replace(element, shape=str(value))
        elif property_name in ("rotation", "orientation"):
            changed = replace(element, rotation=_wrap_angle(_as_number(value)))
        elif property_name == "marker":
            changed = replace(element, marker=None if value is None else str(value))
        else:
            changed = element
        scene = _with_element(scene, index, changed)
    return scene


def _apply_count(scene: Scene, delta: int, frame_index: int, parameters: Mapping[str, Any]) -> Scene:
    desired_delta = int(delta) * frame_index
    if desired_delta > 0:
        elements = list(scene.elements)
        template = elements[-1] if elements else Element("element-0")
        for offset in range(desired_delta):
            new_id = f"added-{frame_index}-{offset + 1}"
            elements.append(
                replace(
                    template,
                    id=new_id,
                    x=_clamp(template.x + 0.08 * (offset + 1)),
                    y=_clamp(template.y + 0.08 * (offset + 1)),
                    marker=None,
                    children=(),
                )
            )
        return replace(scene, elements=tuple(elements))
    if desired_delta < 0:
        keep = max(0, len(scene.elements) + desired_delta)
        return replace(scene, elements=scene.elements[:keep])
    return scene


def _apply_shape_change(scene: Scene, parameters: Mapping[str, Any], frame_index: int) -> Scene:
    if frame_index == 0:
        return scene
    shapes = tuple(str(shape) for shape in parameters.get("shapes", SHAPES)) or SHAPES
    for index in _target_indices(scene, parameters):
        element = scene.elements[index]
        scene = _with_element(scene, index, replace(element, shape=shapes[frame_index % len(shapes)]))
    return scene


def _apply_fill(scene: Scene, parameters: Mapping[str, Any], frame_index: int) -> Scene:
    if frame_index == 0:
        return scene
    for index in _target_indices(scene, parameters):
        element = scene.elements[index]
        if "shaded" in parameters:
            shaded = bool(parameters["shaded"])
        else:
            shaded = element.shaded if frame_index % 2 == 0 else not element.shaded
        scene = _with_element(scene, index, replace(element, shaded=shaded))
    return scene


def _apply_color(scene: Scene, parameters: Mapping[str, Any], frame_index: int) -> Scene:
    if frame_index == 0:
        return scene
    colors = tuple(str(color) for color in parameters.get("colors", PALETTE)) or PALETTE
    for index in _target_indices(scene, parameters):
        element = scene.elements[index]
        scene = _with_element(
            scene,
            index,
            replace(element, fill=colors[frame_index % len(colors)], shaded=True),
        )
    return scene


def _apply_symmetry(scene: Scene, parameters: Mapping[str, Any], frame_index: int) -> Scene:
    if frame_index == 0:
        return scene
    order = max(1, int(parameters.get("order", parameters.get("count", 2))))
    for index in _target_indices(scene, parameters):
        scene = _with_element(scene, index, replace(scene.elements[index], symmetry=order))
    return scene


def _apply_nesting(scene: Scene, parameters: Mapping[str, Any], frame_index: int) -> Scene:
    if frame_index == 0:
        return scene
    action = str(parameters.get("action", "add")).lower()
    for index in _target_indices(scene, parameters):
        element = scene.elements[index]
        if action in ("remove", "delete"):
            changed = replace(element, children=())
        else:
            inner_shape = str(parameters.get("shape", "circle" if element.shape != "circle" else "diamond"))
            child = Element(
                id=f"{element.id}-inner",
                shape=inner_shape,
                x=0.5,
                y=0.5,
                size=0.46,
                rotation=-element.rotation,
                fill=str(parameters.get("fill", "#ffffff")),
                shaded=bool(parameters.get("shaded", False)),
                stroke=element.stroke,
                line_count=1,
            )
            changed = replace(element, children=(child,))
        scene = _with_element(scene, index, changed)
    return scene


def _apply_line_count(scene: Scene, parameters: Mapping[str, Any], frame_index: int) -> Scene:
    delta = int(parameters.get("delta", 1))
    for index in _target_indices(scene, parameters):
        element = scene.elements[index]
        scene = _with_element(scene, index, replace(element, line_count=max(1, element.line_count + delta * frame_index)))
    return scene


def _apply_marker(scene: Scene, parameters: Mapping[str, Any], frame_index: int) -> Scene:
    if frame_index == 0:
        return scene
    movement = _as_number(parameters.get("delta", parameters.get("movement", 0.2)), 0.2)
    for index in _target_indices(scene, parameters):
        element = scene.elements[index]
        scene = _with_element(
            scene,
            index,
            replace(
                element,
                marker=str(parameters.get("marker", element.marker or "dot")),
                marker_position=(element.marker_position + movement * frame_index) % 1,
            ),
        )
    return scene


def apply_rule(scene: Scene, rule: Rule, frame_index: int = 1) -> Scene:
    """Apply one rule to a scene.

    ``frame_index`` is one-based for a transformed frame and zero-based for a
    source frame.  Additive rules are cumulative from the source scene, which
    makes direct regeneration of frame N independent of earlier frames.
    """

    if not isinstance(rule, Rule):
        rule = Rule.from_dict(rule)  # type: ignore[arg-type]
    frame_index = max(0, int(frame_index))
    kind = rule.kind.lower().replace("_", "-")
    parameters = rule.parameters
    if kind in ("composite", "combined"):
        result = scene
        nested = parameters.get("rules", ())
        for nested_rule in nested:
            result = apply_rule(result, nested_rule if isinstance(nested_rule, Rule) else Rule.from_dict(nested_rule), frame_index)
        return result
    if kind in ("rotation", "orientation"):
        return _apply_rotation(scene, _as_number(parameters.get("degrees", parameters.get("angle", 90)), 90), frame_index, parameters)
    if kind in ("translation", "movement", "position"):
        return _apply_translation(
            scene,
            _as_number(parameters.get("dx", parameters.get("x", 0.1)), 0.1),
            _as_number(parameters.get("dy", parameters.get("y", 0)), 0),
            frame_index,
            parameters,
        )
    if kind in ("reflection", "reflect"):
        return _apply_reflection(scene, str(parameters.get("axis", "vertical")), parameters, frame_index)
    if kind in ("alternation", "alternate"):
        return _apply_alternation(scene, parameters, frame_index)
    if kind in ("element-count", "count", "shape-addition", "shape-removal"):
        delta = int(parameters.get("delta", 1))
        if kind in ("shape-removal",):
            delta = -abs(delta)
        return _apply_count(scene, delta, frame_index, parameters)
    if kind in ("shape-change", "shape", "shape-cycling"):
        return _apply_shape_change(scene, parameters, frame_index)
    if kind in ("fill", "shading", "shade"):
        return _apply_fill(scene, parameters, frame_index)
    if kind in ("color-change", "colour-change", "color", "colour"):
        return _apply_color(scene, parameters, frame_index)
    if kind == "symmetry":
        return _apply_symmetry(scene, parameters, frame_index)
    if kind in ("nesting", "containment"):
        return _apply_nesting(scene, parameters, frame_index)
    if kind in ("line-count", "lines"):
        return _apply_line_count(scene, parameters, frame_index)
    if kind in ("marker", "marker-movement"):
        return _apply_marker(scene, parameters, frame_index)
    raise ValueError(f"Unsupported visual rule: {rule.kind}")


def apply_rules(scene: Scene, rules: Iterable[Rule], frame_index: int = 1) -> Scene:
    result = scene
    for rule in rules:
        result = apply_rule(result, rule, frame_index)
    return result


def _points_for_shape(shape: str, cx: float, cy: float, radius: float, rotation_degrees: float) -> str:
    sides = {"triangle": 3, "diamond": 4, "square": 4, "star": 10}.get(shape, 0)
    if not sides:
        return ""
    start = math.radians(rotation_degrees - 90)
    points: list[str] = []
    if shape == "star":
        for index in range(10):
            radius_for_point = radius if index % 2 == 0 else radius * 0.45
            angle = start + index * math.pi / 5
            points.append(f"{cx + radius_for_point * math.cos(angle):.3f},{cy + radius_for_point * math.sin(angle):.3f}")
    elif shape == "diamond":
        for index in range(4):
            angle = start + index * math.pi / 2
            points.append(f"{cx + radius * math.cos(angle):.3f},{cy + radius * math.sin(angle):.3f}")
    else:
        for index in range(sides):
            angle = start + index * 2 * math.pi / sides
            points.append(f"{cx + radius * math.cos(angle):.3f},{cy + radius * math.sin(angle):.3f}")
    return " ".join(points)


def _element_svg(
    element: Element,
    width: int,
    height: int,
    parent: tuple[float, float, float, float] | None = None,
    id_suffix: str = "",
) -> str:
    if parent is None:
        cx, cy, size = element.x * width, element.y * height, element.size * min(width, height)
        render_rotation = element.rotation
    else:
        parent_x, parent_y, parent_size, parent_rotation = parent
        relative_x = (element.x - 0.5) * parent_size
        relative_y = (element.y - 0.5) * parent_size
        parent_angle = math.radians(parent_rotation)
        cx = parent_x + relative_x * math.cos(parent_angle) - relative_y * math.sin(parent_angle)
        cy = parent_y + relative_x * math.sin(parent_angle) + relative_y * math.cos(parent_angle)
        size = element.size * parent_size
        render_rotation = element.rotation + parent_rotation
    fill_value = html.escape(element.fill if element.shaded else "none", quote=True)
    stroke_value = html.escape(element.stroke, quote=True)
    element_id = html.escape(element.id + id_suffix, quote=True)
    radius = size / 2
    pieces: list[str] = []
    shape = element.shape.lower()
    common = f'fill="{fill_value}" stroke="{stroke_value}" stroke-width="2"'
    if shape == "circle":
        pieces.append(f'<circle data-element-id="{element_id}" cx="{cx:.3f}" cy="{cy:.3f}" r="{radius:.3f}" {common}/>')
    elif shape == "line":
        for line_index in range(max(1, element.line_count)):
            offset = (line_index - (element.line_count - 1) / 2) * size * 0.12
            pieces.append(
                f'<line data-element-id="{element_id}-{line_index}" x1="{cx - radius:.3f}" y1="{cy + offset:.3f}" '
                f'x2="{cx + radius:.3f}" y2="{cy + offset:.3f}" transform="rotate({render_rotation:.3f} {cx:.3f} {cy:.3f})" {common}/>'
            )
    elif shape == "square":
        pieces.append(
            f'<rect data-element-id="{element_id}" x="{cx - radius:.3f}" y="{cy - radius:.3f}" '
            f'width="{size:.3f}" height="{size:.3f}" transform="rotate({render_rotation:.3f} {cx:.3f} {cy:.3f})" {common}/>'
        )
    else:
        points = _points_for_shape(shape, cx, cy, radius, render_rotation)
        pieces.append(f'<polygon data-element-id="{element_id}" points="{points}" {common}/>')
    if shape in ("circle", "square", "diamond", "triangle", "star"):
        orientation_angle = math.radians(render_rotation - 90)
        orientation_x = cx + radius * 0.62 * math.cos(orientation_angle)
        orientation_y = cy + radius * 0.62 * math.sin(orientation_angle)
        pieces.append(
            f'<line data-orientation="{element_id}" x1="{cx:.3f}" y1="{cy:.3f}" '
            f'x2="{orientation_x:.3f}" y2="{orientation_y:.3f}" stroke="{stroke_value}" stroke-width="1"/>'
        )
    if shape != "line" and element.line_count > 1:
        # Line-count is visible for every primitive, not only for an explicit
        # line shape, so a line-count rule cannot become metadata-only.
        for line_index in range(element.line_count):
            offset = (line_index - (element.line_count - 1) / 2) * radius * 0.22
            pieces.append(
                f'<line data-line-count="{element_id}-{line_index}" x1="{cx - radius * 0.55:.3f}" '
                f'y1="{cy + offset:.3f}" x2="{cx + radius * 0.55:.3f}" y2="{cy + offset:.3f}" '
                f'stroke="{stroke_value}" stroke-width="1"/>'
            )
    if element.marker:
        marker_angle = 2 * math.pi * element.marker_position - math.pi / 2 + math.radians(render_rotation)
        marker_x = cx + radius * 0.68 * math.cos(marker_angle)
        marker_y = cy + radius * 0.68 * math.sin(marker_angle)
        marker_name = html.escape(element.marker, quote=True)
        if element.marker == "cross":
            pieces.append(
                f'<path data-marker="{marker_name}" d="M {marker_x - 4:.3f} {marker_y:.3f} L {marker_x + 4:.3f} {marker_y:.3f} '
                f'M {marker_x:.3f} {marker_y - 4:.3f} L {marker_x:.3f} {marker_y + 4:.3f}" stroke="{stroke_value}" stroke-width="2"/>'
            )
        else:
            pieces.append(f'<circle data-marker="{marker_name}" cx="{marker_x:.3f}" cy="{marker_y:.3f}" r="3" fill="{stroke_value}"/>')
    for child in element.children:
        pieces.append(_element_svg(child, width, height, (cx, cy, size, render_rotation), id_suffix + "-nested"))
    if element.symmetry > 1 and parent is None:
        # Symmetry is a scene-visible property, not only metadata.  Mirror
        # copies are rendered around the element while retaining stable IDs.
        for copy_index in range(1, element.symmetry):
            angle = 2 * math.pi * copy_index / element.symmetry
            copy_x = _clamp(element.x + math.cos(angle) * element.size * 0.65) * width
            copy_y = _clamp(element.y + math.sin(angle) * element.size * 0.65) * height
            copy = replace(element, x=copy_x / width, y=copy_y / height, symmetry=1)
            pieces.append(_element_svg(copy, width, height, None, f"-symmetry-{copy_index}"))
    return "".join(pieces)


def render_svg(scene: Scene, width: int = 160, height: int = 160) -> str:
    """Render a scene to stable, dependency-free SVG.

    Rendering the canonical serialized values prevents a figure loaded from
    JSON from differing by a final floating-point digit from its source.
    """

    scene = Scene.from_dict(scene.to_dict())
    background = html.escape(scene.background, quote=True)
    content = "".join(_element_svg(element, width, height) for element in scene.elements)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{int(width)}" height="{int(height)}" '
        f'viewBox="0 0 {int(width)} {int(height)}" role="img" aria-label="visual reasoning figure">'
        f'<rect width="100%" height="100%" fill="{background}"/>{content}</svg>'
    )


def _base_scene(seed: int, difficulty: str | int = "medium") -> Scene:
    rng = random.Random(seed)
    level = _difficulty_name(difficulty)
    count = {"easy": 1, "medium": 2, "hard": 3}[level]
    elements: list[Element] = []
    for index in range(count):
        elements.append(
            Element(
                id=f"element-{index + 1}",
                shape=rng.choice(SHAPES),
                x=0.27 + index * 0.22 + rng.random() * 0.08,
                y=0.35 + (index % 2) * 0.28 + rng.random() * 0.08,
                size=0.18 + rng.random() * 0.08,
                rotation=float(rng.choice((0, 0, 45, 90))),
                fill=rng.choice(PALETTE),
                shaded=True,
                line_count=1,
                marker="dot" if level in ("easy", "hard") and index == 0 else None,
            )
        )
    return Scene(tuple(elements))


def _difficulty_name(difficulty: str | int) -> str:
    if isinstance(difficulty, int):
        return ("easy", "medium", "hard")[max(0, min(2, difficulty - 1))]
    value = str(difficulty).lower()
    if value in ("1", "easy", "low"):
        return "easy"
    if value in ("3", "hard", "high"):
        return "hard"
    return "medium"


def _default_sequence_rules(level: str) -> list[Rule]:
    if level == "easy":
        return [rotation(90)]
    if level == "hard":
        return [
            Rule("composite", {"rules": [rotation(90), translation(0.08, 0.05)]}),
            color_change(("#2563eb", "#dc2626", "#16a34a")),
        ]
    return [Rule("composite", {"rules": [rotation(90), translation(0.08, 0)]})]


def _default_matrix_rules(level: str, size: int) -> tuple[Rule, Rule]:
    if level == "easy":
        return rotation(90), fill()
    if level == "hard":
        return (
            Rule("composite", {"rules": [rotation(90), translation(0.07, 0.04)]}),
            Rule("composite", {"rules": [reflection("vertical"), color_change(("#2563eb", "#dc2626", "#16a34a"))]}),
        )
    return rotation(90), translation(0, 0.1)


def _normalize_rules(rules: Sequence[Rule]) -> list[Rule]:
    return [rule if isinstance(rule, Rule) else Rule.from_dict(rule) for rule in rules]  # type: ignore[arg-type]


def _rules_for_sequence(rules: Sequence[Rule] | None, level: str) -> list[Rule]:
    return _normalize_rules(rules) if rules is not None else _default_sequence_rules(level)


def _figure(scene: Scene, figure_id: str) -> dict[str, Any]:
    return {"id": figure_id, "scene": scene.to_dict(), "svg": render_svg(scene)}


def _rule_label(rule: Rule) -> str:
    kind = rule.kind.lower().replace("_", "-")
    p = rule.parameters
    if kind in ("rotation", "orientation"):
        return f"rotate by {_as_number(p.get('degrees', p.get('angle', 90))):g}°"
    if kind in ("translation", "movement", "position"):
        return f"move by ({_as_number(p.get('dx', p.get('x', 0.1))):g}, {_as_number(p.get('dy', p.get('y', 0))):g})"
    if kind in ("reflection", "reflect"):
        return f"reflect across the {p.get('axis', 'vertical')} axis"
    if kind in ("alternation", "alternate"):
        return f"alternate {p.get('property', 'shading')}"
    if kind in ("element-count", "count", "shape-addition", "shape-removal"):
        return f"change the element count by {int(p.get('delta', 1))}"
    if kind in ("shape-change", "shape", "shape-cycling"):
        return "cycle the shape"
    if kind in ("fill", "shading", "shade"):
        return "change the fill/shading"
    if kind in ("color-change", "colour-change", "color", "colour"):
        return "change colour"
    if kind == "symmetry":
        return f"use {int(p.get('order', 2))}-way symmetry"
    if kind in ("nesting", "containment"):
        return f"{p.get('action', 'add')} a nested shape"
    if kind in ("line-count", "lines"):
        return f"change the line count by {int(p.get('delta', 1))}"
    if kind in ("marker", "marker-movement"):
        return "move the marker"
    if kind in ("composite", "combined"):
        return " and ".join(_rule_label(Rule.from_dict(item) if not isinstance(item, Rule) else item) for item in p.get("rules", []))
    return rule.kind


def _rule_sentence(rules: Sequence[Rule]) -> str:
    labels = [_rule_label(rule) for rule in rules]
    if not labels:
        return "no change"
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} and {labels[1]}"
    return ", ".join(labels[:-1]) + f", and {labels[-1]}"


def _mutated(scene: Scene, mutation: str, reference: Scene, rules: Sequence[Rule]) -> tuple[Scene, dict[str, Any]]:
    elements = list(scene.elements)
    if not elements:
        return Scene((Element("distractor"),)), {"kind": mutation, "description": mutation}
    first = elements[0]
    if mutation == "partial-rule":
        partial = apply_rule(reference, rules[0]) if rules else reference
        return partial, {"kind": mutation, "description": "applies only part of the composite rule"}
    if mutation == "wrong-direction":
        if first.x < 0.5:
            changed = replace(first, x=_clamp(first.x - 0.12))
        else:
            changed = replace(first, x=_clamp(first.x + 0.12))
        elements[0] = changed
        return Scene(tuple(elements), scene.background), {"kind": mutation, "description": "moves in the opposite direction"}
    if mutation == "wrong-rotation":
        elements[0] = replace(first, rotation=_wrap_angle(first.rotation + 45))
        return Scene(tuple(elements), scene.background), {"kind": mutation, "description": "uses an incorrect rotation"}
    if mutation == "wrong-element-count":
        if len(elements) > 1:
            elements = elements[:-1]
        else:
            elements.append(replace(first, id="extra-distractor", x=_clamp(first.x + 0.2), y=_clamp(first.y + 0.12)))
        return Scene(tuple(elements), scene.background), {"kind": mutation, "description": "has the wrong number of elements"}
    if mutation == "wrong-marker-movement":
        elements[0] = replace(first, marker=first.marker or "dot", marker_position=(first.marker_position + 0.37) % 1)
        return Scene(tuple(elements), scene.background), {"kind": mutation, "description": "moves the marker to the wrong position"}
    if mutation == "wrong-shading":
        elements[0] = replace(first, shaded=not first.shaded)
        return Scene(tuple(elements), scene.background), {"kind": mutation, "description": "gets the fill or shading wrong"}
    elements[0] = replace(first, shape="diamond" if first.shape != "diamond" else "triangle")
    return Scene(tuple(elements), scene.background), {"kind": "wrong-shape", "description": "changes the shape incorrectly"}


def make_distractors(
    correct: Scene,
    reference: Scene | None = None,
    rules: Sequence[Rule] = (),
    seed: int = 0,
    count: int = 3,
) -> list[dict[str, Any]]:
    """Build unique, labeled plausible wrong figures.

    The mutation record is intentionally returned with each figure so review
    mode can explain why an option is wrong without reverse-engineering SVG.
    """

    reference = reference or correct
    rng = random.Random(seed)
    mutation_kinds = [
        "partial-rule",
        "wrong-direction",
        "wrong-rotation",
        "wrong-element-count",
        "wrong-marker-movement",
        "wrong-shading",
        "wrong-shape",
    ]
    rng.shuffle(mutation_kinds)
    results: list[dict[str, Any]] = []
    seen = {render_svg(correct)}
    for mutation in mutation_kinds:
        candidate, mutation_record = _mutated(correct, mutation, reference, rules)
        rendered = render_svg(candidate)
        if rendered in seen:
            continue
        seen.add(rendered)
        results.append({"scene": candidate, "mutation": mutation_record})
        if len(results) >= count:
            break
    # A scene containing a circle can make a rotation visually equivalent.  A
    # final deterministic fallback still guarantees answer uniqueness.
    fallback_index = 0
    while len(results) < count:
        candidate = replace(correct, elements=correct.elements + (Element(f"fallback-{fallback_index}", shape="line", line_count=fallback_index + 2),))
        fallback_index += 1
        rendered = render_svg(candidate)
        if rendered not in seen:
            seen.add(rendered)
            results.append({"scene": candidate, "mutation": {"kind": "fallback", "description": "uses an additional line element"}})
    return results


def _option_records(correct: Scene, reference: Scene, rules: Sequence[Rule], seed: int) -> tuple[list[dict[str, Any]], str, list[dict[str, Any]]]:
    distractors = make_distractors(correct, reference, rules, seed=seed, count=3)
    candidates = [{"scene": correct, "mutation": {"kind": "correct", "description": "matches every rule"}}] + distractors
    random.Random(seed + 7919).shuffle(candidates)
    options: list[dict[str, Any]] = []
    correct_option = ""
    for index, candidate in enumerate(candidates):
        option_id = chr(65 + index)
        if candidate["scene"].signature() == correct.signature():
            correct_option = option_id
        options.append(
            {
                "id": option_id,
                "figure": candidate["scene"].to_dict(),
                "svg": render_svg(candidate["scene"]),
                "mutation": candidate["mutation"],
            }
        )
    return options, correct_option, [item["mutation"] for item in distractors]


def _base_question(
    question_id: str,
    format_name: str,
    difficulty: str,
    seed: int,
    stimulus: dict[str, Any],
    question: str,
    options: list[dict[str, Any]],
    correct_option: str,
    explanation: str,
    rules: Sequence[Rule],
    figures: Sequence[dict[str, Any]],
    distractors: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    rule_data = [rule.to_dict() for rule in rules]
    return {
        "id": question_id,
        "exam": "abstract",
        "format": format_name,
        "difficulty": difficulty,
        "stimulus": stimulus,
        "question": question,
        "options": options,
        "correctOption": correct_option,
        "explanation": explanation,
        "metadata": {
            "seed": seed,
            "rules": rule_data,
            "generatedFigures": list(figures),
            "distractors": list(distractors),
            "answerFigure": next(option["figure"] for option in options if option["id"] == correct_option),
            "answerSignature": Scene.from_dict(next(option["figure"] for option in options if option["id"] == correct_option)).signature(),
        },
    }


def generate_sequence(
    seed: int = 0,
    difficulty: str | int = "medium",
    rules: Sequence[Rule] | None = None,
) -> dict[str, Any]:
    """Generate a visual sequence-completion question."""

    level = _difficulty_name(difficulty)
    selected_rules = _rules_for_sequence(rules, level)
    base = _base_scene(seed, level)
    frame_count = {"easy": 3, "medium": 4, "hard": 5}[level]
    frames = [apply_rules(base, selected_rules, frame_index=index) for index in range(frame_count)]
    correct = apply_rules(base, selected_rules, frame_index=frame_count)
    figures = [_figure(scene, f"frame-{index + 1}") for index, scene in enumerate(frames)]
    stimulus = {"type": "sequence", "frames": figures, "missing": "next"}
    options, correct_option, distractors = _option_records(correct, frames[-1], selected_rules, seed + 101)
    explanation = (
        f"The rule is {_rule_sentence(selected_rules)}. Each frame changes from the previous frame by that rule; "
        f"the missing next frame must continue the same change. Option {correct_option} is correct because it "
        f"continues {_rule_sentence(selected_rules)} while preserving the other elements. The wrong options "
        "apply only part of the rule, use a wrong direction or rotation, or change the element count."
    )
    question_id = f"abstract-sequence-{seed}-{level}"
    return _base_question(
        question_id,
        "sequence",
        level,
        seed,
        stimulus,
        "Which visual figure completes the sequence?",
        options,
        correct_option,
        explanation,
        selected_rules,
        figures + [_figure(correct, "answer")],
        distractors,
    )


def _matrix_scene(base: Scene, row_rule: Rule, column_rule: Rule, row: int, column: int) -> Scene:
    return apply_rule(apply_rule(base, row_rule, row), column_rule, column)


def generate_matrix(
    size: int = 2,
    seed: int = 0,
    difficulty: str | int = "medium",
    rules: Sequence[Rule] | None = None,
) -> dict[str, Any]:
    """Generate a 2x2 or 3x3 matrix-completion question."""

    if size not in (2, 3):
        raise ValueError("matrix size must be 2 or 3")
    level = _difficulty_name(difficulty)
    default_row, default_column = _default_matrix_rules(level, size)
    if rules is None:
        row_rule, column_rule = default_row, default_column
        selected_rules = [row_rule, column_rule]
    else:
        if not rules:
            raise ValueError("matrix rules cannot be empty")
        normalized_rules = _normalize_rules(rules)
        if len(normalized_rules) > 2:
            raise ValueError("matrix rules must contain at most two rules")
        row_rule = normalized_rules[0]
        column_rule = normalized_rules[1] if len(normalized_rules) > 1 else normalized_rules[0]
        selected_rules = normalized_rules
    base = _base_scene(seed + 17, level)
    grid: list[list[dict[str, Any] | None]] = []
    figures: list[dict[str, Any]] = []
    for row in range(size):
        grid_row: list[dict[str, Any] | None] = []
        for column in range(size):
            scene = _matrix_scene(base, row_rule, column_rule, row, column)
            if row == size - 1 and column == size - 1:
                grid_row.append(None)
            else:
                figure = _figure(scene, f"cell-{row + 1}-{column + 1}")
                grid_row.append(figure)
                figures.append(figure)
        grid.append(grid_row)
    correct = _matrix_scene(base, row_rule, column_rule, size - 1, size - 1)
    reference_scene = Scene.from_dict(figures[-1]["scene"]) if figures else base
    options, correct_option, distractors = _option_records(correct, reference_scene, selected_rules, seed + 211)
    format_name = f"matrix-{size}x{size}"
    rule_text = f"Rows {_rule_label(row_rule)}; columns {_rule_label(column_rule)}."
    explanation = (
        f"{rule_text} Reading across each row and down each column gives the same local/global pattern. "
        f"The missing bottom-right figure must therefore apply both changes. Option {correct_option} is correct "
        f"because it {_rule_sentence([row_rule, column_rule])}. Other options omit one change or use a plausible "
        "wrong direction, rotation, fill, or element count."
    )
    return _base_question(
        f"abstract-matrix-{size}x{size}-{seed}-{level}",
        format_name,
        level,
        seed,
        {"type": "matrix", "rows": size, "columns": size, "grid": grid, "missing": {"row": size, "column": size}},
        "Which figure completes the matrix?",
        options,
        correct_option,
        explanation,
        selected_rules,
        figures + [_figure(correct, "answer")],
        distractors,
    )


def generate_analogy(
    seed: int = 0,
    difficulty: str | int = "medium",
    rules: Sequence[Rule] | None = None,
) -> dict[str, Any]:
    """Generate a visual A:B :: C:? transformation question."""

    level = _difficulty_name(difficulty)
    selected_rules = _rules_for_sequence(rules, level)
    source = _base_scene(seed + 29, level)
    transformed = apply_rules(source, selected_rules, 1)
    target = _base_scene(seed + 47, level)
    correct = apply_rules(target, selected_rules, 1)
    source_figure = _figure(source, "A")
    transformed_figure = _figure(transformed, "B")
    target_figure = _figure(target, "C")
    stimulus = {
        "type": "analogy",
        "left": {"A": source_figure, "B": transformed_figure},
        "right": {"C": target_figure, "missing": "answer"},
        "notation": "A : B :: C : ?",
    }
    options, correct_option, distractors = _option_records(correct, target, selected_rules, seed + 307)
    explanation = (
        f"A changes to B by {_rule_sentence(selected_rules)}. Apply the same transformation to C: "
        f"{_rule_sentence(selected_rules)}. Option {correct_option} is correct because it matches that "
        "transformation without changing unrelated parts. The distractors use partial rules, wrong directions, "
        "or incorrect rotations/counts."
    )
    figures = [source_figure, transformed_figure, target_figure, _figure(correct, "answer")]
    return _base_question(
        f"abstract-analogy-{seed}-{level}",
        "analogy",
        level,
        seed,
        stimulus,
        "Which figure completes the visual analogy A : B :: C : ?",
        options,
        correct_option,
        explanation,
        selected_rules,
        figures,
        distractors,
    )


def generate_question(
    format: str = "sequence",
    seed: int = 0,
    difficulty: str | int = "medium",
    rules: Sequence[Rule] | None = None,
) -> dict[str, Any]:
    """Dispatch to a stable public generator by visual question format."""

    normalized = format.lower().replace("_", "-")
    if normalized in ("sequence", "visual-sequence"):
        return generate_sequence(seed, difficulty, rules)
    if normalized in ("matrix", "matrix-2x2", "2x2"):
        return generate_matrix(2, seed, difficulty, rules)
    if normalized in ("matrix-3x3", "3x3"):
        return generate_matrix(3, seed, difficulty, rules)
    if normalized in ("analogy", "transformation", "transformation-analogy"):
        return generate_analogy(seed, difficulty, rules)
    raise ValueError(f"Unsupported visual abstract format: {format}")


__all__ = [
    "Element",
    "Rule",
    "Scene",
    "alternation",
    "apply_rule",
    "apply_rules",
    "color_change",
    "deserialize_rule",
    "deserialize_scene",
    "element_count",
    "fill",
    "generate_analogy",
    "generate_matrix",
    "generate_question",
    "generate_sequence",
    "line_count",
    "make_distractors",
    "make_rule",
    "nesting",
    "reflection",
    "render_svg",
    "rotation",
    "serialize_rule",
    "serialize_scene",
    "shape_change",
    "symmetry",
    "translation",
]
