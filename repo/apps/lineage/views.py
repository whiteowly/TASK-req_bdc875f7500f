"""Lineage edges and graph traversal."""
from __future__ import annotations

from datetime import datetime

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.catalog.models import Dataset
from apps.platform_common.audit import write_audit
from apps.platform_common.errors import NotFound, ValidationFailure
from apps.platform_common.permissions import require_capability

from .models import LineageEdge


def _edge_repr(e: LineageEdge):
    return {
        "id": e.id,
        "upstream_dataset_id": e.upstream_dataset_id,
        "downstream_dataset_id": e.downstream_dataset_id,
        "relation_type": e.relation_type,
        "observed_at": e.observed_at.isoformat(),
        "recorded_at": e.recorded_at.isoformat(),
    }


@api_view(["GET", "POST"])
def edges(request):
    require_capability(request, "lineage:read")
    if request.method == "GET":
        qs = LineageEdge.objects.all().order_by("-recorded_at")[:200]
        return Response({"edges": [_edge_repr(e) for e in qs]})

    require_capability(request, "lineage:write")
    payload = request.data or {}
    up = payload.get("upstream_dataset_id")
    down = payload.get("downstream_dataset_id")
    rel = (payload.get("relation_type") or "").strip()
    obs = payload.get("observed_at")
    if not (up and down and rel and obs):
        raise ValidationFailure(
            "upstream_dataset_id, downstream_dataset_id, relation_type, observed_at all required"
        )
    if rel not in LineageEdge.RELATIONS:
        raise ValidationFailure("invalid relation_type",
                                details={"allowed": list(LineageEdge.RELATIONS)})
    try:
        observed_at = datetime.fromisoformat(obs.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise ValidationFailure("observed_at must be ISO-8601") from exc

    try:
        ups = Dataset.objects.get(id=up)
        downs = Dataset.objects.get(id=down)
    except Dataset.DoesNotExist as exc:
        raise NotFound("upstream or downstream dataset not found") from exc

    edge = LineageEdge.objects.create(
        upstream_dataset=ups,
        downstream_dataset=downs,
        relation_type=rel,
        observed_at=observed_at,
    )
    write_audit(
        actor=request.actor,
        action="lineage.add_edge",
        object_type="lineage_edge",
        object_id=edge.id,
        request=request,
        payload_after={"upstream": up, "downstream": down, "relation_type": rel},
    )
    return Response(_edge_repr(edge), status=status.HTTP_201_CREATED)


@api_view(["GET"])
def graph(request):
    require_capability(request, "lineage:read")
    dataset_id = request.query_params.get("dataset_id")
    direction = (request.query_params.get("direction") or "downstream").lower()
    try:
        depth = int(request.query_params.get("depth") or 3)
    except ValueError as exc:
        raise ValidationFailure("depth must be integer") from exc
    if not dataset_id:
        raise ValidationFailure("dataset_id query parameter required")
    if direction not in ("upstream", "downstream"):
        raise ValidationFailure("direction must be 'upstream' or 'downstream'")
    if depth < 1 or depth > 10:
        raise ValidationFailure("depth must be between 1 and 10")
    if not Dataset.objects.filter(id=dataset_id).exists():
        raise NotFound("Dataset not found")

    visited = set()
    edges_out = []
    nodes = {dataset_id}
    frontier = {dataset_id}
    for _ in range(depth):
        if not frontier:
            break
        if direction == "downstream":
            next_edges = LineageEdge.objects.filter(upstream_dataset_id__in=frontier)
        else:
            next_edges = LineageEdge.objects.filter(downstream_dataset_id__in=frontier)
        new_frontier = set()
        for e in next_edges:
            if e.id in visited:
                continue
            visited.add(e.id)
            edges_out.append(_edge_repr(e))
            target = e.downstream_dataset_id if direction == "downstream" else e.upstream_dataset_id
            if target not in nodes:
                nodes.add(target)
                new_frontier.add(target)
        frontier = new_frontier
    return Response({"nodes": sorted(nodes), "edges": edges_out, "direction": direction, "depth": depth})
