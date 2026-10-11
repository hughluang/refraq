"""Expression sandbox subprocess.

Started as ``python -m backend.channel.sandbox.child``. Reads JSON lines from
stdin and writes JSON lines to stdout. One process is reused for a run.
"""

from __future__ import annotations

import json
import sys
from typing import Any


SAFE_BUILTINS = {
    "len": len,
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "dict": dict,
    "list": list,
    "set": set,
    "tuple": tuple,
    "sorted": sorted,
    "sum": sum,
    "min": min,
    "max": max,
    "any": any,
    "all": all,
    "enumerate": enumerate,
    "zip": zip,
    "range": range,
    "round": round,
    "abs": abs,
    "isinstance": isinstance,
    "None": None,
    "True": True,
    "False": False,
}

_ALLOWED_IMPORTS = frozenset(
    {
        "math",
        "re",
        "json",
        "datetime",
        "decimal",
        "itertools",
        "functools",
        "statistics",
        "collections",
        "string",
    }
)


def _audit(event: str, args: tuple[Any, ...]) -> None:
    if event.startswith("socket.") or event.startswith("subprocess."):
        raise RuntimeError(f"blocked: {event}")
    if event in {"os.system", "os.exec", "os.fork", "os.posix_spawn"}:
        raise RuntimeError(f"blocked: {event}")
    if event.startswith("ctypes."):
        raise RuntimeError(f"blocked: {event}")
    if event == "open" and args and not str(args[0]).startswith("<"):
        mode = args[1] if len(args) > 1 else "r"
        if any(flag in str(mode) for flag in ("w", "a", "x", "+")):
            raise RuntimeError("blocked: open for write")


def _safe_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):  # noqa: A002
    root = name.split(".", 1)[0]
    if root not in _ALLOWED_IMPORTS or level != 0:
        raise ImportError(f"import of {name} is not allowed")
    return __import__(name, globals, locals, fromlist, level)


class Dotted:
    """Dict keys are available as attributes and subscripts. Methods are not."""

    def __init__(self, value: Any) -> None:
        object.__setattr__(self, "_value", value)

    def __getattr__(self, name: str) -> Any:
        value = object.__getattribute__(self, "_value")
        if isinstance(value, dict) and name in value:
            return _wrap(value[name])
        raise AttributeError(f"{name} does not resolve")

    def __getitem__(self, key: Any) -> Any:
        value = object.__getattribute__(self, "_value")
        try:
            return _wrap(value[key])
        except (KeyError, IndexError, TypeError) as exc:
            raise KeyError(f"{key} does not resolve") from exc

    def __iter__(self):
        value = object.__getattribute__(self, "_value")
        return (_wrap(item) for item in value)

    def __len__(self) -> int:
        return len(object.__getattribute__(self, "_value"))

    def __repr__(self) -> str:
        return repr(object.__getattribute__(self, "_value"))


def _wrap(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return Dotted(value)
    return value


def _unwrap(value: Any) -> Any:
    if isinstance(value, Dotted):
        raw = object.__getattribute__(value, "_value")
        if isinstance(raw, dict):
            return {key: _unwrap(item) for key, item in raw.items()}
        return [_unwrap(item) for item in raw]
    if isinstance(value, dict):
        return {key: _unwrap(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_unwrap(item) for item in value]
    return value


class NodeView:
    def __init__(self, output: Any) -> None:
        self.output = _wrap(output)


class NodesMap:
    def __init__(self, nodes: dict[str, NodeView]) -> None:
        self._nodes = nodes

    def __getitem__(self, name: str) -> NodeView:
        for view in self._nodes.values():
            if getattr(view, "name", None) == name:
                return view
        raise KeyError(f"self.nodes[{name!r}] does not resolve")


class SelfProxy:
    def __init__(self) -> None:
        self.channel: Any = Dotted({})
        self.run: Any = Dotted({})
        self.platform: Any = Dotted({})
        self._by_ref: dict[str, NodeView] = {}
        self.nodes = NodesMap(self._by_ref)

    def __getattr__(self, name: str) -> Any:
        if name in self._by_ref:
            return self._by_ref[name]
        raise AttributeError(f"self.{name} does not resolve")


SELF = SelfProxy()


def _put_output(message: dict[str, Any]) -> None:
    ref = str(message["ref"])
    view = NodeView(message.get("output"))
    view.name = message.get("name")  # type: ignore[attr-defined]
    SELF._by_ref[ref] = view


def _eval(expression: str) -> Any:
    compiled = compile(expression, "<expression>", "eval")
    env = {"self": SELF, "__builtins__": {**SAFE_BUILTINS, "__import__": _safe_import}}
    value = eval(compiled, env, {})  # noqa: S307
    return _unwrap(value)


def _handle(message: dict[str, Any]) -> dict[str, Any]:
    kind = message.get("op")
    if kind == "put_context":
        SELF.channel = Dotted(message.get("channel") or {})
        SELF.run = Dotted(message.get("run") or {})
        SELF.platform = Dotted(message.get("platform") or {})
        return {"op": "ok"}
    if kind == "put_output":
        _put_output(message)
        return {"op": "ok"}
    if kind == "eval":
        try:
            value = _eval(str(message.get("expression") or ""))
            json.dumps(value)
            return {"op": "eval", "id": message.get("id"), "ok": True, "value": value}
        except Exception as exc:  # noqa: BLE001
            return {
                "op": "eval",
                "id": message.get("id"),
                "ok": False,
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }


def main() -> None:
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
    except (ImportError, ValueError, OSError):
        pass
    sys.addaudithook(_audit)
    for line in sys.stdin:
        reply = _handle(json.loads(line))
        sys.stdout.write(json.dumps(reply) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
