"""Governed dataset query and report execution.

The query API enforces an allowlisted filter grammar — there is **no** raw SQL
acceptance path. All filtering happens in-process against persisted dataset
rows so we can apply per-dataset field allowlists.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from apps.catalog.models import Dataset, DatasetField, DatasetRow
from apps.platform_common.errors import (
    DomainRuleViolation,
    Forbidden,
    ValidationFailure,
)


ALLOWED_OPS = {"eq", "neq", "lt", "lte", "gt", "gte", "in", "not_in", "contains"}
MAX_FILTERS = 20
MAX_SORTS = 3
MAX_LIMIT = 5000
DEFAULT_LIMIT = 500
SQL_KEYWORD_RE = re.compile(
    r"\b(select|insert|update|delete|drop|union|alter|truncate|where|--|/\*)\b",
    re.IGNORECASE,
)


def _sql_like(value: Any) -> bool:
    if isinstance(value, str) and SQL_KEYWORD_RE.search(value):
        return True
    return False


def _coerce(field: DatasetField, value: Any) -> Any:
    try:
        if field.data_type == "integer":
            return int(value)
        if field.data_type == "decimal":
            return float(value)
        if field.data_type == "boolean":
            return bool(value)
    except (TypeError, ValueError) as exc:
        raise ValidationFailure(
            f"value for {field.field_key} cannot be coerced to {field.data_type}"
        ) from exc
    return value


def _matches(row: dict, field: DatasetField, op: str, value: Any) -> bool:
    cell = row.get(field.field_key)
    if cell is None:
        return False
    try:
        if op == "eq":
            return cell == value
        if op == "neq":
            return cell != value
        if op == "lt":
            return cell < value
        if op == "lte":
            return cell <= value
        if op == "gt":
            return cell > value
        if op == "gte":
            return cell >= value
        if op == "in":
            return cell in (value or [])
        if op == "not_in":
            return cell not in (value or [])
        if op == "contains":
            return isinstance(cell, str) and isinstance(value, str) and value in cell
    except TypeError:
        return False
    return False


def execute_query(*, dataset: Dataset, payload: Dict[str, Any], allow_unapproved: bool = False) -> Dict[str, Any]:
    if dataset.approval_state != "approved" and not allow_unapproved:
        raise Forbidden("dataset must be approved to query")

    select = payload.get("select") or []
    filters = payload.get("filters") or []
    sort = payload.get("sort") or []
    limit = payload.get("limit", DEFAULT_LIMIT)
    if not isinstance(limit, int) or limit < 1 or limit > MAX_LIMIT:
        raise ValidationFailure(
            f"limit must be 1..{MAX_LIMIT}", details={"received": limit}
        )
    if len(filters) > MAX_FILTERS:
        raise DomainRuleViolation(
            f"max {MAX_FILTERS} filter clauses allowed",
            code="too_many_filters",
        )
    if len(sort) > MAX_SORTS:
        raise DomainRuleViolation(
            f"max {MAX_SORTS} sort fields allowed", code="too_many_sorts"
        )

    field_qs = list(dataset.fields.all())
    field_by_key = {f.field_key: f for f in field_qs}
    queryable = {k for k, f in field_by_key.items() if f.is_queryable}

    if select and not isinstance(select, list):
        raise ValidationFailure("select must be a list of field keys")
    for s in select:
        if s not in field_by_key:
            raise ValidationFailure(f"unknown field {s}", code="unknown_field")
    project = list(select) if select else list(queryable)

    parsed_filters: List[Tuple[DatasetField, str, Any]] = []
    for f in filters:
        if not isinstance(f, dict):
            raise ValidationFailure("filter must be an object")
        field_key = f.get("field")
        op = f.get("op")
        value = f.get("value")
        if op not in ALLOWED_OPS:
            raise ValidationFailure("invalid filter op",
                                    code="invalid_filter_op",
                                    details={"allowed": sorted(ALLOWED_OPS)})
        if field_key not in field_by_key:
            raise ValidationFailure(f"unknown field {field_key}", code="unknown_field")
        if field_key not in queryable:
            raise Forbidden(f"field {field_key} is not queryable")
        if _sql_like(value):
            raise ValidationFailure(
                "filter value rejected (sql-like content)",
                code="sql_like_rejected",
            )
        if isinstance(value, list):
            value = [_coerce(field_by_key[field_key], v) for v in value]
        else:
            value = _coerce(field_by_key[field_key], value)
        parsed_filters.append((field_by_key[field_key], op, value))

    parsed_sort: List[Tuple[str, bool]] = []
    for s in sort:
        if not isinstance(s, dict):
            raise ValidationFailure("sort entry must be an object")
        f_key = s.get("field")
        direction = (s.get("direction") or "asc").lower()
        if f_key not in field_by_key:
            raise ValidationFailure(f"unknown sort field {f_key}", code="unknown_field")
        if f_key not in queryable:
            raise Forbidden(f"sort field {f_key} is not queryable")
        if direction not in ("asc", "desc"):
            raise ValidationFailure("sort direction must be asc|desc")
        parsed_sort.append((f_key, direction == "desc"))

    rows = [r.payload for r in DatasetRow.objects.filter(dataset=dataset)]
    matched = []
    for r in rows:
        if all(_matches(r, fld, op, val) for (fld, op, val) in parsed_filters):
            matched.append(r)
    for f_key, desc in reversed(parsed_sort):
        matched.sort(key=lambda row: (row.get(f_key) is None, row.get(f_key)), reverse=desc)
    matched = matched[:limit]
    out = [{k: r.get(k) for k in project} for r in matched]
    return {
        "rows": out,
        "next_cursor": None,
        "applied_scope": {"dataset_id": dataset.id, "approved_only": True},
        "row_count": len(out),
    }
