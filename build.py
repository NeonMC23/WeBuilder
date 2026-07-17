#!/usr/bin/env python3
"""WeBuilder — generate a modular static website from build.json.

The implementation deliberately uses only Python's standard library for normal
builds.  ``watchdog`` is required only when ``--watch`` is enabled.
"""

from __future__ import annotations

import argparse
import copy
import html
import json
import re
import shutil
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Sequence
from urllib.parse import urlsplit, urlunsplit

VERSION = "1.3.0"
ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_LIBRARY_PATH = ROOT_DIR / "library.json"
MISSING = object()


class TemplateError(ValueError):
    """Raised when a Mustache template is malformed."""


class ConfigurationError(ValueError):
    """Raised when a JSON configuration cannot be loaded."""


# ---------------------------------------------------------------------------
# Small Mustache-compatible renderer
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(
    r"{{{\s*([^{}]+?)\s*}}}|{{\s*([#\^/!&]?)\s*([^{}]*?)\s*}}",
    flags=re.DOTALL,
)


@dataclass(frozen=True)
class _TextNode:
    value: str


@dataclass(frozen=True)
class _VariableNode:
    name: str
    escaped: bool = True


@dataclass(frozen=True)
class _SectionNode:
    name: str
    children: tuple[Any, ...]
    inverted: bool = False


class MustacheRenderer:
    """Render the Mustache subset used by component templates.

    Supported syntax:
      * ``{{name}}`` escaped variables and dotted paths;
      * ``{{{name}}}`` / ``{{& name}}`` unescaped variables;
      * ``{{#items}}...{{/items}}`` sections and list loops;
      * ``{{^items}}...{{/items}}`` inverted sections;
      * ``{{! comment}}`` comments.
    """

    def __init__(self) -> None:
        self._cache: dict[str, tuple[Any, ...]] = {}

    def parse(self, template: str) -> tuple[Any, ...]:
        if template in self._cache:
            return self._cache[template]

        position = 0

        def parse_nodes(stop_name: str | None = None) -> tuple[tuple[Any, ...], int]:
            nonlocal position
            nodes: list[Any] = []
            while True:
                match = _TOKEN_RE.search(template, position)
                if not match:
                    if stop_name is not None:
                        raise TemplateError(f"Unclosed Mustache section: {stop_name!r}")
                    if position < len(template):
                        nodes.append(_TextNode(template[position:]))
                    position = len(template)
                    return tuple(nodes), position

                if match.start() > position:
                    nodes.append(_TextNode(template[position : match.start()]))
                position = match.end()

                triple_name, sigil, regular_name = match.groups()
                if triple_name is not None:
                    nodes.append(_VariableNode(triple_name.strip(), escaped=False))
                    continue

                name = regular_name.strip()
                if sigil in ("#", "^"):
                    if not name:
                        raise TemplateError("A Mustache section must have a name")
                    children, _ = parse_nodes(name)
                    nodes.append(_SectionNode(name, children, inverted=sigil == "^"))
                elif sigil == "/":
                    if stop_name is None:
                        raise TemplateError(f"Unexpected Mustache closing tag: {name!r}")
                    if name != stop_name:
                        raise TemplateError(
                            f"Mustache section {stop_name!r} closed by {name!r}"
                        )
                    return tuple(nodes), position
                elif sigil == "!":
                    continue
                elif sigil == "&":
                    nodes.append(_VariableNode(name, escaped=False))
                else:
                    nodes.append(_VariableNode(name, escaped=True))

        nodes, _ = parse_nodes()
        self._cache[template] = nodes
        return nodes

    @staticmethod
    def _lookup(name: str, stack: Sequence[Any]) -> Any:
        name = name.strip()
        if name == ".":
            return stack[-1] if stack else MISSING

        parts = name.split(".") if name else []
        if not parts:
            return MISSING

        value: Any = MISSING
        for context in reversed(stack):
            if isinstance(context, dict) and parts[0] in context:
                value = context[parts[0]]
                break
        if value is MISSING:
            return MISSING

        for part in parts[1:]:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return MISSING
        return value

    def _render_nodes(self, nodes: Iterable[Any], stack: list[Any]) -> str:
        output: list[str] = []
        for node in nodes:
            if isinstance(node, _TextNode):
                output.append(node.value)
                continue

            if isinstance(node, _VariableNode):
                value = self._lookup(node.name, stack)
                if value is MISSING or value is None:
                    text = ""
                elif isinstance(value, bool):
                    text = "true" if value else "false"
                elif isinstance(value, (dict, list, tuple)):
                    text = json.dumps(value, ensure_ascii=False)
                else:
                    text = str(value)
                output.append(html.escape(text, quote=True) if node.escaped else text)
                continue

            value = self._lookup(node.name, stack)
            truthy = value is not MISSING and bool(value)
            if node.inverted:
                if not truthy:
                    output.append(self._render_nodes(node.children, stack))
                continue
            if not truthy:
                continue
            if isinstance(value, (list, tuple)):
                for item in value:
                    output.append(self._render_nodes(node.children, [*stack, item]))
            elif isinstance(value, dict):
                output.append(self._render_nodes(node.children, [*stack, value]))
            elif isinstance(value, bool):
                output.append(self._render_nodes(node.children, stack))
            else:
                # A scalar section changes the current context, making {{.}}
                # behave like standard Mustache implementations.
                output.append(self._render_nodes(node.children, [*stack, value]))
        return "".join(output)

    def render(self, template: str, context: dict[str, Any]) -> str:
        return self._render_nodes(self.parse(template), [context])


# ---------------------------------------------------------------------------
# Logging and models
# ---------------------------------------------------------------------------


class BuildLogger:
    """Collect structured entries and persist them to build/log.json."""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.entries: list[dict[str, Any]] = []

    def add(self, level: str, message: str, **context: Any) -> None:
        entry: dict[str, Any] = {
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "level": level,
            "message": message,
        }
        entry.update({key: value for key, value in context.items() if value is not None})
        self.entries.append(entry)

    def info(self, message: str, **context: Any) -> None:
        self.add("info", message, **context)

    def warning(self, message: str, **context: Any) -> None:
        self.add("warning", message, **context)

    def error(self, message: str, **context: Any) -> None:
        self.add("error", message, **context)

    @property
    def has_errors(self) -> bool:
        return any(entry["level"] == "error" for entry in self.entries)

    def write(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        target = self.output_dir / "log.json"
        target.write_text(
            json.dumps(self.entries, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


@dataclass
class ComponentUse:
    type_name: str
    variant_name: str
    component_definition: dict[str, Any]
    variant_definition: dict[str, Any]
    data: dict[str, Any]
    page_path: str
    tree_path: str
    instance_id: str
    explicit_id: str | None
    classes: list[str]
    events: dict[str, str]
    children: list["ComponentUse"] = field(default_factory=list)


@dataclass(frozen=True)
class AssetMapping:
    reference: str
    source: Path
    destination_relative: PurePosixPath


@dataclass(frozen=True)
class PluginInfo:
    """One namespaced library extension loaded for the current command."""

    name: str
    path: Path
    version: str
    component_count: int
    theme_count: int
    shortcut_count: int


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _get_path(data: Any, dotted_path: str) -> Any:
    value = data
    for part in dotted_path.split("."):
        if not isinstance(value, dict) or part not in value:
            return MISSING
        value = value[part]
    return value


def _normalise_classes(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part for part in value.split() if part]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            if isinstance(item, str):
                result.extend(part for part in item.split() if part)
        return list(dict.fromkeys(result))
    return []


def _safe_posix_path(value: str) -> PurePosixPath | None:
    normalised = value.replace("\\", "/")
    path = PurePosixPath(normalised)
    if path.is_absolute() or not path.parts or any(part in ("", ".", "..") for part in path.parts):
        return None
    return path


def _artifact_name(value: str) -> str:
    """Create collision-safe filenames, preserving plugin namespace boundaries."""
    if ":" in value:
        namespace, local_name = value.split(":", 1)
        safe_namespace = re.sub(r"[^A-Za-z0-9_-]+", "-", namespace).strip("-")
        safe_local = re.sub(r"[^A-Za-z0-9_-]+", "-", local_name).strip("-")
        return f"plugin-{safe_namespace}--{safe_local}"
    return re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-") or "component"


def _css_escape_identifier(value: str) -> str:
    chars: list[str] = []
    for index, character in enumerate(value):
        if character.isalnum() or character in ("-", "_"):
            if index == 0 and character.isdigit():
                chars.append(f"\\{ord(character):x} ")
            else:
                chars.append(character)
        else:
            chars.append(f"\\{ord(character):x} ")
    return "".join(chars)


# Responsive/state prefixes supported by the on-demand utility engine.  Unlike
# the finite shortcut dictionary, numeric and bracketed utilities are generated
# from the classes actually used by build.json.
_UTILITY_BREAKPOINTS = {
    "sm": "40rem",
    "md": "48rem",
    "lg": "64rem",
    "xl": "80rem",
    "2xl": "96rem",
}
_UTILITY_STATES = {
    "hover": ":hover",
    "focus": ":focus",
    "focus-visible": ":focus-visible",
    "active": ":active",
    "disabled": ":disabled",
    "checked": ":checked",
    "first": ":first-child",
    "last": ":last-child",
    "odd": ":nth-child(odd)",
    "even": ":nth-child(even)",
}


def _safe_arbitrary_css_value(raw_value: str) -> str | None:
    """Decode ``[arbitrary_value]`` while blocking CSS rule injection."""
    if not (raw_value.startswith("[") and raw_value.endswith("]")):
        return None
    value = raw_value[1:-1].replace("_", " ").strip()
    if not value or len(value) > 160 or any(char in value for char in ";{}<>"):
        return None
    lowered = value.lower().replace(" ", "")
    if "url(" in lowered or "expression(" in lowered or "@import" in lowered:
        return None
    if not re.fullmatch(r"[A-Za-z0-9#%.,()\s+\-*/_'\"]+", value):
        return None
    return value


def _utility_size(raw_value: str, *, allow_auto: bool = False) -> str | None:
    arbitrary = _safe_arbitrary_css_value(raw_value)
    if arbitrary is not None:
        return arbitrary
    keywords = {
        "px": "1px",
        "full": "100%",
        "screen": "100vw",
        "svw": "100svw",
        "svh": "100svh",
        "min": "min-content",
        "max": "max-content",
        "fit": "fit-content",
        "none": "none",
    }
    if allow_auto:
        keywords["auto"] = "auto"
    if raw_value in keywords:
        return keywords[raw_value]
    fraction = re.fullmatch(r"(\d+)/(\d+)", raw_value)
    if fraction and int(fraction.group(2)) != 0:
        return f"{int(fraction.group(1)) / int(fraction.group(2)) * 100:.8g}%"
    if re.fullmatch(r"\d+(?:\.\d+)?", raw_value):
        number = float(raw_value)
        if number == 0:
            return "0"
        return f"{number * 0.25:g}rem"
    named = {
        "xs": "20rem",
        "sm": "24rem",
        "md": "28rem",
        "lg": "32rem",
        "xl": "36rem",
        "2xl": "42rem",
        "3xl": "48rem",
        "4xl": "56rem",
        "5xl": "64rem",
        "6xl": "72rem",
        "7xl": "80rem",
        "prose": "65ch",
    }
    return named.get(raw_value)


def _dynamic_utility_declaration(token: str) -> str | None:
    """Translate an open-ended utility token into CSS declarations."""
    negative = token.startswith("-")
    if negative:
        token = token[1:]

    spacing_match = re.fullmatch(
        r"(m|mx|my|mt|mr|mb|ml|p|px|py|pt|pr|pb|pl|gap|gap-x|gap-y)-(.+)",
        token,
    )
    if spacing_match:
        kind, raw_value = spacing_match.groups()
        if negative and kind.startswith(("p", "gap")):
            return None
        value = _utility_size(raw_value, allow_auto=kind.startswith("m"))
        if value is None:
            return None
        if negative and value not in ("0", "auto"):
            value = f"calc({value} * -1)"
        properties = {
            "m": ("margin",),
            "mx": ("margin-inline",),
            "my": ("margin-block",),
            "mt": ("margin-top",),
            "mr": ("margin-right",),
            "mb": ("margin-bottom",),
            "ml": ("margin-left",),
            "p": ("padding",),
            "px": ("padding-inline",),
            "py": ("padding-block",),
            "pt": ("padding-top",),
            "pr": ("padding-right",),
            "pb": ("padding-bottom",),
            "pl": ("padding-left",),
            "gap": ("gap",),
            "gap-x": ("column-gap",),
            "gap-y": ("row-gap",),
        }[kind]
        return " ".join(f"{prop}: {value};" for prop in properties)

    inset_match = re.fullmatch(r"(inset|inset-x|inset-y|top|right|bottom|left)-(.+)", token)
    if inset_match:
        kind, raw_value = inset_match.groups()
        value = _utility_size(raw_value, allow_auto=True)
        if value is None:
            return None
        if negative and value not in ("0", "auto"):
            value = f"calc({value} * -1)"
        properties = {
            "inset": ("inset",),
            "inset-x": ("left", "right"),
            "inset-y": ("top", "bottom"),
            "top": ("top",),
            "right": ("right",),
            "bottom": ("bottom",),
            "left": ("left",),
        }[kind]
        return " ".join(f"{prop}: {value};" for prop in properties)

    size_match = re.fullmatch(r"(w|h|min-w|max-w|min-h|max-h|basis)-(.+)", token)
    if size_match and not negative:
        kind, raw_value = size_match.groups()
        value = _utility_size(raw_value, allow_auto=kind in ("w", "h", "basis"))
        if value is None:
            return None
        if raw_value == "screen" and kind in ("h", "min-h", "max-h"):
            value = "100vh"
        prop = {
            "w": "width",
            "h": "height",
            "min-w": "min-width",
            "max-w": "max-width",
            "min-h": "min-height",
            "max-h": "max-height",
            "basis": "flex-basis",
        }[kind]
        return f"{prop}: {value};"

    if negative:
        return None

    arbitrary_property_match = re.fullmatch(
        r"(text|bg|border|rounded|leading|tracking)-(.+)", token
    )
    if arbitrary_property_match:
        kind, raw_value = arbitrary_property_match.groups()
        value = _safe_arbitrary_css_value(raw_value)
        if value is not None:
            if kind == "text":
                color_like = value.startswith("#") or value.lower().startswith(
                    ("rgb(", "rgba(", "hsl(", "hsla(", "oklch(", "var(--color")
                )
                prop = "color" if color_like else "font-size"
            else:
                prop = {
                    "bg": "background",
                    "border": "border-color",
                    "rounded": "border-radius",
                    "leading": "line-height",
                    "tracking": "letter-spacing",
                }[kind]
            return f"{prop}: {value};"

    color_match = re.fullmatch(r"(text|bg|border)-(primary|secondary|success|warning|danger|info|surface|surface-2|muted|transparent|current)", token)
    if color_match:
        kind, color = color_match.groups()
        if color == "transparent":
            value = "transparent"
        elif color == "current":
            value = "currentColor"
        elif color == "muted":
            value = "var(--text-muted)"
        else:
            value = f"var(--{color})"
        prop = {"text": "color", "bg": "background-color", "border": "border-color"}[kind]
        return f"{prop}: {value};"

    simple_number = re.fullmatch(r"(opacity|z|order|grid-cols|col-span|row-span)-(-?\d+)", token)
    if simple_number:
        kind, number_text = simple_number.groups()
        number = int(number_text)
        if kind == "opacity" and 0 <= number <= 100:
            return f"opacity: {number / 100:g};"
        if kind == "z":
            return f"z-index: {number};"
        if kind == "order":
            return f"order: {number};"
        if kind == "grid-cols" and number > 0:
            return f"grid-template-columns: repeat({number}, minmax(0, 1fr));"
        if kind == "col-span" and number > 0:
            return f"grid-column: span {number} / span {number};"
        if kind == "row-span" and number > 0:
            return f"grid-row: span {number} / span {number};"

    rounded_match = re.fullmatch(r"rounded-(.+)", token)
    if rounded_match:
        value = _utility_size(rounded_match.group(1))
        return f"border-radius: {value};" if value is not None else None
    return None


def _important_declarations(declarations: str) -> str:
    return " ".join(
        f"{part.strip()} !important;"
        for part in declarations.split(";")
        if part.strip()
    )


def _generate_on_demand_utility_rules(
    class_names: Iterable[str], shortcuts: dict[str, Any]
) -> list[str]:
    """Generate responsive, stateful and arbitrary utility rules on demand."""
    rules: list[str] = []
    generated: set[str] = set()
    for full_class_name in sorted(set(class_names)):
        parts = full_class_name.split(":")
        token = parts[-1]
        prefixes = parts[:-1]
        important = False
        shortcut_found = False

        # A namespaced shortcut is itself colon-delimited (plugin:class).
        # Find the longest suffix present in the merged shortcut dictionary;
        # anything before it remains a responsive/state prefix.
        for index in range(len(parts)):
            candidate = ":".join(parts[index:])
            candidate_important = candidate.startswith("!")
            lookup_candidate = candidate[1:] if candidate_important else candidate
            if lookup_candidate in shortcuts:
                token = lookup_candidate
                prefixes = parts[:index]
                important = candidate_important
                shortcut_found = True
                break

        if not shortcut_found:
            important = token.startswith("!")
            if important:
                token = token[1:]

        if any(
            prefix not in _UTILITY_BREAKPOINTS
            and prefix not in _UTILITY_STATES
            and prefix != "dark"
            for prefix in prefixes
        ):
            continue

        declaration_value = shortcuts.get(token)
        declaration = (
            declaration_value.strip()
            if isinstance(declaration_value, str)
            else _dynamic_utility_declaration(token)
        )
        if not declaration:
            continue
        # Plain shortcuts, including plugin:shortcut, are already emitted.
        if not prefixes and not important and token in shortcuts:
            continue

        selector = f".{_css_escape_identifier(full_class_name)}"
        media: str | None = None
        dark = False
        for prefix in prefixes:
            if prefix in _UTILITY_BREAKPOINTS:
                media = _UTILITY_BREAKPOINTS[prefix]
            elif prefix == "dark":
                dark = True
            else:
                selector += _UTILITY_STATES[prefix]
        if dark:
            selector = f".theme-dark {selector}"
        if important:
            declaration = _important_declarations(declaration)
        rule = f"{selector} {{ {declaration.strip()} }}"
        if media:
            rule = f"@media (min-width: {media}) {{ {rule} }}"
        if rule not in generated:
            generated.add(rule)
            rules.append(rule)
    return rules


def _append_children(fragment: str, children_html: str) -> str:
    """Fallback for older templates that have no {{{children}}} placeholder."""
    if not children_html.strip():
        return fragment
    closing_tags = list(re.finditer(r"</[A-Za-z][A-Za-z0-9:_-]*\s*>", fragment))
    if not closing_tags:
        return fragment + children_html
    match = closing_tags[-1]
    return fragment[: match.start()] + children_html + fragment[match.start() :]


def _inject_root_attributes(
    fragment: str, attributes: dict[str, str], classes: Sequence[str]
) -> str:
    """Add generated data attributes and classes to the first HTML element."""
    opening = re.search(
        r"<([A-Za-z][A-Za-z0-9:_-]*)(\s[^<>]*?)?\s*(/?)>", fragment, flags=re.DOTALL
    )
    if not opening:
        return fragment

    tag = opening.group(1)
    attr_text = opening.group(2) or ""
    slash = opening.group(3) or ""

    class_match = re.search(r"\bclass\s*=\s*([\"'])(.*?)\1", attr_text, flags=re.DOTALL)
    unique_classes = list(dict.fromkeys(item for item in classes if item))
    if unique_classes:
        if class_match:
            existing = class_match.group(2).split()
            merged = " ".join(dict.fromkeys([*existing, *unique_classes]))
            replacement = f'class="{html.escape(merged, quote=True)}"'
            attr_text = (
                attr_text[: class_match.start()]
                + replacement
                + attr_text[class_match.end() :]
            )
        else:
            attr_text += f' class="{html.escape(" ".join(unique_classes), quote=True)}"'

    for name, value in attributes.items():
        if re.search(rf"(?<![\w:-]){re.escape(name)}\s*=", attr_text):
            continue
        attr_text += f' {name}="{html.escape(value, quote=True)}"'

    replacement = f"<{tag}{attr_text}{' /' if slash else ''}>"
    return fragment[: opening.start()] + replacement + fragment[opening.end() :]


def _indent_code(code: str, spaces: int) -> str:
    prefix = " " * spaces
    return "\n".join(prefix + line if line.strip() else "" for line in code.splitlines())


def _load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:
        raise ConfigurationError(f"File not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigurationError(
            f"Invalid JSON in {path} (line {exc.lineno}, column {exc.colno}): {exc.msg}"
        ) from exc
    except OSError as exc:
        raise ConfigurationError(f"Unable to read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigurationError(f"The root value in {path} must be a JSON object")
    return data


_PLUGIN_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
_PLUGIN_RESERVED_NAMES = {
    "core",
    "dark",
    *_UTILITY_BREAKPOINTS.keys(),
    *_UTILITY_STATES.keys(),
}


def _resolve_plugin_paths(plugin_paths: Sequence[str | Path] | None) -> list[Path]:
    """Resolve CLI/API plugin paths while preserving declaration order."""
    resolved: list[Path] = []
    values: Sequence[str | Path]
    if isinstance(plugin_paths, (str, Path)):
        values = [plugin_paths]
    else:
        values = plugin_paths or []
    for value in values:
        path = Path(value).expanduser().resolve()
        if path not in resolved:
            resolved.append(path)
    return resolved


def _validate_plugin_section_keys(
    plugin_name: str, section_name: str, section: Any, path: Path
) -> dict[str, Any]:
    if section is None:
        return {}
    if not isinstance(section, dict):
        raise ConfigurationError(
            f"Plugin {plugin_name!r}: {section_name!r} must be an object ({path})"
        )
    for local_name in section:
        if not isinstance(local_name, str) or not _PLUGIN_NAME_RE.fullmatch(local_name):
            raise ConfigurationError(
                f"Plugin {plugin_name!r}: invalid name in {section_name}: {local_name!r}. "
                "Local names must not contain ':'"
            )
    return section


def load_library_with_plugins(
    plugin_paths: Sequence[str | Path] | None = None,
    *,
    base_library_path: str | Path = DEFAULT_LIBRARY_PATH,
) -> tuple[dict[str, Any], list[PluginInfo]]:
    """Load the immutable core library and merge namespaced plugin libraries.

    A file ``marketing.json`` contributes ``marketing:hero`` components,
    ``marketing:ocean`` themes and ``marketing:glow`` shortcut classes.  The
    source dictionaries are deep-copied, so the canonical library is never
    modified on disk or in memory.
    """
    core_path = Path(base_library_path).expanduser().resolve()
    core_library = _load_json(core_path)
    merged = copy.deepcopy(core_library)
    merged.setdefault("components", {})
    merged.setdefault("themes", {})
    merged.setdefault("shortcuts", {})
    if not isinstance(merged["components"], dict):
        raise ConfigurationError("Core library.json: 'components' must be an object")
    if not isinstance(merged["themes"], dict):
        raise ConfigurationError("Core library.json: 'themes' must be an object")
    if not isinstance(merged["shortcuts"], dict):
        raise ConfigurationError("Core library.json: 'shortcuts' must be an object")
    merged["shortcuts"].setdefault("class", {})
    if not isinstance(merged["shortcuts"].get("class"), dict):
        raise ConfigurationError(
            "Core library.json: 'shortcuts.class' must be an object"
        )

    infos: list[PluginInfo] = []
    seen_names: dict[str, Path] = {}
    for plugin_path in _resolve_plugin_paths(plugin_paths):
        if plugin_path.suffix.lower() != ".json":
            raise ConfigurationError(
                f"A plugin must be a {{plugin-name}}.json file: {plugin_path}"
            )
        plugin_name = plugin_path.stem
        if not _PLUGIN_NAME_RE.fullmatch(plugin_name):
            raise ConfigurationError(
                f"Invalid plugin name {plugin_name!r}. Expected format: "
                "letters, digits, hyphens, and underscores, starting with a letter"
            )
        if plugin_name in _PLUGIN_RESERVED_NAMES:
            raise ConfigurationError(
                f"Reserved or ambiguous plugin name: {plugin_name!r}"
            )
        if plugin_name in seen_names:
            raise ConfigurationError(
                f"Duplicate plugin namespace {plugin_name!r}: {seen_names[plugin_name]} and {plugin_path}"
            )
        seen_names[plugin_name] = plugin_path

        plugin_library = _load_json(plugin_path)
        components = _validate_plugin_section_keys(
            plugin_name, "components", plugin_library.get("components", {}), plugin_path
        )
        themes = _validate_plugin_section_keys(
            plugin_name, "themes", plugin_library.get("themes", {}), plugin_path
        )
        shortcuts_container = plugin_library.get("shortcuts", {})
        if shortcuts_container is None:
            shortcuts_container = {}
        if not isinstance(shortcuts_container, dict):
            raise ConfigurationError(
                f"Plugin {plugin_name!r}: 'shortcuts' must be an object"
            )
        shortcut_classes = _validate_plugin_section_keys(
            plugin_name,
            "shortcuts.class",
            shortcuts_container.get("class", {}),
            plugin_path,
        )
        if not components and not themes and not shortcut_classes:
            raise ConfigurationError(
                f"Empty plugin {plugin_name!r}: add components, themes, or shortcuts.class"
            )

        plugin_renderer = MustacheRenderer()
        for local_name, definition in components.items():
            if not isinstance(definition, dict):
                raise ConfigurationError(
                    f"Plugin {plugin_name!r}: invalid component {local_name!r}"
                )
            variants = definition.get("variants")
            if not isinstance(variants, dict) or not variants:
                raise ConfigurationError(
                    f"Plugin {plugin_name!r}: component {local_name!r} must define variants"
                )
            for variant_name, variant_definition in variants.items():
                if not isinstance(variant_definition, dict) or not isinstance(
                    variant_definition.get("html"), str
                ):
                    raise ConfigurationError(
                        f"Plugin {plugin_name!r}: missing template for "
                        f"{local_name!r}/{variant_name!r}"
                    )
                try:
                    plugin_renderer.parse(variant_definition["html"])
                except TemplateError as exc:
                    raise ConfigurationError(
                        f"Plugin {plugin_name!r}: invalid template for "
                        f"{local_name!r}/{variant_name!r}: {exc}"
                    ) from exc
        for local_name, definition in themes.items():
            if not isinstance(definition, dict) or not isinstance(
                definition.get("css"), str
            ):
                raise ConfigurationError(
                    f"Plugin {plugin_name!r}: theme {local_name!r} does not contain valid CSS"
                )

        for local_name, definition in components.items():
            merged["components"][f"{plugin_name}:{local_name}"] = copy.deepcopy(definition)
        for local_name, definition in themes.items():
            merged["themes"][f"{plugin_name}:{local_name}"] = copy.deepcopy(definition)
        for local_name, declarations in shortcut_classes.items():
            if not isinstance(declarations, str):
                raise ConfigurationError(
                    f"Plugin {plugin_name!r}: shortcut {local_name!r} must be a CSS string"
                )
            merged["shortcuts"]["class"][
                f"{plugin_name}:{local_name}"
            ] = declarations

        version = str(plugin_library.get("version", "unspecified"))
        infos.append(
            PluginInfo(
                name=plugin_name,
                path=plugin_path,
                version=version,
                component_count=len(components),
                theme_count=len(themes),
                shortcut_count=len(shortcut_classes),
            )
        )

    merged["_loaded_plugins"] = [
        {
            "name": info.name,
            "path": str(info.path),
            "version": info.version,
        }
        for info in infos
    ]
    return merged, infos


# ---------------------------------------------------------------------------
# Site builder
# ---------------------------------------------------------------------------


class SiteBuilder:
    """Validate one configuration and generate all website artifacts."""

    def __init__(
        self,
        build_data: dict[str, Any],
        library_data: dict[str, Any],
        input_path: Path,
        output_dir: Path,
        logger: BuildLogger,
    ) -> None:
        self.build_data = build_data
        self.library_data = library_data
        self.input_path = input_path
        self.project_dir = input_path.parent
        self.output_dir = output_dir
        self.logger = logger
        self.renderer = MustacheRenderer()
        self.pages: list[tuple[dict[str, Any], list[ComponentUse]]] = []
        self.assets: list[AssetMapping] = []

    # ------------------------------ validation -----------------------------

    def validate(self) -> bool:
        components_library = self.library_data.get("components")
        if not isinstance(components_library, dict) or not components_library:
            self.logger.error("library.json must contain a non-empty 'components' object")
            components_library = {}

        themes = self.library_data.get("themes", {})
        if not isinstance(themes, dict):
            self.logger.error("library.json: 'themes' must be an object")
            themes = {}

        meta = self.build_data.get("meta", {})
        if not isinstance(meta, dict):
            self.logger.error("build.json: 'meta' must be an object")
            meta = {}
        theme_name = meta.get("theme", "light")
        if theme_name not in themes:
            self.logger.error(f"Theme {theme_name!r} was not found in the loaded libraries")

        raw_pages = self.build_data.get("pages")
        if not isinstance(raw_pages, list) or not raw_pages:
            self.logger.error("build.json: 'pages' must be a non-empty array")
            raw_pages = []

        seen_page_paths: set[str] = set()
        for page_index, page in enumerate(raw_pages):
            if not isinstance(page, dict):
                self.logger.error(f"Page #{page_index + 1} must be an object")
                continue
            page_path = page.get("path")
            if not isinstance(page_path, str) or not page_path.strip():
                self.logger.error(f"Page #{page_index + 1} must define a 'path' field")
                continue
            safe_page_path = _safe_posix_path(page_path)
            if safe_page_path is None or safe_page_path.suffix.lower() not in (".html", ".htm"):
                self.logger.error(
                    f"Unsafe or non-HTML page path: {page_path!r}", page=page_path
                )
                continue
            canonical_page_path = safe_page_path.as_posix()
            if canonical_page_path in seen_page_paths:
                self.logger.error(
                    f"Duplicate page path: {canonical_page_path!r}",
                    page=canonical_page_path,
                )
                continue
            seen_page_paths.add(canonical_page_path)

            raw_components = page.get("components", [])
            if not isinstance(raw_components, list):
                self.logger.error(
                    "The page 'components' field must be an array",
                    page=canonical_page_path,
                )
                raw_components = []

            page_uses: list[ComponentUse] = []
            for component_index, raw_component in enumerate(raw_components):
                use = self._validate_component(
                    raw_component,
                    components_library,
                    canonical_page_path,
                    str(component_index),
                )
                if use is not None:
                    page_uses.append(use)
            self.pages.append((page, page_uses))

        self._validate_assets(meta)
        self._validate_library_templates(components_library)
        return not self.logger.has_errors

    def _validate_component(
        self,
        raw_component: Any,
        components_library: dict[str, Any],
        page_path: str,
        tree_path: str,
    ) -> ComponentUse | None:
        location = f"component {tree_path}"
        if not isinstance(raw_component, dict):
            self.logger.error(f"{location} must be an object", page=page_path)
            return None

        type_name = raw_component.get("type")
        if not isinstance(type_name, str) or not type_name:
            self.logger.error(f"{location}: required 'type' field is missing", page=page_path)
            return None
        component_definition = components_library.get(type_name)
        if not isinstance(component_definition, dict):
            self.logger.error(
                f"Component {type_name!r} was not found in the loaded libraries",
                page=page_path,
                component=tree_path,
            )
            return None

        variants = component_definition.get("variants")
        if not isinstance(variants, dict) or not variants:
            self.logger.error(
                f"Component {type_name!r} has no valid variants",
                page=page_path,
                component=tree_path,
            )
            return None
        variant_name = raw_component.get("variant") or component_definition.get("default_variant")
        if not variant_name:
            variant_name = next(iter(variants))
        if not isinstance(variant_name, str) or not isinstance(variants.get(variant_name), dict):
            self.logger.error(
                f"Variant {variant_name!r} was not found for component {type_name!r}",
                page=page_path,
                component=tree_path,
            )
            return None
        variant_definition = variants[variant_name]

        defaults: dict[str, Any] = {}
        if isinstance(component_definition.get("defaults"), dict):
            defaults = _deep_merge(defaults, component_definition["defaults"])
        if isinstance(variant_definition.get("defaults"), dict):
            defaults = _deep_merge(defaults, variant_definition["defaults"])
        merged_data = _deep_merge(defaults, raw_component)
        merged_data["type"] = type_name
        merged_data["variant"] = variant_name

        required_fields: list[str] = []
        for definition in (component_definition, variant_definition):
            value = definition.get("required", [])
            if isinstance(value, list):
                required_fields.extend(item for item in value if isinstance(item, str))
        for required_path in dict.fromkeys(required_fields):
            value = _get_path(merged_data, required_path)
            if value is MISSING or value is None or value == "":
                self.logger.error(
                    f"Missing required field {required_path!r} for {type_name!r}",
                    page=page_path,
                    component=tree_path,
                )

        class_value = raw_component.get("class", [])
        if not isinstance(class_value, (str, list)) or (
            isinstance(class_value, list)
            and any(not isinstance(item, str) for item in class_value)
        ):
            self.logger.error(
                f"The 'class' field of {type_name!r} must be a string or an array of strings",
                page=page_path,
                component=tree_path,
            )
        classes = _normalise_classes(merged_data.get("class"))

        explicit_id_value = raw_component.get("id")
        explicit_id: str | None
        if explicit_id_value is None:
            explicit_id = None
        elif isinstance(explicit_id_value, (str, int)):
            explicit_id = str(explicit_id_value)
        else:
            explicit_id = None
            self.logger.error(
                f"The 'id' field of {type_name!r} must be a string or integer",
                page=page_path,
                component=tree_path,
            )

        events_value = raw_component.get("events", {})
        events: dict[str, str] = {}
        if not isinstance(events_value, dict):
            self.logger.error(
                f"The 'events' field of {type_name!r} must be an object",
                page=page_path,
                component=tree_path,
            )
        else:
            for event_name, event_code in events_value.items():
                if not isinstance(event_name, str) or not re.fullmatch(
                    r"[A-Za-z][A-Za-z0-9:_-]*", event_name
                ):
                    self.logger.error(
                        f"Invalid event name: {event_name!r}",
                        page=page_path,
                        component=tree_path,
                    )
                elif not isinstance(event_code, str):
                    self.logger.error(
                        f"Event code for {event_name!r} must be a string",
                        page=page_path,
                        component=tree_path,
                    )
                else:
                    events[event_name] = event_code

        raw_children = raw_component.get("children", [])
        if not isinstance(raw_children, list):
            self.logger.error(
                f"The 'children' field of {type_name!r} must be an array",
                page=page_path,
                component=tree_path,
            )
            raw_children = []
        if raw_children and component_definition.get("accepts_children", True) is False:
            self.logger.error(
                f"Component {type_name!r} does not accept children",
                page=page_path,
                component=tree_path,
            )

        children: list[ComponentUse] = []
        for child_index, raw_child in enumerate(raw_children):
            child = self._validate_component(
                raw_child,
                components_library,
                page_path,
                f"{tree_path}.{child_index}",
            )
            if child is not None:
                children.append(child)

        instance_seed = explicit_id or "component"
        page_slug = re.sub(r"[^A-Za-z0-9_-]+", "-", page_path).strip("-")
        instance_id = f"{page_slug}--{tree_path.replace('.', '-')}--{instance_seed}"

        return ComponentUse(
            type_name=type_name,
            variant_name=variant_name,
            component_definition=component_definition,
            variant_definition=variant_definition,
            data=merged_data,
            page_path=page_path,
            tree_path=tree_path,
            instance_id=instance_id,
            explicit_id=explicit_id,
            classes=classes,
            events=events,
            children=children,
        )

    def _resolve_asset(self, reference: str) -> AssetMapping | None:
        safe_path = _safe_posix_path(reference)
        if safe_path is None:
            return None
        parts = list(safe_path.parts)
        if parts and parts[0] == "assets":
            destination_parts = parts[1:]
            candidates = [self.project_dir.joinpath(*parts)]
        else:
            destination_parts = parts
            candidates = [
                self.project_dir.joinpath("assets", *parts),
                self.project_dir.joinpath(*parts),
            ]
        if not destination_parts:
            return None
        source = next((candidate for candidate in candidates if candidate.is_file()), candidates[0])
        return AssetMapping(reference, source, PurePosixPath(*destination_parts))

    def _validate_assets(self, meta: dict[str, Any]) -> None:
        asset_references = self.build_data.get("assets", [])
        if not isinstance(asset_references, list):
            self.logger.error("build.json: 'assets' must be an array")
            asset_references = []
        references: list[Any] = list(asset_references)
        favicon_candidates: list[Any] = [meta.get("favicon")]
        for page, _ in self.pages:
            page_meta = page.get("meta", {})
            if isinstance(page_meta, dict):
                favicon_candidates.append(page_meta.get("favicon"))
        for favicon in favicon_candidates:
            if favicon and favicon not in references:
                references.append(favicon)

        destinations: dict[str, str] = {}
        for reference in references:
            if not isinstance(reference, str):
                self.logger.error(f"Invalid asset reference: {reference!r}")
                continue
            mapping = self._resolve_asset(reference)
            if mapping is None:
                self.logger.error(f"Unsafe asset path: {reference!r}")
                continue
            if not mapping.source.is_file():
                self.logger.error(f"Asset not found: {reference!r}")
                continue
            destination_key = mapping.destination_relative.as_posix()
            previous = destinations.get(destination_key)
            if previous and previous != str(mapping.source):
                self.logger.error(
                    f"Two assets target build/assets/{destination_key}: {previous!r} and {reference!r}"
                )
                continue
            destinations[destination_key] = str(mapping.source)
            if all(item.destination_relative != mapping.destination_relative for item in self.assets):
                self.assets.append(mapping)

    def _validate_library_templates(self, components_library: dict[str, Any]) -> None:
        """Parse only variants used by this build so template errors are reported early."""
        checked: set[tuple[str, str]] = set()
        for use in self._all_uses():
            key = (use.type_name, use.variant_name)
            if key in checked:
                continue
            checked.add(key)
            template = use.variant_definition.get("html")
            if not isinstance(template, str) or not template.strip():
                self.logger.error(
                    f"Missing HTML template for {use.type_name!r}/{use.variant_name!r}"
                )
                continue
            try:
                self.renderer.parse(template)
            except TemplateError as exc:
                self.logger.error(
                    f"Invalid template for {use.type_name!r}/{use.variant_name!r}: {exc}"
                )

    # ------------------------------ generation -----------------------------

    def generate(self) -> None:
        self._prepare_output()
        self._generate_global_css()
        self._generate_component_css()
        js_types = self._generate_component_js()
        self._generate_global_js()
        self._copy_assets()
        self._generate_pages(js_types)

    def _prepare_output(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        # Remove only artifacts owned by WeBuilder. Unknown files in the output
        # root are preserved, while stale generated pages are deleted.
        for pattern in ("*.html", "*.htm"):
            for page_file in self.output_dir.rglob(pattern):
                if page_file.is_file() or page_file.is_symlink():
                    page_file.unlink()
        for directory_name in ("css", "js", "assets"):
            target = self.output_dir / directory_name
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
        (self.output_dir / "css").mkdir(parents=True, exist_ok=True)
        (self.output_dir / "js" / "components").mkdir(parents=True, exist_ok=True)
        (self.output_dir / "assets").mkdir(parents=True, exist_ok=True)

    def _generate_global_css(self) -> None:
        meta = self.build_data.get("meta", {})
        theme_name = meta.get("theme", "light")
        theme_definition = self.library_data.get("themes", {}).get(theme_name, {})
        theme_css = theme_definition.get("css", "") if isinstance(theme_definition, dict) else ""
        responsive_base = """

/* WeBuilder responsive base */
*, *::before, *::after { box-sizing: border-box; }
html { color-scheme: var(--color-scheme, normal); scroll-behavior: smooth; }
body { margin: 0; min-height: 100vh; background: var(--bg); color: var(--text); font-family: var(--font-sans, system-ui, sans-serif); line-height: 1.5; }
img, picture, video, canvas, svg { display: block; max-width: 100%; }
button, input, textarea, select { font: inherit; }
a { color: var(--primary); }
[hidden] { display: none !important; }
""".strip()
        (self.output_dir / "css" / "global.css").write_text(
            theme_css.rstrip() + "\n\n" + responsive_base + "\n", encoding="utf-8"
        )

        shortcut_lines = ["/* Static utilities from library.json shortcuts.class */"]
        shortcuts_value = self.library_data.get("shortcuts", {}).get("class", {})
        shortcuts: dict[str, Any] = shortcuts_value if isinstance(shortcuts_value, dict) else {}
        for class_name, declarations in shortcuts.items():
            if isinstance(class_name, str) and isinstance(declarations, str):
                shortcut_lines.append(
                    f".{_css_escape_identifier(class_name)} {{ {declarations.strip()} }}"
                )

        used_classes = [class_name for use in self._all_uses() for class_name in use.classes]
        dynamic_rules = _generate_on_demand_utility_rules(used_classes, shortcuts)
        if dynamic_rules:
            shortcut_lines.extend(
                [
                    "",
                    "/* On-demand utilities discovered in build.json.",
                    "   Supports arbitrary spacing, values, states and breakpoints. */",
                    *dynamic_rules,
                ]
            )
        (self.output_dir / "css" / "shortcuts.css").write_text(
            "\n".join(shortcut_lines) + "\n", encoding="utf-8"
        )

    def _generate_component_css(self) -> None:
        uses_by_variant: dict[tuple[str, str], list[ComponentUse]] = {}
        for use in self._all_uses():
            uses_by_variant.setdefault((use.type_name, use.variant_name), []).append(use)

        for (type_name, variant_name), uses in uses_by_variant.items():
            component_definition = uses[0].component_definition
            variant_definition = uses[0].variant_definition
            chunks = [f"/* WeBuilder: {type_name} / {variant_name} */"]
            base_css = component_definition.get("css", "")
            variant_css = variant_definition.get("css", "")
            if isinstance(base_css, str) and base_css.strip():
                chunks.append(base_css.strip())
            if isinstance(variant_css, str) and variant_css.strip():
                chunks.append(variant_css.strip())
            used_classes = sorted({class_name for use in uses for class_name in use.classes})
            if used_classes:
                chunks.append(
                    "/* Instance classes: "
                    + ", ".join(used_classes)
                    + ". Shortcut declarations live in shortcuts.css. */"
                )
            filename = f"{_artifact_name(type_name)}-{_artifact_name(variant_name)}.css"
            (self.output_dir / "css" / filename).write_text(
                "\n\n".join(chunks).rstrip() + "\n", encoding="utf-8"
            )

    def _generate_component_js(self) -> set[str]:
        uses_by_type: dict[str, list[ComponentUse]] = {}
        for use in self._all_uses():
            uses_by_type.setdefault(use.type_name, []).append(use)

        generated_types: set[str] = set()
        for type_name, uses in uses_by_type.items():
            snippets: list[str] = []
            seen_snippets: set[str] = set()
            component_js = uses[0].component_definition.get("js", "")
            if isinstance(component_js, str) and component_js.strip():
                snippets.append(component_js.strip())
                seen_snippets.add(component_js.strip())

            for use in uses:
                variant_js = use.variant_definition.get("js", "")
                if (
                    isinstance(variant_js, str)
                    and variant_js.strip()
                    and variant_js.strip() not in seen_snippets
                ):
                    snippets.append(variant_js.strip())
                    seen_snippets.add(variant_js.strip())

            for use in uses:
                for event_name, event_code in use.events.items():
                    instance_literal = json.dumps(use.instance_id, ensure_ascii=False)
                    event_literal = json.dumps(event_name, ensure_ascii=False)
                    code = event_code.strip()
                    listener = f"""// build.json: {use.page_path} / component {use.tree_path}
document.querySelectorAll('[data-wb-instance]').forEach((element) => {{
  if (element.dataset.wbInstance === {instance_literal}) {{
    element.addEventListener({event_literal}, (event) => {{
      const el = event.currentTarget;
{_indent_code(code, 6)}
    }});
  }}
}});"""
                    snippets.append(listener)

            if not snippets:
                continue
            generated_types.add(type_name)
            wrapped = (
                f"/* WeBuilder component: {type_name} */\n"
                "window.WeBuilder.ready(() => {\n"
                + _indent_code("\n\n".join(snippets), 2)
                + "\n});\n"
            )
            filename = f"{_artifact_name(type_name)}.js"
            (self.output_dir / "js" / "components" / filename).write_text(
                wrapped, encoding="utf-8"
            )
        return generated_types

    def _generate_global_js(self) -> None:
        script = f"""/* WeBuilder global runtime v{VERSION} */
(() => {{
  const callbacks = [];
  let ready = document.readyState !== 'loading';

  window.WeBuilder = {{
    version: {json.dumps(VERSION)},
    ready(callback) {{
      if (ready) callback();
      else callbacks.push(callback);
    }},
    registerInitializer(callback) {{ this.ready(callback); }}
  }};

  if (!ready) {{
    document.addEventListener('DOMContentLoaded', () => {{
      ready = true;
      callbacks.splice(0).forEach((callback) => callback());
      document.dispatchEvent(new CustomEvent('webuilder:ready'));
    }}, {{ once: true }});
  }} else {{
    queueMicrotask(() => document.dispatchEvent(new CustomEvent('webuilder:ready')));
  }}
}})();
"""
        (self.output_dir / "js" / "global.js").write_text(script, encoding="utf-8")

    def _copy_assets(self) -> None:
        assets_root = self.output_dir / "assets"
        for mapping in self.assets:
            destination = assets_root.joinpath(*mapping.destination_relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(mapping.source, destination)

    def _render_component(self, use: ComponentUse) -> str:
        children_html = "\n".join(self._render_component(child) for child in use.children)
        context = copy.deepcopy(use.data)
        context["class"] = " ".join(use.classes)
        context["variant"] = use.variant_name
        context["id"] = use.explicit_id or use.instance_id
        context["children"] = children_html

        template = use.variant_definition["html"]
        rendered = self.renderer.render(template, context)
        if children_html and not re.search(
            r"\{\{\{?\s*children\s*\}?\}\}", template
        ):
            rendered = _append_children(rendered, children_html)

        attributes = {
            "data-wb-component": use.type_name,
            "data-wb-variant": use.variant_name,
            "data-wb-instance": use.instance_id,
            "data-wb-page": use.page_path,
        }
        if use.explicit_id is not None:
            attributes["data-id"] = use.explicit_id
        return _inject_root_attributes(rendered, attributes, use.classes)

    def _generate_pages(self, generated_js_types: set[str]) -> None:
        global_meta = self.build_data.get("meta", {})
        theme_name = str(global_meta.get("theme", "light"))

        for page, root_uses in self.pages:
            page_meta = _deep_merge(global_meta, page.get("meta", {})) if isinstance(page.get("meta"), dict) else global_meta
            page_path = str(page["path"]).replace("\\", "/")
            title = page_meta.get("title", "Site WeBuilder")
            lang = page_meta.get("lang", "en")
            description = page_meta.get("description", "")
            author = page_meta.get("author", "")
            robots = page_meta.get("robots", "")

            page_uses = list(self._walk_uses(root_uses))
            variant_keys = list(
                dict.fromkeys((use.type_name, use.variant_name) for use in page_uses)
            )
            type_names = list(dict.fromkeys(use.type_name for use in page_uses))

            css_links = ['  <link rel="stylesheet" href="/css/global.css">']
            for type_name, variant_name in variant_keys:
                filename = f"{_artifact_name(type_name)}-{_artifact_name(variant_name)}.css"
                css_links.append(f'  <link rel="stylesheet" href="/css/{filename}">')
            # Utilities are intentionally last: classes explicitly attached to
            # an instance must be able to override component defaults.
            css_links.append('  <link rel="stylesheet" href="/css/shortcuts.css">')

            meta_lines = [
                '  <meta charset="UTF-8">',
                '  <meta name="viewport" content="width=device-width, initial-scale=1.0">',
            ]
            if description:
                meta_lines.append(
                    f'  <meta name="description" content="{html.escape(str(description), quote=True)}">'
                )
            if author:
                meta_lines.append(
                    f'  <meta name="author" content="{html.escape(str(author), quote=True)}">'
                )
            if robots:
                meta_lines.append(
                    f'  <meta name="robots" content="{html.escape(str(robots), quote=True)}">'
                )

            favicon_line = ""
            favicon = page_meta.get("favicon")
            if isinstance(favicon, str) and favicon:
                favicon_path = favicon.replace("\\", "/").lstrip("/")
                if favicon_path.startswith("assets/"):
                    favicon_path = favicon_path[len("assets/") :]
                favicon_line = (
                    f'  <link rel="icon" href="/assets/{html.escape(favicon_path, quote=True)}">\n'
                )

            body_content = "\n".join(self._render_component(use) for use in root_uses)
            script_lines = ['  <script src="/js/global.js"></script>']
            for type_name in type_names:
                if type_name in generated_js_types:
                    filename = f"{_artifact_name(type_name)}.js"
                    script_lines.append(
                        f'  <script src="/js/components/{filename}"></script>'
                    )

            document = f"""<!DOCTYPE html>
<html lang="{html.escape(str(lang), quote=True)}">
<head>
{chr(10).join(meta_lines)}
  <title>{html.escape(str(title))}</title>
{favicon_line}{chr(10).join(css_links)}
</head>
<body class="theme-{html.escape(theme_name, quote=True)}">
{body_content}
{chr(10).join(script_lines)}
</body>
</html>
"""
            target = self.output_dir.joinpath(*PurePosixPath(page_path).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(document, encoding="utf-8")

    # ------------------------------- iterators ------------------------------

    @staticmethod
    def _walk_uses(roots: Iterable[ComponentUse]) -> Iterable[ComponentUse]:
        for use in roots:
            yield use
            yield from SiteBuilder._walk_uses(use.children)

    def _all_uses(self) -> Iterable[ComponentUse]:
        for _, roots in self.pages:
            yield from self._walk_uses(roots)


# ---------------------------------------------------------------------------
# Public build function and CLI
# ---------------------------------------------------------------------------


def build_site(
    input_path: str | Path = "build.json",
    output_dir: str | Path = "./build",
    library_path: str | Path | None = None,
    plugin_paths: Sequence[str | Path] | None = None,
    *,
    quiet: bool = False,
) -> bool:
    """Run one build with the core library plus optional namespaced plugins."""
    input_file = Path(input_path).expanduser().resolve()
    output = Path(output_dir).expanduser().resolve()
    library_file = (
        Path(library_path).expanduser().resolve()
        if library_path is not None
        else DEFAULT_LIBRARY_PATH
    )
    logger = BuildLogger(output)

    try:
        # The output is an owned build directory.  Refuse a project directory
        # (or one of its parents) so cleanup can never remove source assets.
        if output == input_file or output in input_file.parents:
            logger.error(
                "The output directory must be dedicated; it cannot be the project directory or one of its parents"
            )
            if not quiet:
                print("Build failed: unsafe output directory", file=sys.stderr)
            return False
        build_data = _load_json(input_file)
        library_data, plugin_infos = load_library_with_plugins(
            plugin_paths,
            base_library_path=library_file,
        )
        for plugin_info in plugin_infos:
            logger.info(
                "Plugin loaded",
                plugin=plugin_info.name,
                version=plugin_info.version,
                path=str(plugin_info.path),
                components=plugin_info.component_count,
                themes=plugin_info.theme_count,
                shortcuts=plugin_info.shortcut_count,
            )
        builder = SiteBuilder(build_data, library_data, input_file, output, logger)
        if not builder.validate():
            if not quiet:
                print(f"Build failed: see {output / 'log.json'}", file=sys.stderr)
            return False
        builder.generate()
        page_count = len(builder.pages)
        logger.info(
            "Build successful",
            pages=page_count,
            plugins=[info.name for info in plugin_infos],
            output=str(output),
        )
        if not quiet:
            print(f"Build successful: {page_count} page(s) generated in {output}")
        return True
    except (ConfigurationError, TemplateError) as exc:
        logger.error(str(exc))
        if not quiet:
            print(f"Build failed: {exc}", file=sys.stderr)
        return False
    except Exception as exc:  # Last-resort structured logging for CLI users.
        logger.error(f"Unexpected error: {type(exc).__name__}: {exc}")
        if not quiet:
            print(f"Build failed unexpectedly: {exc}", file=sys.stderr)
        return False
    finally:
        try:
            logger.write()
        except OSError as exc:
            if not quiet:
                print(f"Unable to write log.json: {exc}", file=sys.stderr)


class PreviewState:
    """Thread-safe generation counter consumed by the live-reload endpoint."""

    def __init__(self, version: int = 0) -> None:
        self._version = version
        self._lock = threading.Lock()

    @property
    def version(self) -> int:
        with self._lock:
            return self._version

    def bump(self) -> None:
        with self._lock:
            self._version += 1


class PreviewRequestHandler(SimpleHTTPRequestHandler):
    """Static preview handler with clean URLs and injected live reload."""

    server_version = "WeBuilderPreview/1.3"

    def __init__(
        self,
        *args: Any,
        directory: str,
        preview_state: PreviewState,
        **kwargs: Any,
    ) -> None:
        self.preview_state = preview_state
        super().__init__(*args, directory=directory, **kwargs)

    def log_message(self, message_format: str, *args: Any) -> None:
        # Keep the development terminal readable while still surfacing errors.
        if len(args) > 1 and str(args[1]).startswith(("4", "5")):
            super().log_message(message_format, *args)

    def _send_status(self, head_only: bool = False) -> None:
        payload = json.dumps({"version": self.preview_state.version}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if not head_only:
            self.wfile.write(payload)

    def _rewrite_clean_url(self) -> None:
        parsed = urlsplit(self.path)
        request_path = parsed.path
        if request_path == "/":
            request_path = "/index.html"
        elif not PurePosixPath(request_path).suffix:
            candidate_path = request_path.rstrip("/") + ".html"
            translated = Path(self.translate_path(candidate_path))
            if translated.is_file():
                request_path = candidate_path
        self.path = urlunsplit(
            (parsed.scheme, parsed.netloc, request_path, parsed.query, parsed.fragment)
        )

    def _serve_html(self, head_only: bool = False) -> bool:
        parsed = urlsplit(self.path)
        if not parsed.path.lower().endswith((".html", ".htm")):
            return False
        file_path = Path(self.translate_path(parsed.path))
        if not file_path.is_file():
            return False
        try:
            document = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return False
        initial_version = self.preview_state.version
        live_reload = f"""<script data-webuilder-preview>
(() => {{
  let version = {initial_version};
  const check = async () => {{
    try {{
      const response = await fetch('/__webuilder/status', {{ cache: 'no-store' }});
      const state = await response.json();
      if (state.version !== version) location.reload();
    }} catch (_) {{ /* The preview server may be restarting. */ }}
  }};
  setInterval(check, 700);
}})();
</script>"""
        if "</body>" in document:
            document = document.replace("</body>", live_reload + "\n</body>", 1)
        else:
            document += live_reload
        payload = document.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if not head_only:
            self.wfile.write(payload)
        return True

    def do_GET(self) -> None:  # noqa: N802 - name required by http.server
        if urlsplit(self.path).path == "/__webuilder/status":
            self._send_status()
            return
        self._rewrite_clean_url()
        if not self._serve_html():
            super().do_GET()

    def do_HEAD(self) -> None:  # noqa: N802 - name required by http.server
        if urlsplit(self.path).path == "/__webuilder/status":
            self._send_status(head_only=True)
            return
        self._rewrite_clean_url()
        if not self._serve_html(head_only=True):
            super().do_HEAD()


def _start_watcher(
    input_path: str | Path,
    output_dir: str | Path,
    plugin_paths: Sequence[str | Path] | None = None,
    on_success: Callable[[], None] | None = None,
) -> Any | None:
    """Watch build.json, assets, the core library and every loaded plugin."""
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
    except ImportError:
        print(
            "Watch mode requires watchdog. Install it with: pip install watchdog",
            file=sys.stderr,
        )
        return None

    watched_file = Path(input_path).expanduser().resolve()
    project_assets = watched_file.parent / "assets"
    resolved_plugins = _resolve_plugin_paths(plugin_paths)
    watched_plugin_paths = set(resolved_plugins)
    last_rebuild = 0.0
    rebuild_lock = threading.Lock()

    def is_relevant(path_text: str) -> bool:
        if not path_text:
            return False
        path = Path(path_text).resolve()
        if path in (watched_file, DEFAULT_LIBRARY_PATH) or path in watched_plugin_paths:
            return True
        return project_assets.exists() and path.is_relative_to(project_assets)

    class BuildFileHandler(FileSystemEventHandler):
        def _handle(self, event: Any) -> None:
            nonlocal last_rebuild
            if getattr(event, "is_directory", False):
                return
            paths = [
                path
                for path in (
                    getattr(event, "src_path", ""),
                    getattr(event, "dest_path", ""),
                )
                if path and is_relevant(path)
            ]
            if not paths:
                return
            now = time.monotonic()
            if now - last_rebuild < 0.3 or not rebuild_lock.acquire(blocking=False):
                return
            last_rebuild = now
            try:
                changed = Path(paths[-1]).name
                print(f"\nRebuilding due to changes in {changed}...")
                if build_site(
                    watched_file,
                    output_dir,
                    plugin_paths=resolved_plugins,
                ) and on_success is not None:
                    on_success()
            finally:
                rebuild_lock.release()

        def on_modified(self, event: Any) -> None:
            self._handle(event)

        def on_created(self, event: Any) -> None:
            self._handle(event)

        def on_deleted(self, event: Any) -> None:
            self._handle(event)

        def on_moved(self, event: Any) -> None:
            self._handle(event)

    observer = Observer()
    scheduled: set[Path] = set()
    # Recursive project watching captures build.json and source assets. Events
    # produced inside output_dir are filtered by is_relevant().
    watch_locations: list[tuple[Path, bool]] = [
        (watched_file.parent, True),
        (DEFAULT_LIBRARY_PATH.parent, False),
        *((plugin_path.parent, False) for plugin_path in resolved_plugins),
    ]
    for directory, recursive in watch_locations:
        if directory in scheduled or not directory.exists():
            continue
        observer.schedule(BuildFileHandler(), str(directory), recursive=recursive)
        scheduled.add(directory)
    observer.start()
    return observer


def watch_build(
    input_path: str | Path,
    output_dir: str | Path,
    plugin_paths: Sequence[str | Path] | None = None,
) -> int:
    """Build once, then keep rebuilding all relevant project and plugin inputs."""
    build_site(input_path, output_dir, plugin_paths=plugin_paths)
    observer = _start_watcher(input_path, output_dir, plugin_paths)
    if observer is None:
        return 2
    plugin_label = ", ".join(path.name for path in _resolve_plugin_paths(plugin_paths))
    watched_label = "build.json, source assets, WeBuilder/library.json"
    if plugin_label:
        watched_label += f", plugins: {plugin_label}"
    print(f"Watching {watched_label} — Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping WeBuilder watch mode…")
        observer.stop()
    observer.join()
    return 0


def preview_site(
    input_path: str | Path,
    output_dir: str | Path,
    *,
    plugin_paths: Sequence[str | Path] | None,
    watch: bool,
    host: str,
    port: int,
    open_browser: bool,
) -> int:
    """Build and serve the output from the same terminal with live reload."""
    output = Path(output_dir).expanduser().resolve()
    state = PreviewState()
    if build_site(input_path, output, plugin_paths=plugin_paths):
        state.bump()

    observer = (
        _start_watcher(input_path, output, plugin_paths, state.bump) if watch else None
    )
    if watch and observer is None:
        return 2

    handler = partial(
        PreviewRequestHandler,
        directory=str(output),
        preview_state=state,
    )
    try:
        server = ThreadingHTTPServer((host, port), handler)
    except OSError as exc:
        if observer is not None:
            observer.stop()
            observer.join()
        print(f"Unable to start the preview server on {host}:{port}: {exc}", file=sys.stderr)
        return 2

    actual_port = int(server.server_address[1])
    browser_host = "localhost" if host in ("0.0.0.0", "::", "127.0.0.1") else host
    url = f"http://{browser_host}:{actual_port}/"
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"  WeBuilder preview: {url}")
    print(f"  Output: {output}")
    print(f"  Live reload: {'on' if watch else 'off'}")
    print("  Press Ctrl+C to stop.")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

    if open_browser:
        threading.Timer(0.35, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\nStopping WeBuilder preview…")
    finally:
        server.server_close()
        if observer is not None:
            observer.stop()
            observer.join()
    return 0


def initialise_project(target_directory: str | Path) -> int:
    """Create a lightweight project that reuses WeBuilder's canonical library."""
    target = Path(target_directory).expanduser().resolve()
    build_file = target / "build.json"
    if build_file.exists():
        print(f"Initialization cancelled: {build_file} already exists.", file=sys.stderr)
        return 1
    target.mkdir(parents=True, exist_ok=True)
    (target / "assets" / "images").mkdir(parents=True, exist_ok=True)
    (target / "plugins").mkdir(parents=True, exist_ok=True)
    starter = {
        "meta": {
            "title": "My new website",
            "theme": "light",
            "lang": "en",
            "description": "Website created with WeBuilder",
        },
        "assets": [],
        "pages": [
            {
                "path": "index.html",
                "components": [
                    {
                        "type": "hero",
                        "variant": "centered",
                        "content": {
                            "eyebrow": "New project",
                            "title": "Your website starts here",
                            "text": "Edit build.json and use the integrated preview with live reload.",
                        },
                        "children": [
                            {
                                "type": "button",
                                "variant": "primary",
                                "content": {"text": "Get started"},
                            }
                        ],
                    }
                ],
            }
        ],
    }
    build_file.write_text(
        json.dumps(starter, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Project created: {target}")
    print(
        f"Preview command: python {ROOT_DIR / 'build.py'} --input {build_file} "
        f"--output {target / 'build'} --preview --watch"
    )
    return 0


def list_components(
    query: str = "", plugin_paths: Sequence[str | Path] | None = None
) -> int:
    """Print a searchable core + plugin component catalogue."""
    try:
        library, plugin_infos = load_library_with_plugins(plugin_paths)
    except ConfigurationError as exc:
        print(exc, file=sys.stderr)
        return 1
    components = library.get("components", {})
    query_lower = query.casefold().strip()
    matches = 0
    for name, definition in components.items():
        description = str(definition.get("description", ""))
        variants = ", ".join(definition.get("variants", {}).keys())
        haystack = f"{name} {description} {variants}".casefold()
        if query_lower and query_lower not in haystack:
            continue
        print(f"{name:<22} [{variants}]")
        if description:
            print(f"  {description}")
        matches += 1
    plugin_names = ", ".join(info.name for info in plugin_infos) or "none"
    print(f"\n{matches} component(s) — core: {DEFAULT_LIBRARY_PATH}")
    print(f"Plugins: {plugin_names}")
    return 0 if matches else 1


def show_component(
    type_name: str, plugin_paths: Sequence[str | Path] | None = None
) -> int:
    """Show a core or namespaced plugin component and a copyable instance."""
    try:
        library, _ = load_library_with_plugins(plugin_paths)
    except ConfigurationError as exc:
        print(exc, file=sys.stderr)
        return 1
    definition = library.get("components", {}).get(type_name)
    if not isinstance(definition, dict):
        print(f"Unknown component: {type_name!r}", file=sys.stderr)
        return 1
    variants = list(definition.get("variants", {}).keys())
    default_variant = definition.get("default_variant") or variants[0]
    required = definition.get("required", [])
    content: dict[str, Any] = {}
    list_like_fields = {
        "items",
        "lines",
        "options",
        "headers",
        "rows",
        "features",
        "slides",
        "images",
        "members",
        "pages",
        "columns",
    }
    for path in required:
        if isinstance(path, str) and path.startswith("content."):
            field_name = path.split(".", 1)[1]
            content[field_name] = [] if field_name in list_like_fields else "Required value"
    example = {
        "type": type_name,
        "variant": default_variant,
        "content": content,
    }
    print(f"{type_name}: {definition.get('description', '')}")
    print(f"Variants: {', '.join(variants)}")
    print(f"Required: {', '.join(required) if required else 'none'}")
    print("\nReady-to-copy instance:\n")
    print(json.dumps(example, ensure_ascii=False, indent=2))
    return 0


def create_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="WeBuilder",
        description=(
            "Build and preview a modular website with a core library "
            f"({DEFAULT_LIBRARY_PATH}) and optional namespaced plugins."
        ),
    )
    parser.add_argument(
        "--input",
        default="build.json",
        help="path to build.json (default: build.json)",
    )
    parser.add_argument(
        "--output",
        default="./build",
        help="output directory (default: ./build)",
    )
    parser.add_argument(
        "--plugin",
        action="append",
        nargs="+",
        default=[],
        metavar="PLUGIN_JSON",
        help=(
            "load one or more plugin libraries; the option may be repeated. "
            "The filename becomes the namespace"
        ),
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="rebuild after changes to build.json, source assets, the core library, or plugins",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="start the integrated preview server in this terminal",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="preview server address (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="preview port; 0 selects a free port (default: 8000)",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="do not open the browser automatically with --preview",
    )
    parser.add_argument(
        "--init",
        metavar="DIRECTORY",
        help="create a new project without copying library.json",
    )
    parser.add_argument(
        "--list-components",
        nargs="?",
        const="",
        metavar="QUERY",
        help="list components, with an optional search query",
    )
    parser.add_argument(
        "--show-component",
        metavar="TYPE",
        help="show variants and a copy-ready JSON instance",
    )
    parser.add_argument("--version", action="version", version=f"WeBuilder {VERSION}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = create_argument_parser().parse_args(argv)
    plugin_paths = [path for group in args.plugin for path in group]
    if args.port < 0 or args.port > 65535:
        print("--port must be between 0 and 65535", file=sys.stderr)
        return 2
    if args.init:
        return initialise_project(args.init)
    if args.list_components is not None:
        return list_components(args.list_components, plugin_paths)
    if args.show_component:
        return show_component(args.show_component, plugin_paths)
    if args.preview:
        return preview_site(
            args.input,
            args.output,
            plugin_paths=plugin_paths,
            watch=args.watch,
            host=args.host,
            port=args.port,
            open_browser=not args.no_open,
        )
    if args.watch:
        return watch_build(args.input, args.output, plugin_paths)
    return (
        0
        if build_site(args.input, args.output, plugin_paths=plugin_paths)
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
