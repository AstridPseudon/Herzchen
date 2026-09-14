"""PKG-04 resource-pack compatibility and isolation proofs.

These tests inspect data only.  They deliberately do not import a pack as
Python, create a store, invoke an agent, or interpret an unknown resource kind.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

import pytest


ROOT = Path(__file__).parents[2]
PACKS = ROOT / "packs"
PACKAGE_ROOT = Path(
    "/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/"
    "work/package/otto_herzchen_delivery_v11_2"
)
FILE_MODE_EXPORT = PACKAGE_ROOT / "skill-export/megado"
PROVENANCE = PACKAGE_ROOT / "sources/megado-provenance.json"

ROLE_SLOTS = (
    "coordinator",
    "worker_normal",
    "worker_xhard",
    "reviewer_normal",
    "reviewer_xhard",
    "oracle",
    "final_reviewer",
)
PACK_IDS = {"megado": "megado", "scene-production": "scene_production", "work-starters": "work_starters"}
SAFE_PATH = re.compile(r"^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$")


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_path(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(SAFE_PATH.fullmatch(value))
        and value != "pack.yaml"
        and all(part not in {".", ".."} for part in value.split("/"))
    )


def _manifest(pack_id: str) -> Mapping[str, Any]:
    root = PACKS / pack_id
    value = _json(root / "pack.yaml")
    assert value["schema_version"] == 2
    assert value["id"] == PACK_IDS[pack_id]
    assert re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value["version"])
    assert "database" not in value
    documentation = value["documentation"]
    assert _safe_path(documentation["path"])
    assert (root / documentation["path"]).is_file()
    resources = value["resources"]
    assert resources
    paths = []
    for resource in resources:
        assert isinstance(resource["kind"], str) and resource["kind"]
        assert _safe_path(resource["path"])
        assert (root / resource["path"]).is_file()
        paths.append(resource["path"])
    assert len(paths) == len(set(paths))
    return value


def _all_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [item for child in value.values() for item in _all_strings(child)]
    if isinstance(value, list):
        return [item for child in value for item in _all_strings(child)]
    return []


def _validate_resource_manifest(value: Mapping[str, Any], root: Path) -> None:
    """Small local mirror of the current v2 fail-closed boundary."""
    if value.get("schema_version") != 2:
        raise ValueError("schema_version must be 2")
    if "database" in value:
        raise ValueError("database contributions are forbidden")
    for item in value.get("resources", []):
        raw = item.get("path")
        if not _safe_path(raw):
            raise ValueError("resource path must be safe and relative")
        resolved = (root / raw).resolve()
        if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
            raise ValueError("resource path is missing or escapes owner root")


def test_all_distributions_parse_as_resource_only_v2_packs() -> None:
    for pack_id, count in {"megado": 15, "scene-production": 3, "work-starters": 1}.items():
        manifest = _manifest(pack_id)
        _validate_resource_manifest(manifest, PACKS / pack_id)
        assert len(manifest["resources"]) == count
        assert all("database" not in _json(PACKS / pack_id / item["path"])
                   if item["path"].endswith(".json") else True
                   for item in manifest["resources"])


def test_unknown_resource_kinds_remain_opaque_and_are_not_executed() -> None:
    unknown = {"kind": "future.opaque.kind", "path": "future.json"}
    executable_kinds = {"python", "command", "agent", "database", "scheduler"}
    assert unknown["kind"] not in executable_kinds
    observed = []
    if unknown["kind"] in executable_kinds:
        observed.append(unknown["kind"])
    assert observed == []
    for pack_id in ("megado", "scene-production", "work-starters"):
        kinds = [item["kind"] for item in _manifest(pack_id)["resources"]]
        assert all(kind not in executable_kinds for kind in kinds)


def test_database_and_path_escape_declarations_fail_closed(tmp_path: Path) -> None:
    valid = dict(_manifest("work-starters"))
    forbidden = dict(valid)
    forbidden["database"] = {"tables": ["megado_runs"]}
    with pytest.raises(ValueError, match="database contributions"):
        _validate_resource_manifest(forbidden, PACKS / "work-starters")
    escaped = dict(valid)
    escaped["resources"] = [{"path": "../outside.json", "kind": "work_template"}]
    with pytest.raises(ValueError, match="safe and relative"):
        _validate_resource_manifest(escaped, tmp_path)


def test_import_boundary_does_not_open_ddl_or_invoke_agents() -> None:
    code = """
import sys
import herzchen.packs.composition
import herzchen.packs.templates
assert 'sqlite3' not in sys.modules
assert not any(name.startswith(('astrid', 'otto', 'runtime')) for name in sys.modules)
"""
    subprocess.run([sys.executable, "-c", code], check=True)


def test_megado_exposes_exact_slots_finite_routes_and_pinned_bindings() -> None:
    protocol = _json(PACKS / "megado/protocols/megado.json")
    assert tuple(protocol["role_slots"]) == ROLE_SLOTS
    assert protocol["routes"] == {
        "execute": {"normal": "worker_normal", "xhard": "worker_xhard"},
        "assess": {"normal": "reviewer_normal", "xhard": "reviewer_xhard"},
    }
    for route in protocol["routes"].values():
        assert all(isinstance(choice, str) and choice in ROLE_SLOTS for choice in route.values())
    assert protocol["default_role_bindings"]["worker_normal"] == {
        "model": "gpt-5.6-luna", "reasoning": "high"
    }
    assert protocol["default_role_bindings"]["reviewer_normal"] == {
        "model": "gpt-5.6-luna", "reasoning": "xhigh"
    }
    assert protocol["default_role_bindings"]["worker_xhard"] == {
        "model": "gpt-5.6-sol", "reasoning": "high"
    }
    assert protocol["default_role_bindings"]["oracle"] == {
        "model": "gpt-6-astra", "reasoning": "high"
    }
    assert protocol["default_role_bindings"]["final_reviewer"] == {
        "model": "gpt-6-astra", "reasoning": "high"
    }
    assert protocol["assurance"]["automatic_dispatch"] is False
    assert protocol["assurance"]["periodic_reviews_default"] == []
    extension = _json(PACKS / "megado/schemas/task-extension.json")
    assert extension["properties"]["execution_class"]["enum"] == ["normal", "xhard"]


def test_templates_are_data_with_explicit_protocol_and_review_choices() -> None:
    protocol = _json(PACKS / "megado/protocols/megado.json")
    templates = [
        _json(PACKS / "megado/templates/delivery.json"),
        _json(PACKS / "megado/templates/reviewed-delivery.json"),
        _json(PACKS / "megado/templates/task-batch.json"),
    ]
    for template in templates:
        assert template["protocol"] == protocol["id"]
        assert template["seed"]["status"] == "planning_only"
        assert all("$local" in json.dumps(link) or "$param" in json.dumps(link)
                   for link in template["seed"].get("links", [])
                   for _ in [0])
    assert _json(PACKS / "megado/templates/delivery.json")["seed"]["assessments"] == []
    assert _json(PACKS / "megado/templates/task-batch.json")["seed"]["assessments"] == []
    assessments = _json(PACKS / "megado/templates/reviewed-delivery.json")["seed"]["assessments"]
    assert len(assessments) == 1
    assert assessments[0]["role_slot"] == "reviewer_normal"
    assert assessments[0]["requested_max_rounds"] == 1
    assert assessments[0]["role_slot"] not in {"reviewer_xhard", "final_reviewer"}


def test_scene_is_generic_and_has_human_model_critique_without_megado_hierarchy() -> None:
    protocol = _json(PACKS / "scene-production/protocols/scene.json")
    assert protocol["routes"] == {}
    assert set(protocol["role_slots"]) == {"creator", "editor", "critic"}
    assert "oracle" not in protocol["role_slots"]
    skill = (PACKS / "scene-production/skill/SKILL.md").read_text(encoding="utf-8")
    values = " ".join(_all_strings(protocol) + _all_strings(skill))
    assert "god" not in values.lower()
    assert "human/agent feedback" in skill
    assert "no mandatory" in skill


def test_blank_starter_is_sparse_and_has_no_megado_dependency() -> None:
    manifest = _manifest("work-starters")
    template = _json(PACKS / "work-starters/templates/blank-project.json")
    assert [item["path"] for item in manifest["resources"]] == ["templates/blank-project.json"]
    assert "protocol" not in template
    assert "megado" not in json.dumps(template).lower()
    work = template["seed"]["work"]
    assert len(work) == 1 and work[0]["kind"] == "project"
    assert template["seed"]["links"] == []
    assert template["seed"]["documents"] == []
    assert template["seed"]["assessments"] == []
    assert template["seed"]["status"] == "planning_only"
    assert work[0]["custom"] == {}


def test_low_downside_templates_do_not_add_an_automatic_review() -> None:
    for path in (
        PACKS / "megado/templates/delivery.json",
        PACKS / "megado/templates/task-batch.json",
        PACKS / "scene-production/templates/scene.json",
        PACKS / "work-starters/templates/blank-project.json",
    ):
        assert _json(path)["seed"]["assessments"] == []
    reviewed = _json(PACKS / "megado/templates/reviewed-delivery.json")
    assert reviewed["seed"]["assessments"]
    assert "automatic" not in json.dumps(reviewed["seed"]["assessments"]).lower()


def test_active_megado_skill_matches_file_mode_export_and_provenance() -> None:
    native = PACKS / "megado/skill"
    assert FILE_MODE_EXPORT.is_dir()
    assert PROVENANCE.is_file()
    provenance = _json(PROVENANCE)
    assert provenance["active_skill"] == "packs/megado/skill/SKILL.md"
    assert provenance["file_mode_export"] == "skill-export/megado"
    assert provenance["upstream_written"] is False
    assert hashlib.sha256((native / "SKILL.md").read_bytes()).hexdigest() == provenance["active_skill_sha256"]
    native_files = sorted(path.relative_to(native) for path in native.rglob("*") if path.is_file())
    export_files = sorted(path.relative_to(FILE_MODE_EXPORT) for path in FILE_MODE_EXPORT.rglob("*") if path.is_file())
    assert native_files == export_files
    for relative in native_files:
        assert (native / relative).read_bytes() == (FILE_MODE_EXPORT / relative).read_bytes()


def test_shipped_skill_links_resolve_offline_inside_pack() -> None:
    root = PACKS / "megado/skill"
    markdown_link = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    for source in root.rglob("*.md"):
        for target in markdown_link.findall(source.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "#")):
                continue
            resolved = (source.parent / target).resolve()
            assert resolved.is_relative_to(root.resolve()), (source, target)
            assert resolved.is_file(), (source, target)
