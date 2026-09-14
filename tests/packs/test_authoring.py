"""PKG-05 public managed-pack and content-only authoring proofs."""

from __future__ import annotations

import base64
import builtins
import hashlib
import json
import os
import re
import shutil
from types import SimpleNamespace
from pathlib import Path

import pytest

from herzchen.contracts import AuthenticatedActor
from herzchen.kernel import Store
from herzchen.packs.authoring import (
    ManagedPackAuthoringHandler,
    PackContentError,
    PackPathError,
    PackAuthoringError,
    PackProvenanceError,
    describe_compatibility,
    read_managed_pack,
    verify_skill_export,
)


ROOT = Path(__file__).parents[2]
PACKAGE_ROOT = Path(
    "/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/"
    "work/package/otto_herzchen_delivery_v11_2"
)
PKG04_ROOT = ROOT.parent / "Herzchen-pkg04-worker"
PKG04_COMMIT = "62503c6bf1e08e6399ed97bc4ee5aab7d3f3d96e"


def _astrid():
    return pytest.importorskip("astrid.core.pack.loader")


@pytest.fixture()
def managed_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    setup = pytest.importorskip("astrid.core.pack.source_setup")
    assert PKG04_ROOT.is_dir()
    assert os.popen(f"git -C {PKG04_ROOT} rev-parse HEAD").read().strip() == PKG04_COMMIT
    records = {}
    sources = []
    for pack_id in ("megado", "scene-production", "work-starters"):
        manifest_id = {"scene-production": "scene_production", "work-starters": "work_starters"}.get(pack_id, pack_id)
        pack_root = PKG04_ROOT / "packs" / pack_id
        manifest = pack_root / "pack.yaml"
        tree_digest = setup._tree_digest(pack_root)
        manifest_digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
        source = setup.InstalledSource(
            manifest_id, pack_root, "local-pkg04-source", PKG04_COMMIT,
            f"packs/{pack_id}", manifest_digest, tree_digest,
        )
        sources.append(source)
        records[manifest_id] = source.to_dict()
    state = {"version": 1, "active": records, "cached": {}, "disabled": []}
    state_path = tmp_path / "pack-sources.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setenv("ASTRID_SOURCE_STATE", str(state_path))
    return tmp_path


@pytest.fixture()
def managed_pack(managed_state: Path):
    return read_managed_pack("megado", project_root=managed_state)


def test_public_managed_reader_uses_real_discovery_and_loader(managed_state: Path):
    packs = {
        pack_id: read_managed_pack(pack_id, project_root=managed_state)
        for pack_id in ("megado", "scene_production", "work_starters")
    }
    assert {item.source.source_kind for item in packs.values()} == {"managed"}
    assert {item.source.source_revision for item in packs.values()} == {PKG04_COMMIT}
    assert all(item.source.source_tree_sha256 for item in packs.values())
    assert all(item.source.source_inventory_identity for item in packs.values())
    assert packs["megado"].resource("skill/references/improvement-loop.md").source_digest
    assert packs["scene_production"].pack_id == "scene_production"


def _neutral_megado_adapter(*, wrong_digest_path: str | None = None):
    pack_root = ROOT / "packs/megado"
    manifest_path = pack_root / "pack.yaml"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    resource_paths = ("skill/SKILL.md", "skill/references/improvement-loop.md")
    handles = tuple(
        SimpleNamespace(
            path=path,
            resolved=pack_root / path,
            sha256=(
                "0" * 64
                if path == wrong_digest_path
                else hashlib.sha256((pack_root / path).read_bytes()).hexdigest()
            ),
            kind="resource:skill",
        )
        for path in resource_paths
    )
    entry = SimpleNamespace(
        id="megado",
        manifest=SimpleNamespace(sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest()),
        definition=SimpleNamespace(id="megado", version=manifest["version"], to_dict=lambda: manifest),
        resource_handles=handles,
    )
    discovered = SimpleNamespace(
        id="megado",
        entry=entry,
        source_kind="managed",
        source_revision="62503c6bf1e08e6399ed97bc4ee5aab7d3f3d96e",
        # Fixture-only identity derived from the actual pack bytes below; it
        # is not an authoritative Astrid source-tree admission claim.
        source_tree_sha256=_fixture_tree_identity(pack_root),
        source_manifest_sha256=entry.manifest.sha256,
        # This is the accepted PKG-04 inventory identity supplied to a fake
        # adapter, not a live managed-source inventory assertion.
        source_inventory_identity="3a5406c6c8640c0f3a771b21c0c30a88242b904150dc5c1362c925a334453974",
        pack_dir=pack_root,
    )

    def fake_discoverer(*, project_root):
        assert project_root == ROOT
        return (discovered,)

    def fake_loader(path, *, expected_pack_id=None):
        assert Path(path) == manifest_path
        assert expected_pack_id == "megado"
        return SimpleNamespace(id="megado", schema_version="2")

    return pack_root, manifest_path, handles, discovered, fake_discoverer, fake_loader


def _fixture_tree_identity(pack_root: Path) -> str:
    """Hash the actual fake-adapter pack bytes; not live Astrid provenance."""
    digest = hashlib.sha256()
    for path in sorted(item for item in pack_root.rglob("*") if item.is_file()):
        relative = path.relative_to(pack_root).as_posix().encode("utf-8")
        payload = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def test_neutral_admission_adapter_avoids_astrid_imports_and_preserves_identity(
    monkeypatch: pytest.MonkeyPatch,
):
    _, manifest_path, handles, discovered, fake_discoverer, fake_loader = _neutral_megado_adapter()

    real_import = builtins.__import__

    def block_product_imports(name, *args, **kwargs):
        if name == "astrid" or name.startswith(("astrid.", "otto", "runtime")):
            raise AssertionError(f"neutral adapter imported forbidden product module: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", block_product_imports)
    pack = read_managed_pack(
        "megado",
        project_root=ROOT,
        discoverer=fake_discoverer,
        loader=fake_loader,
    )
    assert pack.pack_id == "megado"
    assert pack.source.source_kind == "managed"
    assert pack.source.source_revision == discovered.source_revision
    assert pack.source.source_manifest_sha256 == discovered.source_manifest_sha256
    assert pack.resource("skill/SKILL.md").source_digest == handles[0].sha256
    assert pack.resource("skill/references/improvement-loop.md").source_ref.revision == discovered.source_revision


def test_neutral_admission_adapter_rejects_actual_resource_digest_mismatch():
    _, _, _, _, fake_discoverer, fake_loader = _neutral_megado_adapter(
        wrong_digest_path="skill/references/improvement-loop.md"
    )
    with pytest.raises(PackContentError, match="resource digest mismatch"):
        read_managed_pack(
            "megado",
            project_root=ROOT,
            discoverer=fake_discoverer,
            loader=fake_loader,
        )


def test_partial_admission_adapter_is_rejected_before_default_import():
    with pytest.raises(PackAuthoringError, match="supplied together"):
        read_managed_pack("megado", project_root=ROOT, discoverer=lambda **_: (), loader=None)


def test_blank_starter_is_sparse_pack_v2_and_independent_of_megado():
    manifest = json.loads((ROOT / "packs/work-starters/pack.yaml").read_text(encoding="utf-8"))
    template = json.loads((ROOT / "packs/work-starters/templates/blank-project.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 2
    assert [item["path"] for item in manifest["resources"]] == ["templates/blank-project.json"]
    assert "protocol" not in template and "megado" not in json.dumps(template).lower()
    assert len(template["seed"]["work"]) == 1
    assert template["seed"]["work"][0]["kind"] == "project"
    assert template["seed"]["work"][0]["custom"] == {}
    assert template["seed"]["links"] == []
    assert [document["role"] for document in template["seed"]["documents"]] == ["initial-specification"]
    assert template["seed"]["document_links"][0]["subject"] == {"$local": "project"}
    assert template["seed"]["assessments"] == []


@pytest.mark.parametrize("bad_manifest", [
    {"schema_version": 1},
    {"schema_version": 2, "database": {"tables": ["private"]}},
    {"schema_version": 2, "resources": [{"path": "../outside.json", "kind": "opaque"}]},
    {"schema_version": 2, "resources": [{"path": "x.json", "kind": "opaque"}, {"path": "x.json", "kind": "opaque"}]},
])
def test_supported_loader_rejects_legacy_database_escape_and_duplicate(tmp_path: Path, bad_manifest):
    loader = _astrid().load_pack_manifest
    pack_root = tmp_path / "bad"
    pack_root.mkdir()
    (pack_root / "x.json").write_text("{}", encoding="utf-8")
    payload = {
        "schema_version": 2, "id": "bad", "name": "Bad", "version": "1.0.0",
        "documentation": {"kind": "skill", "path": "x.json"},
        "resources": [{"path": "x.json", "kind": "opaque"}],
    }
    payload.update(bad_manifest)
    (pack_root / "pack.yaml").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(Exception):
        loader(pack_root / "pack.yaml", expected_pack_id="bad")


def test_supported_loader_rejects_symlinked_pack_tree(tmp_path: Path):
    loader = _astrid().load_pack_manifest
    pack_root = tmp_path / "bad"
    pack_root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    (pack_root / "linked.json").symlink_to(outside)
    (pack_root / "pack.yaml").write_text(json.dumps({
        "schema_version": 2, "id": "bad", "name": "Bad", "version": "1.0.0",
        "documentation": {"kind": "skill", "path": "linked.json"},
    }), encoding="utf-8")
    with pytest.raises(Exception):
        loader(pack_root / "pack.yaml", expected_pack_id="bad")


def test_invalid_managed_provenance_fails_closed(managed_state: Path):
    import astrid.core.pack.discovery as discovery

    def bad_discovery(*, project_root):
        items = list(discovery.discover_canonical_pack_metadata(project_root=project_root))
        item = items[0]
        return (type(item)(item.entry, "managed", item.priority_index, item.source_revision, None, item.source_tree_sha256, item.source_inventory_identity),)

    with pytest.raises(PackProvenanceError):
        read_managed_pack(
            "megado",
            project_root=managed_state,
            discoverer=bad_discovery,
            loader=_astrid().load_pack_manifest,
        )


def test_content_only_authoring_preserves_unknown_siblings_and_old_pins(managed_pack, tmp_path: Path):
    with Store.create(tmp_path / "pack.sqlite", authority="pkg05-test") as store:
        handler = ManagedPackAuthoringHandler(store)
        actor = AuthenticatedActor("pkg05-test", "author", "credential")
        tables_before = {
            row["name"] for row in store.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        first = handler.author(
            managed_pack,
            {"skill/SKILL.md": "# adopted revision one\n"},
            logical_request_key="pack-author-1",
            actor=actor,
        )
        unknown = {
            "descriptor": {
                "resource_id": "future/opaque.json", "kind": "future.opaque",
                "revision": "rev-2", "source_ref": first.snapshot_ref.to_dict(),
                "digest": hashlib.sha256(b"opaque").hexdigest(), "annotations": {},
            },
            "content_b64": base64.b64encode(b"opaque").decode("ascii"),
        }
        current = store.get_identity(first.snapshot_ref)
        assert current is not None
        payload = dict(current.payload)
        payload["resources"] = dict(payload["resources"])
        payload["resources"]["future/opaque.json"] = unknown
        store.revise_identity(current.ref, payload, revision="rev-2", expected_revision=current.ref.revision, expected_version=current.version)
        second = handler.author(
            managed_pack,
            {"skill/SKILL.md": "# adopted revision two\n"},
            logical_request_key="pack-author-3",
            actor=actor,
        )
        assert second.revision == "rev-3"
        fresh = handler.read("megado")
        old = handler.read("megado", revision=first.revision)
        assert fresh["resources"]["future/opaque.json"] == unknown
        assert fresh["resources"]["skill/SKILL.md"]["content_b64"] != old["resources"]["skill/SKILL.md"]["content_b64"]
        assert old["revision"] == first.revision
        assert fresh["execution_pins"]
        assert "invocation" not in fresh and "dependencies" not in fresh and "permissions" not in fresh
        tables_after = {
            row["name"] for row in store.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert tables_after == tables_before


def test_execution_choices_are_inspectable_and_independent(managed_pack):
    description = describe_compatibility(managed_pack).to_dict()
    assert description["execution"]["profiles"] == ["normal", "xhard"]
    assert description["execution"]["normal_xhard_independent"] is True
    assert description["execution"]["compulsory_stage_count"] == 1
    assert description["execution"]["counter_reset"] is False
    assert description["execution"]["new_specialist_recipe"] == "deferred:LATER-01"
    assert any(item["path"] == "skill/references/improvement-loop.md" for item in description["current"]["resources"])


def test_skill_export_is_byte_identical_and_links_resolve_offline():
    result = verify_skill_export(ROOT / "packs/megado/skill", PACKAGE_ROOT / "skill-export/megado")
    assert "references/improvement-loop.md" in result["files"]
    assert result["offline_relative_links"] > 0


def test_compatibility_inventory_has_explicit_history_aliases_and_transfer_fixture(managed_pack):
    description = describe_compatibility(managed_pack).to_dict()
    assert {item["id"] for item in description["historical"]} == {"pack-v1", "alternate-manifest", "database-pack"}
    assert description["aliases"] == []
    assert description["lesson_transfer"]["origin_evidence"].startswith("tests/packs/")
    assert description["lesson_transfer"]["adopted_resource"].endswith("@" + PKG04_COMMIT)
    assert "transfer mechanics only" in description["lesson_transfer"]["claim"]


def test_authoring_path_rejects_undeclared_escape_updates(managed_pack, tmp_path: Path):
    with Store.create(tmp_path / "pack.sqlite", authority="pkg05-test") as store:
        handler = ManagedPackAuthoringHandler(store)
        with pytest.raises(PackPathError):
            handler.author(
                managed_pack,
                {"../outside.json": b"bad"},
                logical_request_key="pack-author-bad",
                actor=AuthenticatedActor("pkg05-test", "author", "credential"),
            )
