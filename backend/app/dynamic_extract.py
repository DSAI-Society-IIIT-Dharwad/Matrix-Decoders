from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .logger import get_logger
from .ollama_client import OllamaClient
from .transcript_cleaner import clean_transcript

log = get_logger("dynamic_extract")

_ALLOWED_TYPES = {"object", "array", "string", "number", "integer", "boolean"}

_DYNAMIC_EXTRACT_SYSTEM_PROMPT = """\
You are an information extraction engine.
Extract fields from clinical text into JSON using the provided JSON schema.

Hard rules:
- Output only a single JSON object.
- Do not include markdown, comments, or explanations.
- Never invent facts that are not in the source text.
- If a value is missing, use empty values compatible with schema types.
- Keep extracted values in the same language as source text.
"""


@dataclass
class DynamicExtractResult:
    result: dict[str, Any] = field(default_factory=dict)
    normalized_schema: dict[str, Any] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    used_llm: bool = False
    fallback_used: bool = False
    raw_response: str = ""


def normalize_dynamic_schema(schema: Any) -> tuple[dict[str, Any], list[str]]:
    issues: list[str] = []
    normalized: dict[str, Any] = {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    }

    if not isinstance(schema, dict):
        issues.append("Schema is not an object; using empty object schema.")
        return normalized, issues

    if schema.get("type") not in {None, "object"}:
        issues.append("Root schema type must be object; forcing object schema.")

    raw_properties = schema.get("properties", {})
    if not isinstance(raw_properties, dict):
        issues.append("Schema properties must be an object; using empty properties.")
        raw_properties = {}

    properties: dict[str, Any] = {}
    for key, value in raw_properties.items():
        field_name = str(key)
        properties[field_name] = _normalize_field_schema(value, issues, path=field_name)

    required = schema.get("required", [])
    if isinstance(required, list):
        normalized_required = [str(name) for name in required if str(name) in properties]
    else:
        issues.append("Schema required must be a list; ignoring invalid value.")
        normalized_required = []

    normalized.update(
        {
            "properties": properties,
            "required": normalized_required,
            "additionalProperties": bool(schema.get("additionalProperties", False)),
        }
    )
    return normalized, issues


def _normalize_field_schema(schema: Any, issues: list[str], path: str) -> dict[str, Any]:
    if not isinstance(schema, dict):
        issues.append(f"{path}: field schema must be an object; defaulting to string.")
        return {"type": "string"}

    raw_type = schema.get("type", "string")
    nullable = False

    if isinstance(raw_type, list):
        candidate_types = [str(value) for value in raw_type if str(value) in _ALLOWED_TYPES | {"null"}]
        nullable = "null" in candidate_types
        base_type = next((value for value in candidate_types if value != "null"), "string")
    else:
        raw_type_str = str(raw_type)
        if raw_type_str in _ALLOWED_TYPES:
            base_type = raw_type_str
        else:
            issues.append(f"{path}: unsupported type '{raw_type_str}', defaulting to string.")
            base_type = "string"

    normalized: dict[str, Any] = {"type": base_type}
    if nullable:
        normalized["nullable"] = True

    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and enum_values:
        normalized["enum"] = list(enum_values)

    if base_type == "object":
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            issues.append(f"{path}: object field properties must be an object; using empty object.")
            properties = {}
        normalized["properties"] = {
            str(name): _normalize_field_schema(value, issues, path=f"{path}.{name}")
            for name, value in properties.items()
        }
        required = schema.get("required", [])
        if isinstance(required, list):
            normalized["required"] = [str(name) for name in required if str(name) in normalized["properties"]]
        else:
            normalized["required"] = []
            issues.append(f"{path}: object field required must be a list; ignoring invalid value.")
        normalized["additionalProperties"] = bool(schema.get("additionalProperties", False))
    elif base_type == "array":
        normalized["items"] = _normalize_field_schema(
            schema.get("items", {"type": "string"}),
            issues,
            path=f"{path}[]",
        )

    return normalized


def _default_for_schema(schema: dict[str, Any]) -> Any:
    value_type = schema.get("type", "string")
    if value_type == "object":
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            return {}
        return {str(name): _default_for_schema(value) for name, value in properties.items()}
    if value_type == "array":
        return []
    if value_type == "integer":
        return 0
    if value_type == "number":
        return 0.0
    if value_type == "boolean":
        return False
    return ""


def _coerce_to_schema(value: Any, schema: dict[str, Any], path: str, issues: list[str]) -> Any:
    value_type = schema.get("type", "string")
    enum_values = schema.get("enum")

    if value is None:
        coerced = _default_for_schema(schema)
    elif value_type == "object":
        coerced = _coerce_object(value, schema, path, issues)
    elif value_type == "array":
        coerced = _coerce_array(value, schema, path, issues)
    elif value_type == "integer":
        coerced = _coerce_integer(value, path, issues)
    elif value_type == "number":
        coerced = _coerce_number(value, path, issues)
    elif value_type == "boolean":
        coerced = _coerce_boolean(value, path, issues)
    else:
        coerced = clean_transcript(str(value))

    if isinstance(enum_values, list) and enum_values:
        if coerced not in enum_values:
            issues.append(f"{path}: value '{coerced}' not in enum; using '{enum_values[0]}'.")
            coerced = enum_values[0]

    return coerced


def _coerce_object(value: Any, schema: dict[str, Any], path: str, issues: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        issues.append(f"{path}: expected object, using defaults.")
        value = {}

    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return {}

    output: dict[str, Any] = {}
    required = set(schema.get("required", [])) if isinstance(schema.get("required", []), list) else set()

    for key, child_schema in properties.items():
        child_path = f"{path}.{key}" if path else key
        if key in value:
            output[key] = _coerce_to_schema(value.get(key), child_schema, child_path, issues)
        else:
            if key in required:
                issues.append(f"{child_path}: missing required field, using default value.")
            output[key] = _default_for_schema(child_schema)

    if schema.get("additionalProperties") and isinstance(value, dict):
        for key, raw_value in value.items():
            if key not in output:
                output[str(key)] = raw_value

    return output


def _coerce_array(value: Any, schema: dict[str, Any], path: str, issues: list[str]) -> list[Any]:
    items_schema = schema.get("items", {"type": "string"})
    if isinstance(value, list):
        items = value
    elif isinstance(value, str):
        tokens = [part.strip() for part in re.split(r"[,;\n]+", value) if part.strip()]
        items = tokens or ([value.strip()] if value.strip() else [])
    else:
        items = [value]

    output: list[Any] = []
    for index, item in enumerate(items):
        output.append(_coerce_to_schema(item, items_schema, f"{path}[{index}]", issues))
    return output


def _coerce_integer(value: Any, path: str, issues: list[str]) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(round(value))
    if isinstance(value, str):
        cleaned = clean_transcript(value)
        if not cleaned:
            return 0
        try:
            return int(float(cleaned))
        except ValueError:
            issues.append(f"{path}: could not coerce '{cleaned}' to integer; using 0.")
            return 0
    issues.append(f"{path}: unsupported integer value type; using 0.")
    return 0


def _coerce_number(value: Any, path: str, issues: list[str]) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = clean_transcript(value)
        if not cleaned:
            return 0.0
        try:
            return float(cleaned)
        except ValueError:
            issues.append(f"{path}: could not coerce '{cleaned}' to number; using 0.")
            return 0.0
    issues.append(f"{path}: unsupported number value type; using 0.")
    return 0.0


def _coerce_boolean(value: Any, path: str, issues: list[str]) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        cleaned = clean_transcript(value).lower()
        if cleaned in {"true", "yes", "y", "1", "present"}:
            return True
        if cleaned in {"false", "no", "n", "0", "absent"}:
            return False
    issues.append(f"{path}: could not coerce value to boolean; using false.")
    return False


def _extract_json_object(raw_text: str) -> dict[str, Any] | None:
    text = raw_text.strip()
    if not text:
        return None

    candidates: list[str] = []
    for match in re.finditer(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text, flags=re.IGNORECASE):
        candidates.append(match.group(1).strip())
    candidates.append(text)
    object_slice = _slice_first_json_object(text)
    if object_slice:
        candidates.append(object_slice)

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _slice_first_json_object(text: str) -> str:
    start = text.find("{")
    if start < 0:
        return ""

    depth = 0
    in_string = False
    escaped = False
    end = -1

    for index in range(start, len(text)):
        char = text[index]

        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            continue

        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = index + 1
                break

    if end > start:
        return text[start:end]
    return ""


def _fallback_extract_from_text(text: str, schema: dict[str, Any]) -> dict[str, Any]:
    return _fallback_extract_object(text, schema, path="")


def _fallback_extract_object(text: str, schema: dict[str, Any], path: str) -> dict[str, Any]:
    output = _default_for_schema(schema)
    properties = schema.get("properties", {})
    if not isinstance(output, dict) or not isinstance(properties, dict):
        return {}

    for field_name, field_schema in properties.items():
        field_path = f"{path}.{field_name}" if path else field_name
        field_type = field_schema.get("type", "string")

        if field_type == "object":
            output[field_name] = _fallback_extract_object(text, field_schema, path=field_path)
            continue

        line_value = _match_field_value(text, field_name)
        if line_value is None:
            continue

        if field_type == "array":
            raw_items = [part.strip() for part in re.split(r"[,;\n]+", line_value) if part.strip()]
            output[field_name] = [_coerce_to_schema(item, field_schema.get("items", {"type": "string"}), field_path, []) for item in raw_items]
        else:
            output[field_name] = _coerce_to_schema(line_value, field_schema, field_path, [])

    return output


def _match_field_value(text: str, field_name: str) -> str | None:
    aliases = [
        field_name,
        field_name.replace("_", " "),
        field_name.replace("_", "-"),
    ]
    for alias in aliases:
        pattern = (
            rf"(?:^|\n|\s){re.escape(alias)}\s*[:=-]\s*"
            r"(.+?)(?=(?:\s+[A-Za-z_][A-Za-z0-9_\- ]{1,40}\s*[:=-])|$)"
        )
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return clean_transcript(match.group(1))
    return None


def _build_extraction_messages(text: str, schema: dict[str, Any], context: str = "") -> list[dict[str, str]]:
    prompt = (
        "Schema:\n"
        f"{json.dumps(schema, ensure_ascii=False, indent=2)}\n\n"
        "Source text:\n"
        f"{text}\n"
    )
    if context:
        prompt = f"{prompt}\nContext:\n{context}\n"
    return [
        {"role": "system", "content": _DYNAMIC_EXTRACT_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]


async def extract_dynamic_json(
    text: str,
    schema: Any,
    context: str = "",
    *,
    client: OllamaClient | None = None,
) -> DynamicExtractResult:
    normalized_schema, issues = normalize_dynamic_schema(schema)
    cleaned_text = clean_transcript(text)
    if not cleaned_text:
        issues.append("Input text is empty; returning schema defaults.")
        return DynamicExtractResult(
            result=_default_for_schema(normalized_schema),
            normalized_schema=normalized_schema,
            issues=issues,
            used_llm=False,
            fallback_used=True,
            raw_response="",
        )

    active_client = client or OllamaClient()
    llm_output = ""
    extracted_payload: dict[str, Any] | None = None
    used_llm = False

    try:
        chunks: list[str] = []
        async for chunk in active_client.stream(_build_extraction_messages(cleaned_text, normalized_schema, context=context)):
            chunks.append(chunk)
        llm_output = "".join(chunks).strip()

        if llm_output and not llm_output.startswith("[ERROR]"):
            extracted_payload = _extract_json_object(llm_output)
            if extracted_payload is None:
                issues.append("LLM response was not valid JSON object; using fallback extraction.")
            else:
                used_llm = True
        elif llm_output.startswith("[ERROR]"):
            issues.append(llm_output)
    except Exception as exc:
        log.warning(f"Dynamic extraction LLM request failed: {exc}")
        issues.append(f"Dynamic extraction LLM request failed: {exc}")

    fallback_used = False
    if extracted_payload is None:
        fallback_used = True
        extracted_payload = _fallback_extract_from_text(cleaned_text, normalized_schema)

    coerced = _coerce_to_schema(extracted_payload, normalized_schema, "root", issues)
    if not isinstance(coerced, dict):
        issues.append("Normalized extraction output was not an object; returning defaults.")
        coerced = _default_for_schema(normalized_schema)

    return DynamicExtractResult(
        result=coerced,
        normalized_schema=normalized_schema,
        issues=issues,
        used_llm=used_llm,
        fallback_used=fallback_used,
        raw_response=llm_output,
    )
