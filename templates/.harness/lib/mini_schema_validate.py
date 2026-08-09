#!/usr/bin/env python3
"""Minimal JSON Schema validator (subset), pure stdlib.

Why (M2/H4, adversarial audit): `validate_contract.py` only ran
`json.loads()` on the schemas — it never validated an example INSTANCE
against them. Real proof from the audit: changing the `then` block of a
schema to an innocuous rule (e.g. requiring a property that is already
`required` in the root `type`, making the `if/then` practically ineffective)
kept `validate_contract.py` exiting 0 — the only test that touched the
subject (`test_json_schemas_parse_and_enforce_conditional_payloads`) merely
checked that the strings "then"/"fix_request" appeared somewhere in the
serialized JSON, never that the `then` actually REJECTS an instance that
violates it.

Library decision (declared, LEI ZERO §9.1 cost delta):
`engine/contract/README.md` line 5 is explicit — "pure stdlib (zero
external dependency)" is the DECLARED architecture of this package (and of
the whole framework: there is no `pyproject.toml`/`requirements.txt`
anywhere in the repo — every script runs with a bare `python3 script.py`,
in the target project installed via Copier, with no package manager).
Adopting `jsonschema` (even just "if available, else fallback") would make
the gate's behavior DEPENDENT on the environment where it runs — the same
target project would validate differently with/without the package
installed, the opposite of what "self-contained" promises. That is why the
choice here is: ALWAYS this minimal validator, never optional `jsonschema`.
It covers exactly the subset of JSON Schema (draft 2020-12) used by the 3
schemas of this package: `type`, `additionalProperties`, `required`,
`properties.*` (`type`, `enum`, `minimum`, `minLength`, `pattern`, `items`),
and `allOf` of `if`/`then` blocks (with `if.properties.*.const` +
`if.required` and `then.required`/`then.properties.*.minItems`). It is not a
generic JSON Schema validator — it does not implement `$ref`, `oneOf`,
`patternProperties` etc., because no schema in this package uses those
features; if a new schema needs something outside this subset, this module
needs to grow (or the decision to adopt a real lib needs to be revisited
with new data).
"""

from __future__ import annotations

import re
from typing import Any


class SchemaValidationError(Exception):
    """One or more schema violations. `.errors` holds the full list."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def _type_ok(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    return True  # type not covered by the subset -- does not block


def _validate_property(path: str, value: Any, subschema: dict, errors: list[str]) -> None:
    expected_type = subschema.get("type")
    if expected_type and not _type_ok(value, expected_type):
        errors.append(f"{path}: expected type={expected_type}, got {type(value).__name__}")
        return

    if "enum" in subschema and value not in subschema["enum"]:
        errors.append(f"{path}: value {value!r} outside enum {subschema['enum']}")

    if "const" in subschema and value != subschema["const"]:
        errors.append(f"{path}: value {value!r} must equal const {subschema['const']!r}")

    if "minimum" in subschema and isinstance(value, (int, float)) and value < subschema["minimum"]:
        errors.append(f"{path}: {value} < minimum {subschema['minimum']}")

    if "minLength" in subschema and isinstance(value, str) and len(value) < subschema["minLength"]:
        errors.append(f"{path}: string shorter than minLength {subschema['minLength']}")

    if "pattern" in subschema and isinstance(value, str):
        if not re.search(subschema["pattern"], value):
            errors.append(f"{path}: {value!r} does not match pattern {subschema['pattern']!r}")

    if expected_type == "array" and "items" in subschema and isinstance(value, list):
        item_schema = subschema["items"]
        for i, item in enumerate(value):
            if item_schema.get("type") == "object":
                _validate_object(f"{path}[{i}]", item, item_schema, errors)
            else:
                _validate_property(f"{path}[{i}]", item, item_schema, errors)

    if "minItems" in subschema and isinstance(value, list) and len(value) < subschema["minItems"]:
        errors.append(f"{path}: array shorter than minItems {subschema['minItems']}")


def _validate_object(path: str, instance: Any, schema: dict, errors: list[str]) -> None:
    if schema.get("type") == "object" and not isinstance(instance, dict):
        errors.append(f"{path}: expected object, got {type(instance).__name__}")
        return

    if isinstance(instance, dict):
        for required_key in schema.get("required", []):
            if required_key not in instance:
                errors.append(f"{path}: missing required property '{required_key}'")

        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in instance:
                if key not in properties:
                    errors.append(f"{path}: property '{key}' not declared (additionalProperties=false)")

        for key, value in instance.items():
            if key in properties:
                _validate_property(f"{path}.{key}", value, properties[key], errors)


def _if_condition_matches(instance: dict, if_clause: dict) -> bool:
    for required_key in if_clause.get("required", []):
        if required_key not in instance:
            return False
    for key, subschema in if_clause.get("properties", {}).items():
        if key not in instance:
            return False
        if "const" in subschema and instance[key] != subschema["const"]:
            return False
    return True


def validate_instance(instance: Any, schema: dict) -> list[str]:
    """Validate `instance` against `schema` (subset documented in the module).

    Returns a list of errors (empty = valid). Never raises -- the caller
    decides what to do (raise SchemaValidationError, count, etc.).
    """
    errors: list[str] = []
    _validate_object("$", instance, schema, errors)

    if isinstance(instance, dict):
        for clause in schema.get("allOf", []):
            if_clause = clause.get("if", {})
            then_clause = clause.get("then", {})
            if _if_condition_matches(instance, if_clause):
                _validate_object("$ (allOf/then)", instance, then_clause, errors)

    return errors


def assert_valid(instance: Any, schema: dict, label: str) -> None:
    errors = validate_instance(instance, schema)
    if errors:
        raise SchemaValidationError([f"{label}: {e}" for e in errors])


def assert_invalid(instance: Any, schema: dict, label: str) -> None:
    """Negative control: the instance MUST fail. If it passes, it is the
    schema (or the validator) that lost enforcement power -- raises an error."""
    errors = validate_instance(instance, schema)
    if not errors:
        raise SchemaValidationError(
            [f"{label}: INVALID instance passed validation -- schema/allOf/if/then with no real effect"]
        )
