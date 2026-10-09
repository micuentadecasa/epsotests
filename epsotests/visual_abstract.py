"""Deterministic visual abstract reasoning question generation.

The generator deliberately keeps the scene model, rules, rendered SVG, answer
mutations, and explanation together.  A question is therefore portable JSON:
it can be reviewed, regenerated from its seed, or rendered without a browser or
an image library.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, replace
import html
import json
import math
import random
from typing import Any, Callable, Iterable, Mapping, Sequence

from .signatures import stable_signature


# EPSO-style figures use restrained grayscale rather than decorative colours.
PALETTE = ("#111827", "#374151", "#6b7280", "#9ca3af", "#d1d5db", "#000000")
SHAPES = ("circle", "square", "triangle", "diamond", "star")

# Stable rule vocabulary.  Alias kinds remain serializable so callers can
# describe movement/position, colour, shading, and containment using the
# terminology used by their item bank.
SUPPORTED_RULE_KINDS = (
    "rotation",
    "reflection",
    "translation",
    "movement",
    "alternation",
    "element-count",
    "shape-addition",
    "shape-removal",
    "shape-change",
    "fill",
    "shading",
    "color-change",
    "colour-change",
    "position",
    "orientation",
    "symmetry",
    "nesting",
    "containment",
    "line-count",
    "composite",
)

# Canonical values shared by the Python API, CLI, examples, and tests.  The
# dispatcher still accepts documented aliases (for example ``matrix``), but
# these are the stable values that appear in generated question JSON.
SUPPORTED_FORMATS = ("sequence", "matrix-2x2", "matrix-3x3", "analogy")
SUPPORTED_DIFFICULTIES = ("easy", "medium", "hard")
SUPPORTED_EXAM_PROFILES = ("standard", "five-option")
# Explicit rule profiles keep repeated seeds from changing only the source
# drawing.  The profile is selected deterministically from the seed and is
# recorded in metadata so catalog consumers can audit method variation.
VISUAL_RULE_VARIATION_PROFILES = (
    "rotation-movement",
    "reflection-fill",
    "count-symmetry",
    "nesting-shape",
)
# Generated rule magnitudes are intentionally quantized and large enough to
# recover at normal exam scale.  The policy is shared by default item rules
# and the audit tests; callers may still construct custom Rule values.
MIN_HUMAN_OBSERVABLE_TRANSLATION = 0.04
QUANTIZED_ROTATION_DEGREES = (45, 90, 180, 270)
DIFFICULTY_ELEMENT_COUNTS = {"easy": 2, "medium": 3, "hard": 4}
EXPLAIN_LOGIC_ACTION_ID = "explain-logic"
HIDE_SOLUTION_ACTION_ID = "hide-solution"


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
    fill: str = PALETTE[0]
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
            fill=str(data.get("fill", PALETTE[0])),
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
            elements=tuple(
                Element.from_dict(item) for item in data.get("elements", [])
            ),
            background=str(data.get("background", "#ffffff")),
        )

    def signature(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class ExamProfile:
    """Exam presentation settings that affect answer-option cardinality."""

    name: str
    option_count: int

    def __post_init__(self) -> None:
        name = str(self.name).strip().lower()
        count = int(self.option_count)
        if not name:
            raise ValueError("exam profile name cannot be empty")
        if count < 2 or count > 26:
            raise ValueError("exam profile option_count must be between 2 and 26")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "option_count", count)

    @property
    def option_ids(self) -> tuple[str, ...]:
        return tuple(chr(65 + index) for index in range(self.option_count))


EXAM_PROFILES = {
    "standard": ExamProfile("standard", 4),
    "five-option": ExamProfile("five-option", 5),
}
_PROFILE_ALIASES = {
    "default": "standard",
    "four-option": "standard",
    "pdf": "standard",
    "computer": "standard",
    "five": "five-option",
    "png": "five-option",
}


def resolve_exam_profile(
    profile: str | ExamProfile | None = None,
) -> ExamProfile:
    """Resolve a named or custom exam profile for question presentation."""

    if profile is None:
        return EXAM_PROFILES["standard"]
    if isinstance(profile, ExamProfile):
        return profile
    key = str(profile).strip().lower()
    key = _PROFILE_ALIASES.get(key, key)
    try:
        return EXAM_PROFILES[key]
    except KeyError as error:
        available = ", ".join(SUPPORTED_EXAM_PROFILES)
        raise ValueError(f"Unsupported exam profile {profile!r}; use {available}") from error


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
        return cls(
            str(data["kind"]), dict(data.get("parameters", data.get("params", {})))
        )


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


def movement(dx: float = 0.1, dy: float = 0.0) -> Rule:
    return Rule("movement", {"dx": dx, "dy": dy})


def position(dx: float = 0.1, dy: float = 0.0) -> Rule:
    return Rule("position", {"dx": dx, "dy": dy})


def orientation(degrees: float = 90) -> Rule:
    return Rule("orientation", {"degrees": degrees})


def shading(shaded: bool | None = None) -> Rule:
    return Rule("shading", {} if shaded is None else {"shaded": shaded})


def colour_change(colors: Sequence[str] = PALETTE) -> Rule:
    return Rule("colour-change", {"colors": list(colors)})


def shape_addition(shape: str | None = None, count: int = 1) -> Rule:
    parameters: dict[str, Any] = {"delta": abs(int(count))}
    if shape is not None:
        parameters["shape"] = shape
    return Rule("shape-addition", parameters)


def shape_removal(count: int = 1) -> Rule:
    return Rule("shape-removal", {"delta": abs(int(count))})


def containment(action: str = "add") -> Rule:
    return Rule("containment", {"action": action})


def composite(rules: Sequence[Rule]) -> Rule:
    return Rule("composite", {"rules": list(rules)})


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
    return [
        index
        for index, element in enumerate(scene.elements)
        if element.id == str(target)
    ]


def _with_element(scene: Scene, index: int, element: Element) -> Scene:
    elements = list(scene.elements)
    elements[index] = element
    return replace(scene, elements=tuple(elements))


def _update_targets(
    scene: Scene,
    parameters: Mapping[str, Any],
    transform: Callable[[Element], Element],
    *,
    descendants_for_all: bool = False,
) -> Scene:
    """Apply a transform while retaining nested scene structure.

    A top-level rotation or translation moves a container as one unit; its
    children follow through the renderer.  Attribute rules opt into updating
    all descendants.  A string target can always address a nested element by
    id, which keeps the single Element/Scene model useful for authored items.
    """

    target = parameters.get("target", "all")

    def visit(element: Element, top_index: int, is_top_level: bool) -> Element:
        selected = (
            target in ("all", None)
            or (is_top_level and isinstance(target, int) and top_index == target)
            or element.id == str(target)
        )
        changed = transform(element) if selected else element
        visit_children = descendants_for_all or target not in ("all", None)
        if visit_children and changed.children:
            changed = replace(
                changed,
                children=tuple(
                    visit(child, top_index, False) for child in changed.children
                ),
            )
        return changed

    return replace(
        scene,
        elements=tuple(
            visit(element, index, True) for index, element in enumerate(scene.elements)
        ),
    )


def _apply_rotation(
    scene: Scene, degrees: float, frame_index: int, parameters: Mapping[str, Any]
) -> Scene:
    amount = degrees * frame_index
    return _update_targets(
        scene,
        parameters,
        lambda element: replace(
            element, rotation=_wrap_angle(element.rotation + amount)
        ),
    )


def _apply_translation(
    scene: Scene, dx: float, dy: float, frame_index: int, parameters: Mapping[str, Any]
) -> Scene:
    return _update_targets(
        scene,
        parameters,
        lambda element: replace(
            element,
            x=_clamp(element.x + dx * frame_index),
            y=_clamp(element.y + dy * frame_index),
        ),
    )


def _reflected_element(element: Element, axis: str) -> Element:
    children = tuple(_reflected_element(child, axis) for child in element.children)
    if axis in ("vertical", "y"):
        return replace(
            element,
            x=_clamp(1 - element.x),
            rotation=_wrap_angle(-element.rotation),
            marker_position=(1 - element.marker_position) % 1,
            children=children,
        )
    if axis in ("horizontal", "x"):
        return replace(
            element,
            y=_clamp(1 - element.y),
            rotation=_wrap_angle(180 - element.rotation),
            marker_position=(1 - element.marker_position) % 1,
            children=children,
        )
    return replace(
        element,
        x=_clamp(1 - element.x),
        y=_clamp(1 - element.y),
        rotation=_wrap_angle(element.rotation + 180),
        children=children,
    )


def _apply_reflection(
    scene: Scene, axis: str, parameters: Mapping[str, Any], frame_index: int
) -> Scene:
    if frame_index == 0 or frame_index % 2 == 0:
        return scene
    axis = axis.lower()
    return _update_targets(
        scene,
        parameters,
        lambda element: _reflected_element(element, axis),
    )


def _apply_alternation(
    scene: Scene, parameters: Mapping[str, Any], frame_index: int
) -> Scene:
    if frame_index == 0:
        return scene
    property_name = str(parameters.get("property", "shaded")).lower().replace(
        "-", "_"
    )
    values = parameters.get("values")

    def transform(element: Element) -> Element:
        if values:
            value = values[frame_index % len(values)]
        elif property_name in ("shaded", "shading", "fill"):
            value = element.shaded if frame_index % 2 == 0 else not element.shaded
        elif property_name == "shape":
            value = SHAPES[frame_index % len(SHAPES)]
        elif property_name in ("rotation", "orientation"):
            value = element.rotation + 90 * frame_index
        elif property_name == "marker":
            value = None if frame_index % 2 == 0 else (element.marker or "dot")
        else:
            return element
        if property_name in ("shaded", "shading"):
            return replace(element, shaded=bool(value))
        if property_name == "fill":
            fill_value = (
                value if isinstance(value, str) else PALETTE[frame_index % len(PALETTE)]
            )
            return replace(element, fill=fill_value, shaded=True)
        if property_name == "shape":
            return replace(element, shape=str(value))
        if property_name in ("rotation", "orientation"):
            return replace(element, rotation=_wrap_angle(_as_number(value)))
        if property_name == "marker":
            return replace(element, marker=None if value is None else str(value))
        return element

    return _update_targets(scene, parameters, transform, descendants_for_all=True)


def _apply_count(
    scene: Scene, delta: int, frame_index: int, parameters: Mapping[str, Any]
) -> Scene:
    desired_delta = int(delta) * frame_index
    if desired_delta > 0:
        elements = list(scene.elements)
        template = elements[-1] if elements else Element("element-0")
        requested_shape = parameters.get("shape")
        requested_shapes = parameters.get("shapes")
        for offset in range(desired_delta):
            new_id = f"added-{frame_index}-{offset + 1}"
            if requested_shapes:
                shape = str(requested_shapes[offset % len(requested_shapes)])
            else:
                shape = str(requested_shape or template.shape)
            elements.append(
                replace(
                    template,
                    id=new_id,
                    shape=shape,
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


def _apply_shape_change(
    scene: Scene, parameters: Mapping[str, Any], frame_index: int
) -> Scene:
    if frame_index == 0:
        return scene
    shapes = tuple(str(shape) for shape in parameters.get("shapes", SHAPES)) or SHAPES
    return _update_targets(
        scene,
        parameters,
        lambda element: replace(element, shape=shapes[frame_index % len(shapes)]),
        descendants_for_all=True,
    )


def _apply_fill(scene: Scene, parameters: Mapping[str, Any], frame_index: int) -> Scene:
    if frame_index == 0:
        return scene

    def transform(element: Element) -> Element:
        if "shaded" in parameters:
            shaded = bool(parameters["shaded"])
        else:
            shaded = element.shaded if frame_index % 2 == 0 else not element.shaded
        return replace(element, shaded=shaded)

    return _update_targets(scene, parameters, transform, descendants_for_all=True)


def _apply_color(
    scene: Scene, parameters: Mapping[str, Any], frame_index: int
) -> Scene:
    if frame_index == 0:
        return scene
    colors = tuple(str(color) for color in parameters.get("colors", PALETTE)) or PALETTE
    return _update_targets(
        scene,
        parameters,
        lambda element: replace(
            element, fill=colors[frame_index % len(colors)], shaded=True
        ),
        descendants_for_all=True,
    )


def _apply_symmetry(
    scene: Scene, parameters: Mapping[str, Any], frame_index: int
) -> Scene:
    if frame_index == 0:
        return scene
    base_order = max(1, int(parameters.get("order", parameters.get("count", 2))))
    # Increase the visible symmetry order each frame; setting a constant order
    # would make matrix columns 1 and 2 identical while metadata claimed a rule.
    order = base_order + max(0, frame_index - 1)
    return _update_targets(
        scene,
        parameters,
        lambda element: replace(element, symmetry=order),
    )


def _apply_nesting(
    scene: Scene, parameters: Mapping[str, Any], frame_index: int
) -> Scene:
    if frame_index == 0:
        return scene
    action = str(parameters.get("action", "add")).lower()

    def transform(element: Element) -> Element:
        if action in ("remove", "delete"):
            return replace(element, children=())
        inner_shape = str(
            parameters.get(
                "shape", "circle" if element.shape != "circle" else "diamond"
            )
        )
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
        return replace(element, children=(child,))

    return _update_targets(scene, parameters, transform)


def _apply_line_count(
    scene: Scene, parameters: Mapping[str, Any], frame_index: int
) -> Scene:
    delta = int(parameters.get("delta", 1))
    return _update_targets(
        scene,
        parameters,
        lambda element: replace(
            element, line_count=max(1, element.line_count + delta * frame_index)
        ),
        descendants_for_all=True,
    )


def _apply_marker(
    scene: Scene, parameters: Mapping[str, Any], frame_index: int
) -> Scene:
    if frame_index == 0:
        return scene
    movement = _as_number(parameters.get("delta", parameters.get("movement", 0.2)), 0.2)
    return _update_targets(
        scene,
        parameters,
        lambda element: replace(
            element,
            marker=str(parameters.get("marker", element.marker or "dot")),
            marker_position=(element.marker_position + movement * frame_index) % 1,
        ),
        descendants_for_all=True,
    )


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
            result = apply_rule(
                result,
                nested_rule
                if isinstance(nested_rule, Rule)
                else Rule.from_dict(nested_rule),
                frame_index,
            )
        return result
    if kind in ("rotation", "orientation"):
        return _apply_rotation(
            scene,
            _as_number(parameters.get("degrees", parameters.get("angle", 90)), 90),
            frame_index,
            parameters,
        )
    if kind in ("translation", "movement", "position"):
        if (
            kind == "position"
            and ("x" in parameters or "y" in parameters)
            and "dx" not in parameters
            and "dy" not in parameters
        ):
            if frame_index == 0:
                return scene
            return _update_targets(
                scene,
                parameters,
                lambda element: replace(
                    element,
                    x=_clamp(_as_number(parameters.get("x"), element.x)),
                    y=_clamp(_as_number(parameters.get("y"), element.y)),
                ),
            )
        return _apply_translation(
            scene,
            _as_number(parameters.get("dx", parameters.get("x", 0.1)), 0.1),
            _as_number(parameters.get("dy", parameters.get("y", 0)), 0),
            frame_index,
            parameters,
        )
    if kind in ("reflection", "reflect"):
        return _apply_reflection(
            scene, str(parameters.get("axis", "vertical")), parameters, frame_index
        )
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


def _points_for_shape(
    shape: str, cx: float, cy: float, radius: float, rotation_degrees: float
) -> str:
    sides = {"triangle": 3, "diamond": 4, "square": 4, "star": 10}.get(shape, 0)
    if not sides:
        return ""
    start = math.radians(rotation_degrees - 90)
    points: list[str] = []
    if shape == "star":
        for index in range(10):
            radius_for_point = radius if index % 2 == 0 else radius * 0.45
            angle = start + index * math.pi / 5
            points.append(
                f"{cx + radius_for_point * math.cos(angle):.3f},{cy + radius_for_point * math.sin(angle):.3f}"
            )
    elif shape == "diamond":
        for index in range(4):
            angle = start + index * math.pi / 2
            points.append(
                f"{cx + radius * math.cos(angle):.3f},{cy + radius * math.sin(angle):.3f}"
            )
    else:
        for index in range(sides):
            angle = start + index * 2 * math.pi / sides
            points.append(
                f"{cx + radius * math.cos(angle):.3f},{cy + radius * math.sin(angle):.3f}"
            )
    return " ".join(points)


def _element_svg(
    element: Element,
    width: int,
    height: int,
    parent: tuple[float, float, float, float] | None = None,
    id_suffix: str = "",
) -> str:
    if parent is None:
        cx, cy, size = (
            element.x * width,
            element.y * height,
            element.size * min(width, height),
        )
        render_rotation = element.rotation
    else:
        parent_x, parent_y, parent_size, parent_rotation = parent
        relative_x = (element.x - 0.5) * parent_size
        relative_y = (element.y - 0.5) * parent_size
        parent_angle = math.radians(parent_rotation)
        cx = (
            parent_x
            + relative_x * math.cos(parent_angle)
            - relative_y * math.sin(parent_angle)
        )
        cy = (
            parent_y
            + relative_x * math.sin(parent_angle)
            + relative_y * math.cos(parent_angle)
        )
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
        pieces.append(
            f'<circle data-element-id="{element_id}" cx="{cx:.3f}" cy="{cy:.3f}" r="{radius:.3f}" {common}/>'
        )
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
        pieces.append(
            f'<polygon data-element-id="{element_id}" points="{points}" {common}/>'
        )
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
        marker_angle = (
            2 * math.pi * element.marker_position
            - math.pi / 2
            + math.radians(render_rotation)
        )
        marker_x = cx + radius * 0.68 * math.cos(marker_angle)
        marker_y = cy + radius * 0.68 * math.sin(marker_angle)
        marker_name = html.escape(element.marker, quote=True)
        if element.marker == "cross":
            pieces.append(
                f'<path data-marker="{marker_name}" d="M {marker_x - 4:.3f} {marker_y:.3f} L {marker_x + 4:.3f} {marker_y:.3f} '
                f'M {marker_x:.3f} {marker_y - 4:.3f} L {marker_x:.3f} {marker_y + 4:.3f}" stroke="{stroke_value}" stroke-width="2"/>'
            )
        else:
            pieces.append(
                f'<circle data-marker="{marker_name}" cx="{marker_x:.3f}" cy="{marker_y:.3f}" r="3" fill="{stroke_value}"/>'
            )
    for child in element.children:
        pieces.append(
            _element_svg(
                child,
                width,
                height,
                (cx, cy, size, render_rotation),
                id_suffix + "-nested",
            )
        )
    if element.symmetry > 1:
        # Symmetry is a scene-visible property, not only metadata.  Mirror
        # copies retain nested children and stable IDs at every containment
        # depth, so applying symmetry to a child cannot become a no-op.
        for copy_index in range(1, element.symmetry):
            angle = 2 * math.pi * copy_index / element.symmetry
            copy_x = _clamp(element.x + math.cos(angle) * element.size * 0.65)
            copy_y = _clamp(element.y + math.sin(angle) * element.size * 0.65)
            copy = replace(element, x=copy_x, y=copy_y, symmetry=1)
            pieces.append(
                _element_svg(
                    copy,
                    width,
                    height,
                    parent,
                    f"-symmetry-{copy_index}",
                )
            )
    return "".join(pieces)


def render_svg(scene: Scene, width: int = 160, height: int = 160) -> str:
    """Render a scene to stable, dependency-free SVG.

    Rendering the canonical serialized values prevents a figure loaded from
    JSON from differing by a final floating-point digit from its source.
    """

    scene = Scene.from_dict(scene.to_dict())
    background = html.escape(scene.background, quote=True)
    content = "".join(
        _element_svg(element, width, height) for element in scene.elements
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{int(width)}" height="{int(height)}" '
        f'viewBox="0 0 {int(width)} {int(height)}" role="img" aria-label="visual reasoning figure">'
        f'<rect width="100%" height="100%" fill="{background}"/>{content}</svg>'
    )


def _base_scene(seed: int, difficulty: str | int = "medium") -> Scene:
    rng = random.Random(seed)
    level = _difficulty_name(difficulty)
    count = DIFFICULTY_ELEMENT_COUNTS[level]
    elements: list[Element] = []
    for index in range(count):
        elements.append(
            Element(
                id=f"element-{index + 1}",
                shape=rng.choice(SHAPES),
                x=0.2 + index * 0.2 + rng.random() * 0.06,
                y=0.3 + (index % 2) * 0.35 + rng.random() * 0.08,
                size=0.18 + rng.random() * 0.08,
                rotation=float(rng.choice((0, 0, 45, 90))),
                fill=rng.choice(PALETTE),
                shaded=True,
                line_count=1,
                marker=("dot" if index == 0 else "cross" if index == 1 else None),
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


def _variation_index(seed: int) -> int:
    return abs(int(seed)) % len(VISUAL_RULE_VARIATION_PROFILES)


def _default_sequence_rules(level: str, variation_index: int = 0) -> list[Rule]:
    """Return a visible, named transformation profile for a sequence."""

    profiles = (
        [composite((rotation(90), movement(0.08, 0.04)))],
        [composite((reflection("vertical"), fill()))],
        [composite((element_count(1), symmetry(2)))],
        [composite((nesting("add"), shape_change(("circle", "square", "triangle", "diamond"))))],
    )
    selected = list(profiles[variation_index % len(profiles)])
    if level == "hard" and variation_index % 2 == 1:
        selected.append(color_change(("#111827", "#6b7280", "#d1d5db")))
    return selected


def _default_matrix_rules(
    level: str, size: int, variation_index: int = 0
) -> tuple[Rule, Rule]:
    """Return two distinct directional transformations for a matrix."""

    profiles = (
        (rotation(90), fill()),
        (reflection("vertical"), movement(0.08, 0.04)),
        (element_count(1), symmetry(2)),
        (nesting("add"), shape_change(("circle", "square", "triangle", "diamond"))),
    )
    row_rule, column_rule = profiles[variation_index % len(profiles)]
    if level == "hard" and variation_index % 2 == 1:
        column_rule = composite((column_rule, color_change(("#111827", "#6b7280", "#d1d5db"))))
    return row_rule, column_rule


def _normalize_rules(rules: Sequence[Rule]) -> list[Rule]:
    return [rule if isinstance(rule, Rule) else Rule.from_dict(rule) for rule in rules]  # type: ignore[arg-type]


def _rules_for_sequence(
    rules: Sequence[Rule] | None, level: str, variation_index: int = 0
) -> list[Rule]:
    return (
        _normalize_rules(rules)
        if rules is not None
        else _default_sequence_rules(level, variation_index)
    )


def _figure(scene: Scene, figure_id: str) -> dict[str, Any]:
    return {"id": figure_id, "scene": scene.to_dict(), "svg": render_svg(scene)}


def _rule_label(rule: Rule) -> str:
    kind = rule.kind.lower().replace("_", "-")
    p = rule.parameters
    if kind in ("rotation", "orientation"):
        return f"rotate by {_as_number(p.get('degrees', p.get('angle', 90))):g}°"
    if kind in ("translation", "movement", "position"):
        if kind == "position" and ("x" in p or "y" in p) and "dx" not in p and "dy" not in p:
            return f"move to ({_as_number(p.get('x', 0.5)):g}, {_as_number(p.get('y', 0.5)):g})"
        return f"move by ({_as_number(p.get('dx', p.get('x', 0.1))):g}, {_as_number(p.get('dy', p.get('y', 0))):g})"
    if kind in ("reflection", "reflect"):
        return f"reflect across the {p.get('axis', 'vertical')} axis"
    if kind in ("alternation", "alternate"):
        return f"alternate {p.get('property', 'shading')}"
    if kind in ("element-count", "count", "shape-addition", "shape-removal"):
        delta = int(p.get("delta", 1))
        if kind == "shape-removal":
            delta = -abs(delta)
        return f"change the element count by {delta}"
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
        return " and ".join(
            _rule_label(Rule.from_dict(item) if not isinstance(item, Rule) else item)
            for item in p.get("rules", [])
        )
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


def _atomic_rules(rules: Sequence[Rule]) -> list[Rule]:
    """Flatten composites for partial-rule mutations without changing metadata."""

    atomic: list[Rule] = []
    for rule in rules:
        normalized = rule if isinstance(rule, Rule) else Rule.from_dict(rule)
        if normalized.kind.lower().replace("_", "-") in ("composite", "combined"):
            nested = normalized.parameters.get("rules", ())
            atomic.extend(_atomic_rules(_normalize_rules(nested)))
        else:
            atomic.append(normalized)
    return atomic


def _partial_rule_scene(
    correct: Scene, reference: Scene, rules: Sequence[Rule]
) -> Scene:
    """Return an intentionally incomplete but visually plausible transformation."""

    atomic = _atomic_rules(rules)
    if not atomic:
        return reference
    rule = atomic[0]
    kind = rule.kind.lower().replace("_", "-")
    parameters = dict(rule.parameters)
    if kind in ("rotation", "orientation"):
        degrees = _as_number(parameters.get("degrees", parameters.get("angle", 90)), 90)
        parameters["degrees"] = degrees / 2
        partial = apply_rule(reference, Rule("rotation", parameters))
    elif kind in ("translation", "movement", "position"):
        parameters["dx"] = _as_number(parameters.get("dx", parameters.get("x", 0.1)), 0.1) / 2
        parameters["dy"] = _as_number(parameters.get("dy", parameters.get("y", 0)), 0) / 2
        partial = apply_rule(reference, Rule("translation", parameters))
    else:
        # For toggles, counts, reflection, nesting, and colour a source frame
        # is the natural partial answer: it has not completed that operation.
        partial = reference
    if render_svg(partial) == render_svg(correct):
        # A symmetric source can make a source-frame partial visually equal.
        # Flip the first visible primitive rather than returning a duplicate.
        if partial.elements:
            first = partial.elements[0]
            partial = _replace_first(
                partial,
                replace(first, shape="diamond" if first.shape != "diamond" else "triangle"),
            )
    return partial


def _replace_first(scene: Scene, element: Element) -> Scene:
    if not scene.elements:
        return scene
    return replace(scene, elements=(element,) + scene.elements[1:])


def _mutated(
    scene: Scene, mutation: str, reference: Scene, rules: Sequence[Rule]
) -> tuple[Scene, dict[str, Any]]:
    elements = list(scene.elements)
    if not elements:
        return Scene((Element("distractor"),)), {
            "kind": mutation,
            "description": mutation,
        }
    first = elements[0]
    if mutation == "partial-rule":
        return _partial_rule_scene(scene, reference, rules), {
            "kind": mutation,
            "description": "applies only part of the transformation rule",
            "ruleKinds": [rule.kind for rule in _atomic_rules(rules)],
        }
    if mutation == "partial-figure":
        atomic = _atomic_rules(rules)
        partial = reference
        if atomic and partial.elements:
            targeted = dict(atomic[0].parameters)
            targeted["target"] = 0
            partial = apply_rule(
                partial,
                Rule(atomic[0].kind, targeted),
                frame_index=1,
            )
        return partial, {
            "kind": mutation,
            "description": "applies the rule to only part of the figure",
            "ruleKinds": [rule.kind for rule in atomic],
        }
    if mutation == "wrong-direction":
        expected_dx = first.x - (reference.elements[0].x if reference.elements else first.x)
        expected_dy = first.y - (reference.elements[0].y if reference.elements else first.y)
        if abs(expected_dx) < 1e-9 and abs(expected_dy) < 1e-9:
            expected_dx, expected_dy = (0.12 if first.x < 0.5 else -0.12), 0.0
        elements[0] = replace(
            first,
            x=_clamp(first.x - expected_dx if expected_dx else first.x),
            y=_clamp(first.y - expected_dy if expected_dy else first.y),
        )
        return Scene(tuple(elements), scene.background), {
            "kind": mutation,
            "description": "moves in the opposite direction",
            "expectedDelta": {"x": round(expected_dx, 6), "y": round(expected_dy, 6)},
        }
    if mutation == "wrong-rotation":
        elements[0] = replace(first, rotation=_wrap_angle(first.rotation + 45))
        return Scene(tuple(elements), scene.background), {
            "kind": mutation,
            "description": "uses an incorrect rotation",
            "rotationDelta": 45,
        }
    if mutation == "wrong-element-count":
        if len(elements) > 1:
            elements = elements[:-1]
        else:
            elements.append(
                replace(
                    first,
                    id="extra-distractor",
                    x=_clamp(first.x + 0.2),
                    y=_clamp(first.y + 0.12),
                )
            )
        return Scene(tuple(elements), scene.background), {
            "kind": mutation,
            "description": "has the wrong number of elements",
            "expectedCount": len(scene.elements),
            "actualCount": len(elements),
        }
    if mutation == "wrong-marker-movement":
        elements[0] = replace(
            first,
            marker=first.marker or "dot",
            marker_position=(first.marker_position + 0.37) % 1,
        )
        return Scene(tuple(elements), scene.background), {
            "kind": mutation,
            "description": "moves the marker to the wrong position",
            "markerDelta": 0.37,
        }
    if mutation == "wrong-shading":
        elements[0] = replace(first, shaded=not first.shaded)
        return Scene(tuple(elements), scene.background), {
            "kind": mutation,
            "description": "gets the fill or shading wrong",
        }
    elements[0] = replace(
        first, shape="diamond" if first.shape != "diamond" else "triangle"
    )
    return Scene(tuple(elements), scene.background), {
        "kind": "wrong-shape",
        "description": "changes the shape incorrectly",
    }


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

    reference = correct if reference is None else reference
    rules = _normalize_rules(rules)
    count = max(0, int(count))
    rng = random.Random(seed)
    mutation_kinds = [
        "partial-rule",
        "partial-figure",
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
            # A partially applied toggle can be indistinguishable for a
            # symmetric primitive.  Keep its mutation provenance, but use the
            # deterministic shape variant as the visible wrong answer.
            if mutation == "partial-rule":
                candidate, mutation_record = _mutated(
                    correct, "wrong-shape", reference, rules
                )
                mutation_record = {
                    **mutation_record,
                    "kind": "partial-rule",
                    "description": "applies only part of the transformation rule",
                }
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
        candidate = replace(
            correct,
            elements=correct.elements
            + (
                Element(
                    f"fallback-{fallback_index}",
                    shape="line",
                    line_count=fallback_index + 2,
                ),
            ),
        )
        fallback_index += 1
        rendered = render_svg(candidate)
        if rendered not in seen:
            seen.add(rendered)
            results.append(
                {
                    "scene": candidate,
                    "mutation": {
                        "kind": "fallback",
                        "description": "uses an additional line element",
                    },
                }
            )
    return results


def _option_records(
    correct: Scene,
    reference: Scene,
    rules: Sequence[Rule],
    seed: int,
    option_count: int,
) -> tuple[list[dict[str, Any]], str, list[dict[str, Any]]]:
    if option_count < 2 or option_count > 26:
        raise ValueError("option_count must be between 2 and 26")
    distractors = make_distractors(
        correct,
        reference,
        rules,
        seed=seed,
        count=option_count - 1,
    )
    candidates = [
        {
            "scene": correct,
            "mutation": {"kind": "correct", "description": "matches every rule"},
        }
    ] + distractors
    random.Random(seed + 7919).shuffle(candidates)
    options: list[dict[str, Any]] = []
    correct_option = ""
    correct_svg = render_svg(correct)
    for index, candidate in enumerate(candidates):
        option_id = chr(65 + index)
        candidate_svg = render_svg(candidate["scene"])
        if candidate_svg == correct_svg:
            correct_option = option_id
        options.append(
            {
                "id": option_id,
                "figure": candidate["scene"].to_dict(),
                "svg": candidate_svg,
                "mutation": candidate["mutation"],
            }
        )
    return options, correct_option, [item["mutation"] for item in distractors]


def _explain_logic_action(
    explanation: str,
    options: Sequence[dict[str, Any]],
    correct_option: str,
    rules: Sequence[Rule],
    exam_profile: ExamProfile,
) -> dict[str, Any]:
    """Build the reusable learner action used to reveal an item explanation.

    The result is intentionally nested under a hidden-by-default button action:
    a learner can see that help is available without seeing the answer until
    they request it.  Review clients can use the same payload to show the rule
    and the reason every distractor fails.
    """

    distractor_reviews = [
        {
            "option": option["id"],
            "reason": str(option["mutation"]["description"]),
            "mutation": option["mutation"],
        }
        for option in options
        if option["id"] != correct_option
    ]
    return {
        "id": EXPLAIN_LOGIC_ACTION_ID,
        "type": "button",
        "label": "Explain logic",
        "initiallyVisible": False,
        "revealsAnswer": True,
        "solutionView": {
            "initiallyVisible": False,
            "hideAction": {
                "id": HIDE_SOLUTION_ACTION_ID,
                "type": "button",
                "label": "Hide solution",
                "visibleAfterReveal": True,
            },
        },
        "result": {
            "rule": [rule.to_dict() for rule in rules],
            "ruleText": _rule_sentence(rules),
            "optionCount": exam_profile.option_count,
            "explanation": explanation,
            "correctOption": correct_option,
            "correctReason": (
                f"Option {correct_option} is correct because it follows "
                f"{_rule_sentence(rules)}."
            ),
            "distractors": distractor_reviews,
        },
    }


def explain_logic(question: Mapping[str, Any]) -> dict[str, Any]:
    """Return the explanation revealed by a question's Explain Logic action.

    Consumers should render the action's label first and call this function
    only after the learner activates that action.  A copy is returned so a
    review UI cannot mutate the question's stored contract.
    """

    try:
        action = question["actions"]["explainLogic"]
        if action["id"] != EXPLAIN_LOGIC_ACTION_ID:
            raise KeyError("unexpected action id")
        return deepcopy(action["result"])
    except (KeyError, TypeError) as error:
        raise ValueError("question has no Explain Logic action") from error


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
    exam_profile: ExamProfile,
) -> dict[str, Any]:
    rule_data = [rule.to_dict() for rule in rules]
    explanation_fragments = [
        f"Rule: {_rule_sentence(rules)}.",
        f"Answer: option {correct_option} continues that rule.",
        "Distractors: each wrong option records the visual mutation it makes.",
    ]
    answer_figure = next(
        option["figure"] for option in options if option["id"] == correct_option
    )
    rule_signature = stable_signature(rule_data)
    answer_signature = Scene.from_dict(answer_figure).signature()
    return {
        "id": question_id,
        "itemNumber": 1,
        "exam": "abstract",
        "examProfile": exam_profile.name,
        "optionCount": exam_profile.option_count,
        "format": format_name,
        "difficulty": difficulty,
        "stimulus": stimulus,
        "question": question,
        "options": options,
        "correctOption": correct_option,
        "explanation": explanation,
        "explanationFragments": explanation_fragments,
        "actions": {
            "explainLogic": _explain_logic_action(
                explanation,
                options,
                correct_option,
                rules,
                exam_profile,
            )
        },
        "metadata": {
            "seed": seed,
            "examProfile": exam_profile.name,
            "optionCount": exam_profile.option_count,
            "rules": rule_data,
            "ruleMetadata": rule_data,
            "ruleSignature": rule_signature,
            "methodSignature": stable_signature({"format": format_name, "rules": rule_data}),
            "generatedFigures": list(figures),
            "distractors": list(distractors),
            "explanationFragments": explanation_fragments,
            "explanationSignature": stable_signature(explanation),
            "answerFigure": answer_figure,
            "answerSignature": answer_signature,
            "answerValueSignature": stable_signature(answer_signature),
        },
    }


def generate_sequence(
    seed: int = 0,
    difficulty: str | int = "medium",
    rules: Sequence[Rule] | None = None,
    exam_profile: str | ExamProfile | None = None,
    variation: int | None = None,
) -> dict[str, Any]:
    """Generate a visual sequence-completion question."""

    level = _difficulty_name(difficulty)
    profile = resolve_exam_profile(exam_profile)
    selected_rules = _rules_for_sequence(
        rules, level, _variation_index(seed) if variation is None else int(variation)
    )
    base = _base_scene(seed, level)
    frame_count = {"easy": 3, "medium": 4, "hard": 5}[level]
    frames = [
        apply_rules(base, selected_rules, frame_index=index)
        for index in range(frame_count)
    ]
    correct = apply_rules(base, selected_rules, frame_index=frame_count)
    figures = [
        _figure(scene, f"frame-{index + 1}") for index, scene in enumerate(frames)
    ]
    stimulus = {"type": "sequence", "frames": figures, "missing": "next"}
    options, correct_option, distractors = _option_records(
        correct,
        frames[-1],
        selected_rules,
        seed + 101,
        profile.option_count,
    )
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
        profile,
    )


def _matrix_scene(
    base: Scene, row_rule: Rule, column_rule: Rule, row: int, column: int
) -> Scene:
    return apply_rule(apply_rule(base, row_rule, row), column_rule, column)


def generate_matrix(
    size: int = 2,
    seed: int = 0,
    difficulty: str | int = "medium",
    rules: Sequence[Rule] | None = None,
    exam_profile: str | ExamProfile | None = None,
    variation: int | None = None,
) -> dict[str, Any]:
    """Generate a 2x2 or 3x3 matrix-completion question."""

    if size not in (2, 3):
        raise ValueError("matrix size must be 2 or 3")
    level = _difficulty_name(difficulty)
    profile = resolve_exam_profile(exam_profile)
    variation_index = _variation_index(seed) if variation is None else int(variation)
    if variation is None:
        # Keep the fixed Pages seeds compact while distributing all visual
        # rule families across the two matrix sizes.
        variation_index = (abs(int(seed)) % 2) if size == 2 else 2 + (abs(int(seed)) % 2)
    default_row, default_column = _default_matrix_rules(level, size, variation_index)
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
        column_rule = (
            normalized_rules[1] if len(normalized_rules) > 1 else normalized_rules[0]
        )
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
    options, correct_option, distractors = _option_records(
        correct,
        reference_scene,
        selected_rules,
        seed + 211,
        profile.option_count,
    )
    format_name = f"matrix-{size}x{size}"
    rule_text = f"Rows {_rule_label(row_rule)}; columns {_rule_label(column_rule)}."
    explanation = (
        f"The rule is applied in two directions: {rule_text} Reading across each row and down each column "
        "gives the same local/global pattern. The missing bottom-right figure must therefore apply both changes. "
        f"Option {correct_option} is correct because it applies {_rule_sentence([row_rule, column_rule])}. "
        "Other options omit one change or use a plausible wrong direction, rotation, fill, or element count."
    )
    return _base_question(
        f"abstract-matrix-{size}x{size}-{seed}-{level}",
        format_name,
        level,
        seed,
        {
            "type": "matrix",
            "rows": size,
            "columns": size,
            "grid": grid,
            "missing": {"row": size, "column": size},
        },
        "Which figure completes the matrix?",
        options,
        correct_option,
        explanation,
        selected_rules,
        figures + [_figure(correct, "answer")],
        distractors,
        profile,
    )


def generate_analogy(
    seed: int = 0,
    difficulty: str | int = "medium",
    rules: Sequence[Rule] | None = None,
    exam_profile: str | ExamProfile | None = None,
    variation: int | None = None,
) -> dict[str, Any]:
    """Generate a visual A:B :: C:? transformation question."""

    level = _difficulty_name(difficulty)
    profile = resolve_exam_profile(exam_profile)
    selected_rules = _rules_for_sequence(
        rules,
        level,
        (_variation_index(seed) % 2) if variation is None else int(variation),
    )
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
    options, correct_option, distractors = _option_records(
        correct,
        target,
        selected_rules,
        seed + 307,
        profile.option_count,
    )
    explanation = (
        f"A changes to B by {_rule_sentence(selected_rules)}. Apply the same transformation to C: "
        f"{_rule_sentence(selected_rules)}. Option {correct_option} is correct because it matches that "
        "transformation without changing unrelated parts. The distractors use partial rules, wrong directions, "
        "or incorrect rotations/counts."
    )
    figures = [
        source_figure,
        transformed_figure,
        target_figure,
        _figure(correct, "answer"),
    ]
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
        profile,
    )


def generate_question(
    format: str = "sequence",
    seed: int = 0,
    difficulty: str | int = "medium",
    rules: Sequence[Rule] | None = None,
    exam_profile: str | ExamProfile | None = None,
    variation: int | None = None,
) -> dict[str, Any]:
    """Dispatch to a stable public generator by visual question format."""

    normalized = format.lower().replace("_", "-")
    if normalized in ("sequence", "visual-sequence"):
        return generate_sequence(seed, difficulty, rules, exam_profile, variation)
    if normalized in ("matrix", "matrix-2x2", "2x2"):
        return generate_matrix(2, seed, difficulty, rules, exam_profile, variation)
    if normalized in ("matrix-3x3", "3x3"):
        return generate_matrix(3, seed, difficulty, rules, exam_profile, variation)
    if normalized in ("analogy", "transformation", "transformation-analogy"):
        return generate_analogy(seed, difficulty, rules, exam_profile, variation)
    raise ValueError(f"Unsupported visual abstract format: {format}")


__all__ = [
    "Element",
    "EXAM_PROFILES",
    "EXPLAIN_LOGIC_ACTION_ID",
    "ExamProfile",
    "HIDE_SOLUTION_ACTION_ID",
    "Rule",
    "Scene",
    "SUPPORTED_DIFFICULTIES",
    "SUPPORTED_EXAM_PROFILES",
    "SUPPORTED_FORMATS",
    "SUPPORTED_RULE_KINDS",
    "VISUAL_RULE_VARIATION_PROFILES",
    "alternation",
    "apply_rule",
    "apply_rules",
    "color_change",
    "colour_change",
    "composite",
    "containment",
    "deserialize_rule",
    "deserialize_scene",
    "element_count",
    "explain_logic",
    "fill",
    "generate_analogy",
    "generate_matrix",
    "generate_question",
    "generate_sequence",
    "line_count",
    "make_distractors",
    "make_rule",
    "movement",
    "nesting",
    "orientation",
    "position",
    "reflection",
    "render_svg",
    "resolve_exam_profile",
    "rotation",
    "serialize_rule",
    "serialize_scene",
    "shape_addition",
    "shape_change",
    "shape_removal",
    "shading",
    "symmetry",
    "translation",
]
