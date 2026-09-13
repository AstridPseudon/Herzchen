"""Read-only definition and whole-catalog representations."""

from __future__ import annotations

from .common import envelope, stable_digest


AREA_TASKS = {
    "FND": ["FND-03", "FND-04", "FND-05", "FND-06"],
    "DAT": ["DAT-02", "DAT-03", "DAT-04", "DAT-05", "DAT-06"],
    "PKG": ["PKG-02", "PKG-03", "PKG-04", "PKG-05"],
    "WRK": ["WRK-02", "WRK-03", "WRK-04", "WRK-05", "WRK-06", "WRK-07"],
    "EDT": ["EDT-02", "EDT-03", "EDT-04", "EDT-05", "EDT-06"],
    "OTT": ["OTT-01", "OTT-02", "OTT-03", "OTT-04", "OTT-05", "OTT-06"],
    "AST": ["AST-01", "AST-02", "AST-03", "AST-04", "AST-05", "AST-06"],
    "INT": ["INT-02", "INT-03", "INT-04", "INT-05", "INT-06", "INT-07", "INT-08", "INT-09"],
}


def build_definition_catalog() -> dict:
    definition = {
        "definition_id": "int-02-operating-definition",
        "revision": "definition-v1",
        "read_only": True,
        "surfaces": ["describe", "help", "editable_shape", "validation", "query"],
        "managed_fields": ["owner", "state", "acceptance"],
        "extension_namespace": "fixture.int02",
    }
    areas = [
        {
            "area": area,
            "owner": area,
            "tasks": tasks,
            "status": "planned",
            "unknown_fields": {"future_ref": "preserve-me"},
            "conditional_nodes": ["third-specialist" if area == "PKG" else "none"],
            "pending_nodes": ["AST-after-G-OTTO" if area == "AST" else "none"],
        }
        for area, tasks in AREA_TASKS.items()
    ]
    catalog = {
        "catalog_id": "int-02-whole-catalog",
        "catalog_revision": "catalog-v1",
        "read_only": True,
        "owner_areas": areas,
        "preserve_unknown_conditional_pending": True,
        "source_kind": "package-plan-representation",
    }
    return envelope(
        "definition_and_catalog",
        {"definition": definition, "catalog": catalog, "catalog_digest": stable_digest(catalog)},
        "definition-catalog-v1",
    )
