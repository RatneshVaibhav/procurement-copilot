"""pydantic → strict JSON schema (D2.1).

Every object gets additionalProperties=false and required = all its properties;
nullable fields stay anyOf [..., {"type": "null"}]; `default` keys are removed;
$defs / $ref are kept.
"""
from __future__ import annotations

import copy

from pydantic import BaseModel


def _strict(node):
    if isinstance(node, dict):
        node.pop("default", None)
        for key, value in list(node.items()):
            node[key] = _strict(value)
        if node.get("type") == "object" or "properties" in node:
            props = node.get("properties", {})
            node["additionalProperties"] = False
            node["required"] = list(props.keys())
        return node
    if isinstance(node, list):
        return [_strict(v) for v in node]
    return node


def strict_schema(model_cls: type[BaseModel]) -> dict:
    return _strict(copy.deepcopy(model_cls.model_json_schema()))
