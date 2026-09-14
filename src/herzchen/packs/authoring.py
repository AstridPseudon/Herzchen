"""Managed pack compatibility and content-only authoring.

The reader deliberately delegates pack admission to Astrid's public v2
loader/discovery path.  The authoring handler only snapshots already-admitted
resource bytes through the supplied FND store; it never interprets resource
code, creates a database, or owns a second writer.
"""

from __future__ import annotations

import weakref

_COMMAND_PORTS = weakref.WeakKeyDictionary()

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional, Protocol, Sequence

from herzchen.contracts import (
    AuthenticatedActor,
    CommandEnvelope,
    DomainContribution,
    PackResourceDescriptor,
    ResourceRef,
    TransactionContext,
    canonical_json,
)
from herzchen.kernel import Store, Transaction


PACK_SCHEMA_REVISION = "pkg-05.managed-pack.v1"
MANAGED_PACK_KIND = "managed_pack"
MANAGED_PACK_STREAM = "managed-pack"
_SAFE_PATH = re.compile(r"^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$")
_HEX = re.compile(r"^[0-9a-f]+$")


def domain_contribution() -> DomainContribution:
    return DomainContribution(
        "herzchen.packs.authoring", "1", "pkg", (MANAGED_PACK_KIND,), (),
        ("pack.authoring",), ("pack.content.author",),
        ("managed_pack.content_authored",), PACK_SCHEMA_REVISION,
        (
            "fnd-03.identities", "fnd-03.record_references", "fnd-03.transaction", "handler-required",
            "mutation-port:" + PACK_SCHEMA_REVISION + "|pack.content.author|" + MANAGED_PACK_KIND + "|managed_pack.content_authored",
        ),
    )


class PackAuthoringError(ValueError):
    """Base error for managed pack admission and content authoring."""


class PackLoaderUnavailableError(PackAuthoringError):
    """Astrid's supported public loader/discovery API is unavailable."""


class PackProvenanceError(PackAuthoringError):
    """A managed pack is missing or has inconsistent source provenance."""


class PackPathError(PackAuthoringError):
    """A resource path is unsafe or not part of the admitted pack."""


class PackContentError(PackAuthoringError):
    """Resource content is not a JSON-safe authoring value."""


class PublicPackDiscoverer(Protocol):
    def __call__(self, *, project_root: str | Path) -> Sequence[Any]: ...


class PublicPackLoader(Protocol):
    def __call__(self, path: str | Path, *, expected_pack_id: str | None = None) -> Any: ...


@dataclass(frozen=True)
class ManagedSourceIdentity:
    """The identity attached by Astrid's verified managed-source inventory."""

    pack_id: str
    source_kind: str
    source_revision: str
    source_tree_sha256: str
    source_manifest_sha256: str
    source_inventory_identity: str
    pack_root: str
    manifest_path: str

    def __post_init__(self) -> None:
        for field in ("pack_id", "source_kind", "source_revision", "source_tree_sha256",
                      "source_manifest_sha256", "source_inventory_identity", "pack_root",
                      "manifest_path"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise PackProvenanceError(f"{field} must be non-blank")
        if self.source_kind != "managed":
            raise PackProvenanceError("managed pack provenance must have source_kind='managed'")
        for field in ("source_revision", "source_tree_sha256", "source_manifest_sha256",
                      "source_inventory_identity"):
            value = getattr(self, field).lower()
            if len(value) not in {40, 64} or _HEX.fullmatch(value) is None:
                raise PackProvenanceError(f"{field} must be a full immutable hex identity")
        root = Path(self.pack_root).expanduser()
        manifest = Path(self.manifest_path).expanduser()
        if not root.is_absolute() or root.is_symlink() or not root.is_dir():
            raise PackProvenanceError("managed pack root must be an absolute non-symlink directory")
        if not manifest.is_absolute() or manifest.is_symlink() or not manifest.is_file():
            raise PackProvenanceError("managed manifest must be an absolute non-symlink file")
        if manifest.parent.resolve() != root.resolve() or manifest.name != "pack.yaml":
            raise PackProvenanceError("managed manifest must be pack.yaml in the managed pack root")

    def to_dict(self) -> dict[str, str]:
        return {
            "pack_id": self.pack_id,
            "source_kind": self.source_kind,
            "source_revision": self.source_revision,
            "source_tree_sha256": self.source_tree_sha256,
            "source_manifest_sha256": self.source_manifest_sha256,
            "source_inventory_identity": self.source_inventory_identity,
            "pack_root": self.pack_root,
            "manifest_path": self.manifest_path,
        }


@dataclass(frozen=True)
class ManagedResource:
    path: str
    kind: str
    content: bytes
    source_digest: str
    source_ref: ResourceRef

    def __post_init__(self) -> None:
        _validate_relative_path(self.path)
        if not isinstance(self.kind, str) or not self.kind.strip():
            raise PackContentError("resource kind must be non-blank")
        if not isinstance(self.content, bytes):
            raise PackContentError("resource content must be bytes")
        digest = hashlib.sha256(self.content).hexdigest()
        if self.source_digest != digest:
            raise PackContentError(f"resource digest mismatch for {self.path}")


@dataclass(frozen=True)
class ExecutionPin:
    resource_id: str
    kind: str
    revision: str
    digest: str
    role: str | None = None
    model: str | None = None
    reasoning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "resource_id": self.resource_id,
            "kind": self.kind,
            "revision": self.revision,
            "digest": self.digest,
        }
        for key, item in (("role", self.role), ("model", self.model), ("reasoning", self.reasoning)):
            if item is not None:
                value[key] = item
        return value


@dataclass(frozen=True)
class ManagedPack:
    pack_id: str
    version: str
    source: ManagedSourceIdentity
    manifest: Mapping[str, Any]
    resources: tuple[ManagedResource, ...]
    execution_pins: tuple[ExecutionPin, ...]
    review_profiles: tuple[str, ...]

    def resource(self, path: str) -> ManagedResource:
        for item in self.resources:
            if item.path == path:
                return item
        raise PackPathError(f"resource is not declared by pack: {path!r}")

    @property
    def resource_digests(self) -> Mapping[str, str]:
        return {item.path: item.source_digest for item in self.resources}

    def to_dict(self) -> dict[str, Any]:
        return {
            "pack_id": self.pack_id,
            "version": self.version,
            "source": self.source.to_dict(),
            "manifest": dict(self.manifest),
            "resources": [
                {
                    "path": item.path,
                    "kind": item.kind,
                    "digest": item.source_digest,
                    "source_ref": item.source_ref.to_dict(),
                }
                for item in self.resources
            ],
            "execution_pins": [item.to_dict() for item in self.execution_pins],
            "review_profiles": list(self.review_profiles),
        }


@dataclass(frozen=True)
class CompatibilityDescription:
    pack_id: str
    current: Mapping[str, Any]
    historical: tuple[Mapping[str, Any], ...]
    aliases: tuple[Mapping[str, str], ...]
    migration_instructions: tuple[str, ...]
    execution: Mapping[str, Any]
    lesson_transfer: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "pack_id": self.pack_id,
            "current": dict(self.current),
            "historical": [dict(item) for item in self.historical],
            "aliases": [dict(item) for item in self.aliases],
            "migration_instructions": list(self.migration_instructions),
            "execution": dict(self.execution),
            "lesson_transfer": dict(self.lesson_transfer),
        }


@dataclass(frozen=True)
class AuthoringResult:
    pack_id: str
    revision: str
    snapshot_ref: ResourceRef
    receipt: Any
    changed_paths: tuple[str, ...]
    content: Mapping[str, Mapping[str, Any]]
    execution_pins: tuple[Mapping[str, Any], ...]


def _validate_relative_path(path: Any) -> str:
    if not isinstance(path, str) or not _SAFE_PATH.fullmatch(path):
        raise PackPathError("resource paths must be safe POSIX-relative paths")
    if path == "pack.yaml" or any(part in {".", ".."} for part in path.split("/")):
        raise PackPathError(f"unsafe resource path: {path!r}")
    return path


def _public_apis() -> tuple[PublicPackDiscoverer, PublicPackLoader]:
    try:
        from astrid.core.pack.discovery import discover_canonical_pack_metadata
        from astrid.core.pack.loader import load_pack_manifest
    except ImportError as exc:  # pragma: no cover - exercised by a missing product install
        raise PackLoaderUnavailableError(
            "Astrid public managed discovery and pack loader are required"
        ) from exc
    return discover_canonical_pack_metadata, load_pack_manifest


def _source_from_discovered(item: Any) -> ManagedSourceIdentity:
    entry = item.entry
    values = {
        "pack_id": item.id,
        "source_kind": item.source_kind,
        "source_revision": item.source_revision,
        "source_tree_sha256": item.source_tree_sha256,
        "source_manifest_sha256": item.source_manifest_sha256,
        "source_inventory_identity": item.source_inventory_identity,
        "pack_root": str(item.pack_dir.resolve()),
        "manifest_path": str((item.pack_dir / "pack.yaml").resolve()),
    }
    if any(not isinstance(values[name], str) or not values[name] for name in values):
        raise PackProvenanceError(f"managed source record for {item.id!r} is incomplete")
    if entry.manifest.sha256 != values["source_manifest_sha256"]:
        raise PackProvenanceError(f"manifest digest does not match managed source for {item.id!r}")
    return ManagedSourceIdentity(**values)


def _execution_pins(pack_id: str, source: ManagedSourceIdentity, resources: Iterable[ManagedResource]) -> tuple[ExecutionPin, ...]:
    pins: list[ExecutionPin] = []
    for item in resources:
        if item.kind not in {"work_protocol", "protocol_reference", "protocol_guidance", "skill"}:
            continue
        pins.append(ExecutionPin(
            resource_id=f"{pack_id}/{item.path}",
            kind=item.kind,
            revision=source.source_revision,
            digest=item.source_digest,
        ))
    return tuple(sorted(pins, key=lambda item: item.resource_id))


def read_managed_pack(
    pack_id: str,
    *,
    project_root: str | Path,
    discoverer: PublicPackDiscoverer | None = None,
    loader: PublicPackLoader | None = None,
) -> ManagedPack:
    """Read one pack through the real Astrid managed-source discovery route."""
    if not isinstance(pack_id, str) or not pack_id.strip():
        raise PackAuthoringError("pack_id must be non-blank")
    if (discoverer is None) != (loader is None):
        raise PackAuthoringError(
            "discoverer and loader must be supplied together; do not mix an admission adapter with the Astrid default"
        )
    if discoverer is None:
        discover, load = _public_apis()
    else:
        discover, load = discoverer, loader
    try:
        discovered = tuple(discover(project_root=project_root))
    except Exception as exc:  # normalize public-loader failures at this boundary
        raise PackAuthoringError(f"managed pack discovery failed for {pack_id!r}: {exc}") from exc
    candidates = [item for item in discovered if item.id == pack_id and item.source_kind == "managed"]
    if len(candidates) != 1:
        raise PackProvenanceError(
            f"expected one managed source for {pack_id!r}, found {len(candidates)}"
        )
    item = candidates[0]
    source = _source_from_discovered(item)
    try:
        loaded = load(source.manifest_path, expected_pack_id=pack_id)
    except Exception as exc:
        raise PackAuthoringError(f"public pack loader rejected {pack_id!r}: {exc}") from exc
    definition = item.entry.definition
    if loaded.id != pack_id or loaded.schema_version != "2":
        raise PackAuthoringError("public loader returned a non-v2 or mismatched pack")
    resources: list[ManagedResource] = []
    seen: set[str] = set()
    for handle in item.entry.resource_handles:
        path = _validate_relative_path(handle.path)
        if path in seen:
            raise PackContentError(f"duplicate resource path: {path}")
        seen.add(path)
        if handle.resolved.is_symlink() or not handle.resolved.is_file():
            raise PackPathError(f"resource is not a regular non-symlink file: {path}")
        content = handle.resolved.read_bytes()
        kind = handle.kind.split(":", 1)[1] if ":" in handle.kind else handle.kind
        resources.append(ManagedResource(
            path, kind, content, handle.sha256,
            ResourceRef("astrid-managed", MANAGED_PACK_KIND, pack_id, source.source_revision),
        ))
    if not resources:
        raise PackContentError(f"managed pack {pack_id!r} declares no resources")
    return ManagedPack(
        pack_id,
        definition.version,
        source,
        definition.to_dict(),
        tuple(sorted(resources, key=lambda item: item.path)),
        _execution_pins(pack_id, source, resources),
        _review_profiles(definition.to_dict(), resources),
    )


def _review_profiles(manifest: Mapping[str, Any], resources: Iterable[ManagedResource]) -> tuple[str, ...]:
    profiles: set[str] = set()
    for item in resources:
        if item.kind != "work_protocol":
            continue
        try:
            value = json.loads(item.content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        for route in value.get("routes", {}).values():
            if isinstance(route, Mapping):
                profiles.update(str(key) for key in route)
    return tuple(sorted(profiles & {"normal", "xhard"}))


def describe_compatibility(pack: ManagedPack) -> CompatibilityDescription:
    """Return inspectable current/historical and execution-boundary facts."""
    current_resources = [
        {
            "id": f"{pack.pack_id}/{item.path}",
            "path": item.path,
            "kind": item.kind,
            "revision": pack.source.source_revision,
            "digest": item.source_digest,
        }
        for item in pack.resources
    ]
    aliases: list[dict[str, str]] = []
    migration: list[str] = [
        "Use canonical pack.yaml and schema_version 2; legacy/v1/alternate manifests remain rejected.",
        "Resolve resources by pack ID and declared relative path, never by an unbound folder-name guess.",
    ]
    if pack.pack_id == "scene_production":
        aliases.append({"old": "scene-production", "new": "scene_production", "kind": "pack_id"})
        migration.append("Map the historical scene-production directory to manifest ID scene_production in the managed inventory.")
    if pack.pack_id == "work_starters":
        aliases.append({"old": "work-starters", "new": "work_starters", "kind": "pack_id"})
        migration.append("Map the historical work-starters directory to manifest ID work_starters in the managed inventory.")
    if pack.pack_id == "megado":
        migration.append("Keep the maintained Megado skill and file-mode export byte-identical; adopt a new revision explicitly.")
    execution = {
        "pins": [item.to_dict() for item in pack.execution_pins],
        "profiles": list(pack.review_profiles),
        "normal_xhard_independent": True,
        "compulsory_stage_count": 1,
        "counter_reset": False,
        "new_specialist_recipe": "deferred:LATER-01",
    }
    lesson = {
        "origin_evidence": "tests/packs/test_protocol_resources.py::test_active_megado_skill_matches_file_mode_export_and_provenance",
        "adopted_resource": f"{pack.pack_id}/skill/SKILL.md@{pack.source.source_revision}",
        "tool_identity": "herzchen-contracts/pkg-05-public-reader",
        "retained_regression": "tests/packs/test_protocol_resources.py::test_shipped_skill_links_resolve_offline_inside_pack",
        "claim": "transfer mechanics only; no universal benefit or cadence/rights grant",
    }
    return CompatibilityDescription(
        pack.pack_id,
        {
            "manifest_schema": 2,
            "source": pack.source.to_dict(),
            "resources": current_resources,
        },
        (
            {"id": "pack-v1", "status": "rejected", "reason": "schema_version is not 2"},
            {"id": "alternate-manifest", "status": "rejected", "reason": "canonical filename must be pack.yaml"},
            {"id": "database-pack", "status": "rejected", "reason": "database contributions are forbidden"},
        ),
        tuple(aliases),
        tuple(migration),
        execution,
        lesson,
    )


def verify_skill_export(native_root: str | Path, file_export_root: str | Path) -> Mapping[str, Any]:
    """Prove byte identity and offline relative-link resolution for a skill export."""
    native = Path(native_root).expanduser().resolve()
    exported = Path(file_export_root).expanduser().resolve()
    if native.is_symlink() or exported.is_symlink() or not native.is_dir() or not exported.is_dir():
        raise PackPathError("skill roots must be existing non-symlink directories")
    native_files = sorted(path.relative_to(native).as_posix() for path in native.rglob("*") if path.is_file())
    export_files = sorted(path.relative_to(exported).as_posix() for path in exported.rglob("*") if path.is_file())
    if native_files != export_files:
        raise PackContentError("native skill and file-mode export file inventories differ")
    for relative in native_files:
        if (native / relative).read_bytes() != (exported / relative).read_bytes():
            raise PackContentError(f"skill export differs at {relative}")
    link_re = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    links_checked = 0
    for source in native.rglob("*.md"):
        for target in link_re.findall(source.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "#")):
                continue
            resolved = (source.parent / target).resolve()
            if not resolved.is_relative_to(native) or not resolved.is_file():
                raise PackPathError(f"offline skill link does not resolve: {source} -> {target}")
            links_checked += 1
    return {"files": native_files, "sha256": _tree_bytes_digest(native), "offline_relative_links": links_checked}


def _tree_bytes_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        payload = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def _digest_payload(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(dict(value)).encode("utf-8")).hexdigest()


def _content_record(item: ManagedResource, revision: str, content: bytes) -> dict[str, Any]:
    descriptor = PackResourceDescriptor(
        resource_id=item.path.replace("/", "."),
        kind=item.kind,
        revision=revision,
        source_ref=item.source_ref,
        digest=hashlib.sha256(content).hexdigest(),
        annotations={"path": item.path, "encoding": "base64"},
    )
    return {
        "descriptor": descriptor.to_dict(),
        "content_b64": base64.b64encode(content).decode("ascii"),
    }


def _decode_content(path: str, value: Mapping[str, Any]) -> bytes:
    try:
        content = base64.b64decode(value["content_b64"], validate=True)
    except (KeyError, TypeError, ValueError) as exc:
        raise PackContentError(f"stored content is invalid for {path}") from exc
    descriptor = value.get("descriptor")
    if not isinstance(descriptor, Mapping) or descriptor.get("digest") != hashlib.sha256(content).hexdigest():
        raise PackContentError(f"stored descriptor digest mismatch for {path}")
    return content


class ManagedPackAuthoringHandler:
    """Content-only managed pack handler over the injected FND store."""

    def __init__(self, store: Store) -> None:
        if not hasattr(store, "transaction") or not hasattr(store, "mutate"):
            raise TypeError("store must be the supplied FND writer")
        if hasattr(store, "domain_handler"):
            store = store.domain_handler((domain_contribution(),))
        _COMMAND_PORTS[self] = store
        self.reader = store.consumer()

    def author(
        self,
        pack: ManagedPack,
        updates: Mapping[str, bytes | bytearray | str] | None = None,
        *,
        logical_request_key: str,
        actor: AuthenticatedActor,
        transaction: Transaction | None = None,
    ) -> AuthoringResult:
        if not isinstance(pack, ManagedPack):
            raise TypeError("pack must be a ManagedPack read through the public loader")
        if not isinstance(actor, AuthenticatedActor):
            raise TypeError("actor must be an AuthenticatedActor")
        updates = dict(updates or {})
        declared = {item.path: item for item in pack.resources}
        for path in updates:
            _validate_relative_path(path)
            if path not in declared:
                raise PackPathError(f"authoring update is not an admitted resource: {path!r}")
        current_ref = ResourceRef(_COMMAND_PORTS[self].authority, MANAGED_PACK_KIND, pack.pack_id)
        current = _COMMAND_PORTS[self].get_identity(current_ref)
        if current is not None:
            current_ref = current.ref
            current_payload = dict(current.payload)
            if current_payload.get("record_type") != MANAGED_PACK_KIND:
                raise PackContentError("managed pack identity has an unexpected record type")
            existing_resources = dict(current_payload.get("resources", {}))
        else:
            current_payload = {}
            existing_resources = {}
        next_revision = f"rev-{(current.version if current is not None else 0) + 1}"
        merged: dict[str, dict[str, Any]] = dict(existing_resources)
        for item in pack.resources:
            content = item.content
            if item.path in updates:
                content = _coerce_content(updates[item.path])
            merged[item.path] = _content_record(item, next_revision, content)
        # Existing resources not present in a newer source remain untouched;
        # this is the unknown-sibling retention boundary.
        for path, record in merged.items():
            _validate_relative_path(path)
            if not isinstance(record, Mapping):
                raise PackContentError(f"stored sibling resource is invalid: {path}")
            _decode_content(path, record)
        execution_pins = tuple(item.to_dict() for item in pack.execution_pins)
        payload = {
            "record_type": MANAGED_PACK_KIND,
            "pack_id": pack.pack_id,
            "version": pack.version,
            "source": pack.source.to_dict(),
            "resources": {path: merged[path] for path in sorted(merged)},
            "execution_pins": list(execution_pins),
            "compatibility": describe_compatibility(pack).to_dict(),
        }
        if current is not None and current.payload == payload:
            return AuthoringResult(
                pack.pack_id, current.ref.revision or "", current.ref, None, (),
                payload["resources"], tuple(execution_pins),
            )
        digest = _digest_payload(payload)
        context = TransactionContext(
            actor,
            logical_request_key,
            digest,
            expected_revision=current_ref.revision if current is not None else None,
            expected_version=current.version if current is not None else 0,
        )
        target = current_ref if current is not None else ResourceRef(_COMMAND_PORTS[self].authority, MANAGED_PACK_KIND, pack.pack_id)
        envelope = CommandEnvelope("pack.content.author", PACK_SCHEMA_REVISION, target, context, payload)
        result_ref = ResourceRef(_COMMAND_PORTS[self].authority, MANAGED_PACK_KIND, pack.pack_id, next_revision)
        receipt = _COMMAND_PORTS[self].mutate(
            envelope,
            event_type="managed_pack.content_authored",
            result_ref=result_ref,
            effects={
                "content_only": True,
                "changed_paths": sorted(updates),
                "content_snapshot": payload["resources"],
                "source": pack.source.to_dict(),
                "execution_pins": list(execution_pins),
            },
            stream=f"{MANAGED_PACK_STREAM}:{pack.pack_id}",
            transaction=transaction,
        )
        return AuthoringResult(
            pack.pack_id, result_ref.revision or "", result_ref, receipt,
            tuple(sorted(updates)), payload["resources"], tuple(execution_pins),
        )

    def read(self, pack_id: str, *, revision: str | None = None) -> Mapping[str, Any]:
        """Read the fresh adopted record or a retained pinned event snapshot."""
        current = _COMMAND_PORTS[self].get_identity(ResourceRef(_COMMAND_PORTS[self].authority, MANAGED_PACK_KIND, pack_id))
        if current is None:
            raise PackAuthoringError(f"managed pack is not adopted: {pack_id!r}")
        wanted = revision or current.ref.revision
        if wanted == current.ref.revision:
            return current.payload
        for event in _COMMAND_PORTS[self].list_events(stream=f"{MANAGED_PACK_STREAM}:{pack_id}"):
            if any(ref.revision == wanted for ref in event.after_refs):
                return {
                    "record_type": MANAGED_PACK_KIND,
                    "pack_id": pack_id,
                    "resources": event.effects["content_snapshot"],
                    "source": event.effects["source"],
                    "execution_pins": event.effects["execution_pins"],
                    "revision": wanted,
                }
        raise PackAuthoringError(f"pinned managed pack revision is unavailable: {wanted!r}")

    def lifecycle_handler(self, pack: ManagedPack, *, request_id: str) -> Any:
        """Return PKG content hooks for EDT's shared finish boundary."""
        from herzchen.authoring import CallableSemanticHandler, ValidationResult

        def updates(snapshot: Any) -> dict[str, bytes]:
            try:
                data = snapshot.file_bytes("pack-content.json")
            except (AttributeError, KeyError):
                data = snapshot.data
            payload = json.loads(data.decode("utf-8"))
            values = payload.get("updates") if isinstance(payload, Mapping) else None
            if not isinstance(values, Mapping):
                raise PackContentError("updates must be an object")
            declared = {item.path for item in pack.resources}
            result: dict[str, bytes] = {}
            for path, value in values.items():
                _validate_relative_path(path)
                if path not in declared:
                    raise PackPathError(f"authoring update is not an admitted resource: {path!r}")
                try:
                    result[path] = base64.b64decode(value, validate=True)
                except (TypeError, ValueError) as exc:
                    raise PackContentError(f"invalid base64 content for {path!r}") from exc
            return result

        def validate(snapshot: Any, checkout: Any, checkout_root: str) -> Any:
            try:
                updates(snapshot)
            except (PackAuthoringError, TypeError, ValueError, KeyError) as exc:
                return ValidationResult(False, str(exc))
            return ValidationResult(True)

        def apply(snapshot: Any, checkout: Any, tx: Any, writer: Any) -> Any:
            return self.author(
                pack, updates(snapshot), logical_request_key=request_id,
                actor=checkout.actor, transaction=tx,
            )

        return CallableSemanticHandler(validate, apply)

    def assign(self, pack: ManagedPack, *, logical_request_key: str, actor: AuthenticatedActor, transaction: Transaction | None = None) -> AuthoringResult:
        """Adopt the explicitly read revision while retaining prior pins."""
        return self.author(pack, logical_request_key=logical_request_key, actor=actor, transaction=transaction)


def _coerce_content(value: bytes | bytearray | str) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, str):
        return value.encode("utf-8")
    raise PackContentError("content updates must be bytes or UTF-8 text")


__all__ = [
    "AuthoringResult", "CompatibilityDescription", "ExecutionPin", "ManagedPack",
    "ManagedPackAuthoringHandler", "ManagedResource", "ManagedSourceIdentity",
    "MANAGED_PACK_KIND", "PACK_SCHEMA_REVISION", "PackAuthoringError", "domain_contribution",
    "PackContentError", "PackLoaderUnavailableError", "PackPathError",
    "PackProvenanceError", "describe_compatibility", "read_managed_pack",
    "verify_skill_export",
]
