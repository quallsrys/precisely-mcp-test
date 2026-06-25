"""Shared JSON-Schema normalization for MCP tool inputs.

MCP tool schemas use JSON Schema combinators (oneOf/allOf/anyOf) that several model
SDKs reject at the top level. flatten_combiners() merges the variants into one flat
object schema — the common preprocessing every adapter needs. Gemini requires an extra
strict, recursive pass on top of this (see adapters/gemini.py).
"""


def flatten_combiners(schema: dict) -> dict:
    """Merge top-level oneOf/allOf/anyOf variants into a single object schema."""
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}

    if not any(k in schema for k in ("oneOf", "allOf", "anyOf")):
        return schema

    merged_props: dict = {}
    merged_required: list = []
    for key in ("oneOf", "allOf", "anyOf"):
        for variant in schema.get(key, []):
            merged_props.update(variant.get("properties", {}))
            merged_required.extend(variant.get("required", []))

    flattened = {"type": "object", "properties": merged_props}
    if merged_required:
        flattened["required"] = list(dict.fromkeys(merged_required))
    return flattened
