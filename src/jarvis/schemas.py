"""Bound untrusted MCP schema validation; never retrieve files or remote refs."""

from __future__ import annotations

import asyncio
import json
import time

import jsonschema
import regex
from referencing import Registry


def bounded_tree(value, *, maximum_bytes, schema=False):
    if len(json.dumps(value).encode()) > maximum_bytes:
        raise ValueError("MCP validation input exceeds its size limit.")
    pending = [(value, 0)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > 2000 or depth > 25:
            raise ValueError("MCP validation input is too complex.")
        if isinstance(item, dict):
            if schema and ("patternProperties" in item or "unevaluatedProperties" in item):
                raise ValueError("This MCP schema feature is outside the bounded local validator.")
            if schema and isinstance(item.get("pattern"), str) and len(item["pattern"]) > 256:
                raise ValueError("MCP schema pattern exceeds its size limit.")
            pending.extend((v, depth + 1) for v in item.values())
        elif isinstance(item, list):
            pending.extend((v, depth + 1) for v in item)


def validate(schema, arguments):
    bounded_tree(schema, maximum_bytes=64000, schema=True)
    bounded_tree(arguments, maximum_bytes=32000)
    deadline = time.monotonic() + 1

    def pattern(validator, expression, instance, current):
        if validator.is_type(instance, "string") and not regex.search(
            expression, instance, timeout=0.02
        ):
            yield jsonschema.ValidationError("A value does not match its required pattern.")

    def timed(function):
        def check(*args):
            if time.monotonic() > deadline:
                raise TimeoutError("MCP validation exceeded its budget.")
            yield from function(*args)

        return check

    try:
        base = jsonschema.validators.validator_for(schema)
        base.check_schema(schema)
        rules = {**base.VALIDATORS, "pattern": pattern}
        validator = jsonschema.validators.extend(
            base, validators={k: timed(v) for k, v in rules.items()}
        )
        # Registry has no retrieval callback: only in-memory/local-fragment refs work.
        validator(schema, registry=Registry()).validate(arguments)
    except Exception:
        raise ValueError(
            "MCP arguments or schema failed bounded validation. External references are disabled."
        ) from None


async def validate_arguments(schema, arguments):
    async with asyncio.timeout(2):
        await asyncio.to_thread(validate, schema, arguments)
