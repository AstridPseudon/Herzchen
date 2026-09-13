"""Scoped, immutable context packets and bounded DAT-04 views.

This module is deliberately a thin domain adapter over the DAT-02 content
commands and the FND-03 Store.  A packet is a normal immutable content
document: current bindings are resolved once, and the resulting revision
references are stored in the packet revision.  Visibility is evaluated on
each read, so a link never grants access to its target.

The module does not create tables, caches, receipt/event stores, schema
conversion jobs, or a semantic impact engine.  In particular, input
applicability is compared by the references actually consumed by a packet;
digests are only evidence attached to those references.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Iterable, Mapping, Optional, Protocol, Sequence, Tuple, Union

from herzchen.contracts import (
    AuthenticatedActor,
    CommandEnvelope,
    EventCursor,
    ResourceRef,
    TransactionContext,
    canonical_json,
)
from herzchen.extensions.model import validate_json_schema

from .commands import ContentCommandHandler
from .model import (
    ContentDocument,
    ContentError,
    ContentRevision,
    revision_identity,
)


PACKET_SCHEMA_REVISION = "dat.context.packet.v1"
PACKET_KIND = "dat.context.packet"
ATTENTION_KIND = "dat.context.attention"
MANIFEST_KIND = "dat.content.document"


class PacketError(ContentError):
    """Base error for the bounded context-packet surface."""


class AccessDeniedError(PacketError):
    """The actor cannot see a document or backlink."""


class UnresolvedReferenceError(PacketError):
    """A current or required pinned reference cannot be resolved."""


class SchemaAdoptionRequiredError(PacketError):
    """A historical payload has no explicit schema adoption."""


class ImmutableManifestError(PacketError):
    """Candidate and decision manifests are create-once documents."""


class ConflictingAuthorityError(PacketError):
    """Two current authorities disagree and no amendment/hold was supplied."""


class FNDPacketWriter(Protocol):
    authority: str

    def transaction(self) -> Any: ...

    def mutate(self, envelope: CommandEnvelope, **kwargs: Any) -> Any: ...

    def put_identity(self, ref: ResourceRef, payload: Mapping[str, Any], **kwargs: Any) -> Any: ...

    def get_identity(self, ref: ResourceRef) -> Any: ...

    def put_reference(self, ref: ResourceRef, **kwargs: Any) -> ResourceRef: ...

    def get_reference(self, ref: ResourceRef) -> Optional[ResourceRef]: ...

    def list_events(self, **kwargs: Any) -> Sequence[Any]: ...


def _tuple_text(values: Iterable[Any], field: str) -> Tuple[str, ...]:
    result = tuple(value for value in values)
    if any(not isinstance(value, str) or not value.strip() for value in result):
        raise PacketError(f"{field} must contain non-blank strings")
    if len(set(result)) != len(result):
        raise PacketError(f"{field} contains duplicate values")
    return result


def _ref_tuple(values: Iterable[Any], field: str) -> Tuple[ResourceRef, ...]:
    result = tuple(values)
    if any(not isinstance(value, ResourceRef) for value in result):
        raise PacketError(f"{field} must contain ResourceRef values")
    return result


def _json(value: Any, field: str = "value") -> Any:
    try:
        canonical_json(value)
    except Exception as exc:  # ContractError, TypeError, and malformed JSON values.
        raise PacketError(f"{field} must be JSON-safe") from exc
    return value


def _actor_id(actor: Any) -> str:
    if isinstance(actor, AuthenticatedActor):
        return actor.actor
    if isinstance(actor, str) and actor.strip():
        return actor
    raise PacketError("actor must be an AuthenticatedActor or actor identity")


@dataclass(frozen=True)
class VisibilityContext:
    """The minimum actor/role/scope information used by packet reads."""

    actor: str
    roles: Tuple[str, ...] = ()
    scopes: Tuple[ResourceRef, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.actor, str) or not self.actor.strip():
            raise PacketError("visibility actor must be a non-blank string")
        object.__setattr__(self, "roles", _tuple_text(self.roles, "roles"))
        object.__setattr__(self, "scopes", _ref_tuple(self.scopes, "scopes"))

    @classmethod
    def from_actor(cls, actor: Any, roles: Iterable[str] = (), scopes: Iterable[ResourceRef] = ()) -> "VisibilityContext":
        return cls(_actor_id(actor), tuple(roles), tuple(scopes))


AccessContext = VisibilityContext
PacketActor = VisibilityContext


@dataclass(frozen=True)
class PacketInput:
    """One input request and its assignment-time resolved revision."""

    name: str
    binding: Any
    consumed: bool = True
    purpose: str = "input"

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise PacketError("input name must be non-blank")
        if not isinstance(self.consumed, bool):
            raise PacketError("input consumed must be boolean")
        if not isinstance(self.purpose, str) or not self.purpose.strip():
            raise PacketError("input purpose must be non-blank")


ContextInput = PacketInput


@dataclass(frozen=True)
class ContextPacket:
    """In-memory description of the durable packet revision."""

    packet_ref: ResourceRef
    actor: AuthenticatedActor
    inputs: Tuple[Mapping[str, Any], ...]
    protocol_ref: Optional[ResourceRef] = None
    schema_ref: Optional[ResourceRef] = None

    def __post_init__(self) -> None:
        if not isinstance(self.packet_ref, ResourceRef) or self.packet_ref.revision is None:
            raise PacketError("packet_ref must be a pinned ResourceRef")
        if not isinstance(self.actor, AuthenticatedActor):
            raise PacketError("packet actor must be authenticated")
        if any(not isinstance(item, Mapping) for item in self.inputs):
            raise PacketError("packet inputs must be mappings")
        for field, value in (("protocol_ref", self.protocol_ref), ("schema_ref", self.schema_ref)):
            if value is not None and (not isinstance(value, ResourceRef) or value.revision is None):
                raise PacketError(f"{field} must be pinned when supplied")


@dataclass(frozen=True)
class SchemaAdoption:
    """An explicit, versioned adoption; it never rewrites old payloads."""

    schema_ref: ResourceRef
    origin: ResourceRef
    adopted_revision: str
    aliases: Mapping[str, str] = None  # type: ignore[assignment]
    adopted: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.schema_ref, ResourceRef) or self.schema_ref.revision is None:
            raise PacketError("schema_ref must be an explicitly pinned ResourceRef")
        if not isinstance(self.origin, ResourceRef):
            raise PacketError("schema adoption origin must be a ResourceRef")
        if not isinstance(self.adopted_revision, str) or not self.adopted_revision.strip():
            raise PacketError("adopted_revision must be non-blank")
        aliases = dict(self.aliases or {})
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in aliases.items()):
            raise PacketError("schema aliases must map strings to strings")
        object.__setattr__(self, "aliases", aliases)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_ref": self.schema_ref.to_dict(),
            "origin": self.origin.to_dict(),
            "adopted_revision": self.adopted_revision,
            "aliases": dict(self.aliases),
            "adopted": self.adopted,
        }


def _binding_parts(value: Any, name: str) -> tuple[ResourceRef, bool]:
    """Accept the existing ReferenceBinding shape and plain ResourceRef."""
    if hasattr(value, "ref") and hasattr(value, "mode"):
        ref = value.ref
        current = value.mode == "current"
    elif isinstance(value, ResourceRef):
        ref = value
        current = ref.revision is None
    elif isinstance(value, Mapping):
        if "binding" in value:
            return _binding_parts(value["binding"], name)
        if "ref" in value:
            ref = ResourceRef.from_dict(value["ref"])
            current = value.get("mode", "current") == "current"
        else:
            ref = ResourceRef.from_dict(value)
            current = ref.revision is None
    else:
        raise PacketError(f"{name} must be a ResourceRef, ReferenceBinding, or reference mapping")
    if not isinstance(ref, ResourceRef):
        raise PacketError(f"{name} did not contain a ResourceRef")
    if current and ref.revision is not None:
        raise PacketError(f"{name} current binding cannot carry a revision")
    if not current and ref.revision is None:
        raise PacketError(f"{name} pinned binding requires a revision")
    return ref, current


def _same_identity(left: ResourceRef, right: ResourceRef) -> bool:
    return (left.authority, left.kind, left.id) == (right.authority, right.kind, right.id)


class ContextPacketService:
    """Fresh, permission-filtered reads and FND-backed packet mutations."""

    def __init__(self, writer: Optional[FNDPacketWriter]) -> None:
        self._writer = writer
        self._content = ContentCommandHandler(writer)

    def _require_writer(self) -> FNDPacketWriter:
        if self._writer is None:
            raise PacketError("FND-03 Store is required")
        return self._writer

    @staticmethod
    def _context(context: Optional[VisibilityContext], actor: Any = None, roles: Iterable[str] = (), scopes: Iterable[ResourceRef] = ()) -> VisibilityContext:
        if context is not None:
            return context
        if actor is None:
            raise PacketError("an actor or visibility context is required")
        return VisibilityContext.from_actor(actor, roles, scopes)

    def _access(self, document: Mapping[str, Any], context: VisibilityContext) -> None:
        visibility = document.get("visibility", "private")
        maintainer = document.get("maintainer")
        if context.actor == maintainer:
            return
        allowed_actors = set(document.get("allowed_actors", document.get("readers", ())) or ())
        allowed_roles = set(document.get("allowed_roles", document.get("read_roles", ())) or ())
        if allowed_actors or allowed_roles:
            if context.actor not in allowed_actors and not allowed_roles.intersection(context.roles):
                raise AccessDeniedError("document role/reader policy excludes this actor")
            return
        scope = document.get("authoring_scope")
        if visibility == "public":
            return
        if visibility == "shared" and scope is None:
            return
        if visibility == "shared" and scope is not None:
            try:
                scope_ref = ResourceRef.from_dict(scope) if isinstance(scope, Mapping) else scope
                if any(_same_identity(scope_ref, candidate) for candidate in context.scopes):
                    return
            except (TypeError, ValueError):
                pass
        raise AccessDeniedError("document is outside the actor/role/scope visibility boundary")

    def resolve_reference(self, reference: Any, context: Optional[VisibilityContext] = None, *, actor: Any = None, roles: Iterable[str] = (), scopes: Iterable[ResourceRef] = ()) -> Mapping[str, Any]:
        """Resolve a current binding to one immutable revision at read time."""
        writer = self._require_writer()
        reference, current = _binding_parts(reference, "reference")
        if reference.authority != writer.authority:
            if current:
                raise UnresolvedReferenceError("foreign current references cannot be resolved by this Store")
            return {"requested": reference, "resolved": reference, "foreign": True}
        document_record = writer.get_identity(ResourceRef(reference.authority, reference.kind, reference.id))
        if document_record is None:
            raise UnresolvedReferenceError(f"reference is not admitted: {reference.to_json()}")
        document = document_record.payload.get("document")
        if isinstance(document, Mapping):
            visibility_context = self._context(context, actor, roles, scopes)
            self._access(document, visibility_context)
        if current:
            resolved_revision = document_record.ref.revision
            current_value = document_record.payload.get("current_revision")
            if isinstance(current_value, Mapping):
                resolved = ResourceRef.from_dict(current_value)
            elif resolved_revision is not None:
                resolved = ResourceRef(reference.authority, reference.kind, reference.id, resolved_revision)
            else:
                raise UnresolvedReferenceError("current reference has no current revision")
        else:
            resolved = reference
        revision_record = writer.get_identity(revision_identity(ResourceRef(resolved.authority, resolved.kind, resolved.id), resolved.revision)) if resolved.revision is not None else None
        if resolved.revision is not None and revision_record is None:
            if isinstance(document, Mapping):
                raise UnresolvedReferenceError(f"pinned revision is not admitted: {resolved.to_json()}")
            if document_record.ref.revision != resolved.revision:
                raise UnresolvedReferenceError(f"pinned identity is not current/admitted: {resolved.to_json()}")
            revision_record = document_record
        return {
            "requested": reference,
            "resolved": resolved,
            "document": document,
            "revision": None if revision_record is None else dict(revision_record.payload),
            "content": None if revision_record is None else revision_record.payload.get("content"),
        }

    resolve = resolve_reference
    resolve_current = resolve_reference

    def _packet_payload(self, packet_id: str, actor: AuthenticatedActor, inputs: Sequence[Mapping[str, Any]], *, protocol_ref: Optional[ResourceRef], schema_ref_value: Optional[ResourceRef], responsibility: Mapping[str, Any], adoptions: Sequence[SchemaAdoption], provenance: Mapping[str, Any]) -> Mapping[str, Any]:
        return {
            "record_type": PACKET_KIND,
            "packet_id": packet_id,
            "actor": actor,
            "inputs": tuple(inputs),
            "protocol_ref": protocol_ref,
            "schema_ref": schema_ref_value,
            "responsibility": dict(responsibility),
            "schema_adoptions": tuple(adoption.to_dict() for adoption in adoptions),
            "provenance": dict(provenance),
        }

    def create_packet(self, packet_id: str, context: TransactionContext, inputs: Sequence[Any], *, protocol: Any = None, schema: Any = None, responsibility: Optional[Mapping[str, Any]] = None, adoptions: Sequence[SchemaAdoption] = (), visibility: str = "private", maintainer: Optional[str] = None, authoring_scope: Optional[ResourceRef] = None, roles: Iterable[str] = (), scopes: Iterable[ResourceRef] = (), provenance: Optional[Mapping[str, Any]] = None) -> Mapping[str, Any]:
        """Create one packet whose revision contains only resolved input pins."""
        if not isinstance(context, TransactionContext):
            raise PacketError("context must be a TransactionContext")
        if not isinstance(packet_id, str) or not packet_id.strip():
            raise PacketError("packet_id must be non-blank")
        access = VisibilityContext.from_actor(context.actor, roles, scopes)
        stored_inputs = []
        for index, raw in enumerate(inputs):
            if isinstance(raw, PacketInput):
                name, binding, consumed, purpose = raw.name, raw.binding, raw.consumed, raw.purpose
            elif isinstance(raw, Mapping) and "name" in raw:
                name, binding, consumed, purpose = raw["name"], raw.get("binding", raw.get("ref")), bool(raw.get("consumed", True)), raw.get("purpose", "input")
            else:
                name, binding, consumed, purpose = f"input-{index + 1}", raw, True, "input"
            requested, _ = _binding_parts(binding, f"inputs[{index}]")
            resolved = self.resolve_reference(requested, access)["resolved"]
            self._ensure_storable_reference(resolved, f"inputs[{index}]")
            record = self._require_writer().get_identity(ResourceRef(resolved.authority, resolved.kind, resolved.id))
            source_digest = None if record is None else record.payload.get("content_digest")
            stored_inputs.append({"name": name, "requested_ref": requested, "resolved_ref": resolved, "consumed": consumed, "purpose": purpose, "source_digest": source_digest})

        protocol_ref = None
        if protocol is not None:
            protocol_ref = self.resolve_reference(protocol, access)["resolved"] if _binding_parts(protocol, "protocol")[1] else _binding_parts(protocol, "protocol")[0]
            if protocol_ref.revision is None:
                raise UnresolvedReferenceError("protocol must be pinned in a context packet")
        schema_ref_value = None
        if schema is not None:
            schema_ref_value = self.resolve_reference(schema, access)["resolved"] if _binding_parts(schema, "schema")[1] else _binding_parts(schema, "schema")[0]
            if schema_ref_value.revision is None:
                raise UnresolvedReferenceError("schema must be pinned in a context packet")
        for adoption in adoptions:
            if not isinstance(adoption, SchemaAdoption):
                raise PacketError("adoptions must contain SchemaAdoption values")
        payload = self._packet_payload(packet_id, context.actor, stored_inputs, protocol_ref=protocol_ref, schema_ref_value=schema_ref_value, responsibility=responsibility or {}, adoptions=adoptions, provenance=provenance or {"source": "dat.context.packet", "assignment": packet_id})
        document_ref = ResourceRef(self._require_writer().authority, PACKET_KIND, f"packet:{packet_id}")
        document = ContentDocument(document_ref, "context-packet", visibility, "read", maintainer or context.actor.actor, authoring_scope, None, "owned", True)
        revision = ContentRevision(document_ref, "packet-1", payload, context.actor, initial=True)
        receipt = self._content.execute(self._content.build_create_document(context, document, revision))
        for item in stored_inputs:
            self._require_writer().put_reference(item["resolved_ref"])
        return {"packet_ref": revision.ref, "document_ref": document_ref, "revision_ref": revision.ref, "receipt": receipt, "packet": payload}

    assign = create_packet
    create = create_packet

    def read_packet(self, packet: Any, context: Optional[VisibilityContext] = None, *, actor: Any = None, roles: Iterable[str] = (), scopes: Iterable[ResourceRef] = ()) -> Mapping[str, Any]:
        resolved = self.resolve_reference(packet, context, actor=actor, roles=roles, scopes=scopes)
        payload = resolved.get("content")
        if not isinstance(payload, Mapping) or payload.get("record_type") != PACKET_KIND:
            raise PacketError("reference is not a context packet")
        return {"packet_ref": resolved["resolved"], "content": dict(payload), "provenance": payload.get("provenance", {})}

    read = read_packet

    def compare_supplied_inputs(self, packet: Any, supplied: Union[Mapping[str, Any], Sequence[Any]], context: Optional[VisibilityContext] = None, *, actor: Any = None, roles: Iterable[str] = (), scopes: Iterable[ResourceRef] = ()) -> Mapping[str, Any]:
        """Compare exact consumed refs; annotations cannot cause invalidation."""
        packet_value = self.read_packet(packet, context, actor=actor, roles=roles, scopes=scopes)["content"]
        packet_inputs = [item for item in packet_value.get("inputs", ()) if item.get("consumed", True)]
        supplied_map = supplied if isinstance(supplied, Mapping) else {str(index + 1): value for index, value in enumerate(supplied)}
        changed, missing, irrelevant = [], [], []
        for item in packet_inputs:
            name = item.get("name")
            value = supplied_map.get(name)
            if value is None and name not in supplied_map:
                missing.append(name)
                continue
            requested, _ = _binding_parts(value, f"supplied[{name}]")
            current = self.resolve_reference(requested, context, actor=actor, roles=roles, scopes=scopes)["resolved"]
            pinned = ResourceRef.from_dict(item["resolved_ref"]) if isinstance(item.get("resolved_ref"), Mapping) else item.get("resolved_ref")
            if current != pinned:
                changed.append({"name": name, "expected": pinned, "observed": current})
        for name in supplied_map:
            if not any(item.get("name") == name for item in packet_inputs):
                irrelevant.append(name)
        return {"applicable": not changed and not missing, "invalidated": bool(changed), "changed_consumed": changed, "missing": missing, "irrelevant_annotations": irrelevant, "comparison": "consumed-reference-equality"}

    compare_inputs = compare_supplied_inputs

    def visible_backlinks(self, document: Any, context: Optional[VisibilityContext] = None, *, actor: Any = None, roles: Iterable[str] = (), scopes: Iterable[ResourceRef] = ()) -> Tuple[Mapping[str, Any], ...]:
        writer = self._require_writer()
        requested, _ = _binding_parts(document, "document")
        access = self._context(context, actor, roles, scopes)
        visible = []
        for event in writer.list_events():
            if event.event_type not in {"dat.content.linked", "dat.content.unlinked"}:
                continue
            association_id = event.effects.get("association")
            if not isinstance(association_id, str):
                continue
            association_ref = ResourceRef(event.store_authority, "document-association", association_id)
            record = writer.get_identity(association_ref)
            if record is None or not record.payload.get("active", False):
                continue
            association = record.payload.get("association", {})
            target = association.get("document", {}).get("ref") if isinstance(association, Mapping) else None
            if not isinstance(target, Mapping):
                continue
            target_ref = ResourceRef.from_dict(target)
            if not _same_identity(target_ref, requested):
                continue
            target_record = writer.get_identity(ResourceRef(target_ref.authority, target_ref.kind, target_ref.id))
            if target_record is None:
                continue
            try:
                self._access(target_record.payload.get("document", {}), access)
            except AccessDeniedError:
                continue
            subject = association.get("subject") if isinstance(association, Mapping) else None
            if isinstance(subject, Mapping):
                subject_ref = ResourceRef.from_dict(subject)
                subject_record = writer.get_identity(ResourceRef(subject_ref.authority, subject_ref.kind, subject_ref.id))
                if subject_record is not None and isinstance(subject_record.payload.get("document"), Mapping):
                    try:
                        self._access(subject_record.payload["document"], access)
                    except AccessDeniedError:
                        continue
            visible.append({"association": association_ref, "subject": association.get("subject"), "document": target_ref, "namespace": association.get("namespace"), "key": association.get("key")})
        return tuple(visible)

    backlinks = visible_backlinks

    def adopt_schema(self, schema: Any, *, origin: ResourceRef, aliases: Optional[Mapping[str, str]] = None, adopted_revision: Optional[str] = None) -> SchemaAdoption:
        ref, current = _binding_parts(schema, "schema")
        if current or ref.revision is None:
            raise SchemaAdoptionRequiredError("schema adoption requires an explicit pinned schema ref")
        return SchemaAdoption(ref, origin, adopted_revision or ref.revision, aliases or {})

    adopt = adopt_schema

    @staticmethod
    def require_adoption(adoptions: Sequence[SchemaAdoption], schema: ResourceRef) -> SchemaAdoption:
        for adoption in adoptions:
            if adoption.schema_ref == schema and adoption.adopted:
                return adoption
        raise SchemaAdoptionRequiredError("no explicit adoption exists for the historical schema reference")

    @staticmethod
    def validate_historical(payload: Mapping[str, Any], schema: Mapping[str, Any], adoption: Optional[SchemaAdoption]) -> Mapping[str, Any]:
        if adoption is None or not adoption.adopted:
            raise SchemaAdoptionRequiredError("historical payload validation requires explicit schema adoption")
        # The source mapping is copied, not normalized.  Unknown fields remain
        # readable even when the adopted schema does not mention them.
        validate_json_schema(payload, schema)
        return dict(payload)

    def _create_manifest(self, role: str, manifest: Mapping[str, Any], context: TransactionContext, *, visibility: str = "private", maintainer: Optional[str] = None) -> Mapping[str, Any]:
        writer = self._require_writer()
        if role not in {"candidate-manifest", "decision-manifest"}:
            raise PacketError("unsupported manifest role")
        value = dict(manifest)
        _json(value, "manifest")
        required = ("candidate_id", "manifest_revision", "owner", "resource", "provenance") if role == "candidate-manifest" else ("decision_id", "subject", "author", "authority", "question", "rationale", "return_condition")
        missing = [name for name in required if name not in value]
        if missing:
            raise PacketError("manifest missing required fields: " + ", ".join(missing))
        if role == "candidate-manifest" and value.get("role") != "candidate":
            raise PacketError("candidate manifest role must be candidate")
        for key in ("resource", "subject", "authority"):
            if key in value:
                ref = value[key] if isinstance(value[key], ResourceRef) else ResourceRef.from_dict(value[key])
                self._ensure_storable_reference(ref, key)
        identifier = value.get("candidate_id", value.get("decision_id"))
        refs = []
        for key in ("output_refs", "source_refs", "input_refs", "criteria_refs", "candidate_refs", "evidence_refs"):
            for item in value.get(key, ()):
                ref = item if isinstance(item, ResourceRef) else ResourceRef.from_dict(item)
                if ref.revision is None:
                    raise PacketError(f"manifest reference {key} must be pinned")
                self._ensure_storable_reference(ref, key)
                refs.append(ref)
        document_ref = ResourceRef(writer.authority, MANIFEST_KIND, f"{role}:{identifier}")
        existing = writer.get_identity(document_ref)
        if existing is not None and not (hasattr(writer, "get_receipt") and writer.get_receipt(context.logical_request_key) is not None):
            raise ImmutableManifestError(f"{role} already exists and is immutable: {identifier}")
        author_value = value.get("author")
        fallback_maintainer = _actor_id(author_value) if isinstance(author_value, (str, AuthenticatedActor)) else "manifest-owner"
        document = ContentDocument(document_ref, role, visibility, "read", maintainer or value.get("owner", fallback_maintainer))
        revision = ContentRevision(document_ref, str(value.get("manifest_revision", value.get("decision_revision", "1"))), value, context.actor, initial=True)
        handler = self._content
        receipt = handler.execute(handler.build_create_document(context, document, revision))
        for ref in refs:
            writer.put_reference(ref)
        return {"document_ref": document_ref, "revision_ref": revision.ref, "receipt": receipt, "manifest": value, "role": role}

    def _ensure_storable_reference(self, ref: ResourceRef, field: str) -> None:
        writer = self._require_writer()
        if ref.authority != writer.authority:
            raise PacketError(f"{field} must point to an identity in this Store")
        identity = writer.get_identity(ResourceRef(ref.authority, ref.kind, ref.id))
        if identity is None:
            raise UnresolvedReferenceError(f"{field} is not an admitted identity: {ref.to_json()}")
        if ref.revision is None:
            raise PacketError(f"{field} must be pinned")
        if isinstance(identity.payload.get("document"), Mapping):
            if writer.get_identity(revision_identity(ResourceRef(ref.authority, ref.kind, ref.id), ref.revision)) is None:
                raise UnresolvedReferenceError(f"{field} revision is not admitted: {ref.to_json()}")
        elif identity.ref.revision != ref.revision:
            raise UnresolvedReferenceError(f"{field} revision is not the admitted revision: {ref.to_json()}")

    def register_candidate(self, manifest: Mapping[str, Any], context: TransactionContext, *, visibility: str = "private") -> Mapping[str, Any]:
        return self._create_manifest("candidate-manifest", manifest, context, visibility=visibility, maintainer=manifest.get("owner"))

    create_candidate = register_candidate

    def register_decision(self, manifest: Mapping[str, Any], context: TransactionContext, *, visibility: str = "private") -> Mapping[str, Any]:
        author_value = manifest.get("author")
        maintainer = _actor_id(author_value) if isinstance(author_value, (str, AuthenticatedActor)) else context.actor.actor
        return self._create_manifest("decision-manifest", manifest, context, visibility=visibility, maintainer=maintainer)

    create_decision = register_decision

    def notify_amendment(self, document: Any, amended_revision: ResourceRef, owners: Iterable[str], context: TransactionContext, *, reason: str = "shared-document-amended", packet_refs: Iterable[ResourceRef] = ()) -> Tuple[Mapping[str, Any], ...]:
        writer = self._require_writer()
        document_ref, _ = _binding_parts(document, "document")
        if amended_revision.revision is None or not _same_identity(document_ref, amended_revision):
            raise PacketError("amendment must identify the same document and a concrete revision")
        results = []
        for owner in _tuple_text(owners, "owners"):
            dedupe = "attention-" + sha256(canonical_json({"document": document_ref, "revision": amended_revision, "owner": owner, "reason": reason}).encode()).hexdigest()[:24]
            target = ResourceRef(writer.authority, ATTENTION_KIND, dedupe)
            owner_context = TransactionContext(context.actor, f"{context.logical_request_key}:{owner}", context.request_digest, correlation_id=context.correlation_id, causation_id=context.causation_id)
            envelope = CommandEnvelope("dat.context.attention.create", PACKET_SCHEMA_REVISION, target, owner_context, {"record_type": ATTENTION_KIND, "recipient": owner, "cause": reason, "subject": document_ref, "amended_revision": amended_revision, "packet_refs": tuple(packet_refs), "state": "open"})
            with writer.transaction() as transaction:
                receipt = writer.mutate(envelope, event_type="dat.context.attention.created", result_ref=ResourceRef(writer.authority, ATTENTION_KIND, dedupe, "attention-1"), after_refs=(amended_revision,), effects={"recipient": owner, "cause": reason, "subject": document_ref, "amended_revision": amended_revision, "packet_refs": tuple(packet_refs), "state": "open"}, transaction=transaction)
            results.append({"recipient": owner, "attention_ref": target, "receipt": receipt, "state": "open"})
        return tuple(results)

    notify_document_amendment = notify_amendment
    amend_notification = notify_amendment

    def list_attention(self, recipient: Optional[str] = None) -> Tuple[Mapping[str, Any], ...]:
        latest: dict[str, Mapping[str, Any]] = {}
        for event in self._require_writer().list_events():
            if event.event_type not in {"dat.context.attention.created", "dat.context.attention.resolved"}:
                continue
            effects = dict(event.effects)
            if recipient is not None and effects.get("recipient") != recipient:
                continue
            key = event.subject.id
            latest[key] = {"attention_ref": event.subject, "recipient": effects.get("recipient"), "cause": effects.get("cause"), "subject": effects.get("subject"), "amended_revision": effects.get("amended_revision"), "packet_refs": effects.get("packet_refs", ()), "state": effects.get("state", "open"), "event_id": event.event_id}
        return tuple(item for item in latest.values() if item.get("state") == "open")

    unresolved_attention = list_attention

    def responsibility_view(self, packet: Any, context: Optional[VisibilityContext] = None, *, actor: Any = None, roles: Iterable[str] = (), scopes: Iterable[ResourceRef] = (), cursor: Optional[EventCursor] = None) -> Mapping[str, Any]:
        value = self.read_packet(packet, context, actor=actor, roles=roles, scopes=scopes)["content"]
        responsibility = dict(value.get("responsibility", {}))
        provenance = dict(value.get("provenance", {}))
        refs = tuple(item.get("resolved_ref") for item in value.get("inputs", ()) if item.get("resolved_ref") is not None)
        events = tuple(self._require_writer().list_events())
        if cursor is None:
            delta = tuple(event.event_id for event in events if event.subject in refs)
        else:
            delta = tuple(event.event_id for event in events if event.stream == cursor.stream and event.sequence > cursor.sequence)
        allowed = {"mandate", "outcome", "adopted", "adopted_task", "adopted_protocol", "profile", "criteria_refs", "missing_prerequisites", "open_decisions", "evidence_links", "supported_operations", "scope_coverage", "omissions"}
        bounded = {key: responsibility.get(key, ()) for key in allowed}
        bounded["mandate"] = responsibility.get("mandate")
        bounded["outcome"] = responsibility.get("outcome")
        bounded["adopted"] = responsibility.get("adopted", {})
        bounded["adopted_task"] = responsibility.get("adopted_task")
        bounded["adopted_protocol"] = responsibility.get("adopted_protocol")
        bounded["profile"] = responsibility.get("profile")
        bounded["criteria_refs"] = responsibility.get("criteria_refs", ())
        bounded["cursor_delta"] = delta
        bounded["provenance"] = provenance
        bounded["scope_coverage"] = responsibility.get("scope_coverage", ())
        bounded["omissions"] = responsibility.get("omissions", ())
        bounded["missing_prerequisites"] = responsibility.get("missing_prerequisites", ())
        bounded["open_decisions"] = responsibility.get("open_decisions", ())
        bounded["evidence_links"] = responsibility.get("evidence_links", ())
        bounded["supported_operations"] = responsibility.get("supported_operations", ())
        bounded["inputs"] = refs
        # Deliberately no raw revision content, transcript, or private
        # reasoning is copied into this read-only view.
        return bounded

    responsibility = responsibility_view
    resolve_responsibility = responsibility_view


PacketService = ContextPacketService
ContextPackets = ContextPacketService


__all__ = [
    "AccessContext", "AccessDeniedError", "ATTENTION_KIND", "ConflictingAuthorityError",
    "ContextInput", "ContextPacket", "ContextPacketService", "ContextPackets", "FNDPacketWriter",
    "ImmutableManifestError", "PACKET_KIND", "PACKET_SCHEMA_REVISION", "PacketActor",
    "PacketError", "PacketInput", "PacketService", "SchemaAdoption",
    "SchemaAdoptionRequiredError", "UnresolvedReferenceError", "VisibilityContext",
]
