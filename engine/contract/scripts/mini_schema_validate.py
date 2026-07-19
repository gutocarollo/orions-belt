#!/usr/bin/env python3
"""Validador mínimo de JSON Schema (subset), stdlib puro.

Porque (M2/H4, auditoria adversarial): `validate_contract.py` só fazia
`json.loads()` nos schemas — nunca validava uma INSTÂNCIA de exemplo contra
eles. Prova real da auditoria: mudar o bloco `then` de um schema para uma
regra inócua (ex.: exigir uma propriedade que já é `required` no `type`
raiz, tornando o `if/then` sem efeito prático) mantinha `validate_contract.py`
saindo 0 — o único teste que tocava o assunto
(`test_json_schemas_parse_and_enforce_conditional_payloads`) apenas checava
que as strings "then"/"fix_request" apareciam em algum lugar do JSON
serializado, nunca que o `then` de fato REJEITA uma instância que o viola.

Decisão de biblioteca (declarada, LEI ZERO §9.1 delta de custo):
`engine/contract/README.md` linha 5 é explícito — "stdlib puro (zero
dependência externa)" é a arquitetura DECLARADA deste pacote (e do
framework inteiro: não há `pyproject.toml`/`requirements.txt` em lugar
nenhum do repo — todo script roda com `python3 script.py` cru, no
projeto-alvo instalado via Copier, sem gerenciador de pacotes). Adotar
`jsonschema` (mesmo só "se disponível, senão fallback") tornaria o
comportamento do gate DEPENDENTE do ambiente onde ele roda — o mesmo
projeto-alvo validaria diferente com/sem o pacote instalado, o oposto do
que "self-contained" promete. Por isso a escolha aqui é: SEMPRE este
validador mínimo, nunca `jsonschema` opcional. Cobre exatamente o subset de
JSON Schema (draft 2020-12) usado pelos 3 schemas deste pacote: `type`,
`additionalProperties`, `required`, `properties.*` (`type`, `enum`,
`minimum`, `minLength`, `pattern`, `items`), e `allOf` de blocos
`if`/`then` (com `if.properties.*.const` + `if.required` e
`then.required`/`then.properties.*.minItems`). Não é um validador de JSON
Schema genérico — não implementa `$ref`, `oneOf`, `patternProperties` etc.,
porque nenhum schema deste pacote usa essas features; se um schema novo
precisar de algo fora deste subset, este módulo precisa crescer (ou a
decisão de adotar uma lib real precisa ser revisitada com dado novo).
"""

from __future__ import annotations

import re
from typing import Any


class SchemaValidationError(Exception):
    """Uma ou mais violações de schema. `.errors` tem a lista completa."""

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
    return True  # tipo não coberto pelo subset -- não bloqueia


def _validate_property(path: str, value: Any, subschema: dict, errors: list[str]) -> None:
    expected_type = subschema.get("type")
    if expected_type and not _type_ok(value, expected_type):
        errors.append(f"{path}: esperado type={expected_type}, veio {type(value).__name__}")
        return

    if "enum" in subschema and value not in subschema["enum"]:
        errors.append(f"{path}: valor {value!r} fora do enum {subschema['enum']}")

    if "minimum" in subschema and isinstance(value, (int, float)) and value < subschema["minimum"]:
        errors.append(f"{path}: {value} < minimum {subschema['minimum']}")

    if "minLength" in subschema and isinstance(value, str) and len(value) < subschema["minLength"]:
        errors.append(f"{path}: string mais curta que minLength {subschema['minLength']}")

    if "pattern" in subschema and isinstance(value, str):
        if not re.search(subschema["pattern"], value):
            errors.append(f"{path}: {value!r} não casa pattern {subschema['pattern']!r}")

    if expected_type == "array" and "items" in subschema and isinstance(value, list):
        item_schema = subschema["items"]
        for i, item in enumerate(value):
            _validate_object(f"{path}[{i}]", item, item_schema, errors)


def _validate_object(path: str, instance: Any, schema: dict, errors: list[str]) -> None:
    if schema.get("type") == "object" and not isinstance(instance, dict):
        errors.append(f"{path}: esperado objeto, veio {type(instance).__name__}")
        return

    if isinstance(instance, dict):
        for required_key in schema.get("required", []):
            if required_key not in instance:
                errors.append(f"{path}: falta propriedade obrigatória '{required_key}'")

        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in instance:
                if key not in properties:
                    errors.append(f"{path}: propriedade '{key}' não declarada (additionalProperties=false)")

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
    """Valida `instance` contra `schema` (subset documentado no módulo).

    Retorna lista de erros (vazia = válido). Nunca lança -- quem chama decide
    o que fazer (levantar SchemaValidationError, contar, etc.).
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
    """Controle negativo: a instância DEVE falhar. Se passar, é o schema
    (ou o validador) que perdeu poder de enforcement -- levanta erro."""
    errors = validate_instance(instance, schema)
    if not errors:
        raise SchemaValidationError(
            [f"{label}: instância INVÁLIDA passou na validação -- schema/allOf/if/then sem efeito real"]
        )
