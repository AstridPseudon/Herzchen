from __future__ import annotations

import hashlib
from contextlib import contextmanager

import pytest

from herzchen.authoring import AuthoringLifecycle, AuthoringSessionService, FileWriterLeaseAuthority, domain_contribution as authoring_contribution
from herzchen.content import ContentCommandHandler, ContentDocument, ContentRevision, domain_contribution as content_contribution
from herzchen.contracts import AuthenticatedActor, AuthoringState, CleanupStatus, ResourceRef, TransactionContext, canonical_json
from herzchen.extensions import ExtensionCommandService, MANAGED_NAMESPACE, OPEN_NAMESPACE, ManagedFieldError, domain_contribution as extension_contribution
from herzchen.kernel import DomainOwnerCapability, RuntimeDomainOwner, RuntimeOperationReader, Store, StoreAdmissionError, TargetMismatchError
from herzchen.packs.authoring import ManagedPack, ManagedPackAuthoringHandler, ManagedResource, ManagedSourceIdentity, domain_contribution as pack_contribution


def _actor() -> AuthenticatedActor:
    return AuthenticatedActor("dat-auth", "runtime-dat", "credential")


class _RuntimeReader(RuntimeOperationReader):
    __slots__ = ("_reader",)

    def __init__(self, reader):
        self._reader = reader

    @property
    def domain_descriptor_digest(self):
        return self._reader.domain_descriptor_digest

    def registered_domains(self):
        return self._reader.registered_domains()

    def get_identity(self, ref):
        return self._reader.get_identity(ref)

    def get_receipt(self, key):
        return self._reader.get_receipt(key)

    def list_events(self, *, stream=None):
        return self._reader.list_events(stream=stream)


class _ForeignDomainOwner(RuntimeDomainOwner):
    __slots__ = ("_store", "_handler", "_reader")

    def __init__(self, store, handler):
        self._store = store
        self._handler = handler
        self._reader = _RuntimeReader(store.consumer())

    @property
    def authority(self):
        return self._store.authority

    @property
    def domain_descriptor_digest(self):
        return self._store.domain_descriptor_digest

    def consumer(self):
        return self._reader

    def registered_domains(self):
        return self._store.registered_domains()

    def transaction(self):
        return self._store.transaction()

    def mutate(self, envelope, **kwargs):
        return self._handler.mutate(envelope, **kwargs)

    def put_identity(self, *args, **kwargs):
        return self._handler.put_identity(*args, **kwargs)

    def put_reference(self, *args, **kwargs):
        return self._handler.put_reference(*args, **kwargs)

    def get_identity(self, ref):
        return self._store.get_identity(ref)

    def get_receipt(self, key):
        return self._store.get_receipt(key)

    def list_events(self, *, stream=None):
        return self._store.list_events(stream=stream)

    def register_domain(self, contribution, **kwargs):
        return self._store.register_domain(contribution, **kwargs)


def _context(key: str, payload: object, *, version: int = 0, revision: str | None = None) -> TransactionContext:
    digest = hashlib.sha256(canonical_json(payload).encode()).hexdigest()
    return TransactionContext(_actor(), key, digest, expected_version=version, expected_revision=revision)


def test_foreign_domain_capability_runs_content_lifecycle_without_second_store(tmp_path):
    store = Store.create(tmp_path / "foreign-domain.sqlite3", authority="dat-store")
    try:
        with pytest.raises(StoreAdmissionError):
            DomainOwnerCapability.issue_runtime(object(), "dat.content")
        handler = store.register_domain_handler((content_contribution(), extension_contribution()))
        owner = _ForeignDomainOwner(store, handler)
        content_cap = DomainOwnerCapability.issue_runtime(owner, "dat.content")
        assert content_cap.domain_id == "dat.content"
        assert content_cap.consumer() is owner.consumer()
        with pytest.raises(StoreAdmissionError):
            content_cap.issue_command_port(object(), "dat.extensions", ("read",))

        service = ContentCommandHandler(owner)
        document = ContentDocument(
            ResourceRef("dat-store", "project.specification", "foreign-doc"),
            "initial-specification", "private", "append", "runtime-dat",
        )
        revision = ContentRevision(document.ref, "rev-1", {"title": "foreign owner"}, _actor(), initial=True)
        receipt = service.execute(service.build_create_document(_context("foreign-create", {"title": "foreign owner"}), document, revision))
        assert receipt.status.value == "committed"
        assert service.read(document.ref)["revision"]["content"] == {"title": "foreign owner"}
    finally:
        store.close()


def test_foreign_domain_capability_runs_extension_admission_and_rejects_managed_fields(tmp_path):
    store = Store.create(tmp_path / "foreign-extension.sqlite3", authority="dat-store")
    subject = ResourceRef("dat-store", "work.task", "foreign-task", "seed-1")
    try:
        handler = store.register_domain_handler((content_contribution(), extension_contribution()))
        owner = _ForeignDomainOwner(store, handler)
        store.put_identity(
            subject,
            {"metadata": {MANAGED_NAMESPACE: {"identity": "protected"}, "annotation.sibling": {"keep": True}}},
            version=1,
        )
        service = ExtensionCommandService(owner)
        result = service.set(subject, OPEN_NAMESPACE, {"note": "foreign owner"}, _context("foreign-extension", {"note": "foreign owner"}, version=1, revision="seed-1"))
        assert result["metadata"][OPEN_NAMESPACE]["note"] == "foreign owner"
        with pytest.raises(ManagedFieldError):
            service.set(subject, MANAGED_NAMESPACE, {"identity": "spoof"}, _context("foreign-managed", {"identity": "spoof"}, version=result["version"], revision=result["revision"]))
    finally:
        store.close()


def test_foreign_domain_capability_runs_managed_pack_authoring_and_pinned_readback(tmp_path):
    pack_root = tmp_path / "pack"
    pack_root.mkdir()
    manifest = pack_root / "pack.yaml"
    manifest.write_text("{}", encoding="utf-8")
    source = ManagedSourceIdentity(
        "foreign-pack", "managed", "1" * 40, "2" * 64,
        hashlib.sha256(manifest.read_bytes()).hexdigest(), "3" * 64,
        str(pack_root), str(manifest),
    )
    original = b"original\n"
    resource = ManagedResource(
        "skill.md", "skill", original, hashlib.sha256(original).hexdigest(),
        ResourceRef("astrid-managed", "managed_pack", "foreign-pack", "1" * 40),
    )
    pack = ManagedPack("foreign-pack", "1", source, {"schema_version": 2}, (resource,), (), ())
    store = Store.create(tmp_path / "foreign-pack.sqlite3", authority="pkg-store")
    try:
        handler = store.register_domain_handler((pack_contribution(),))
        owner = _ForeignDomainOwner(store, handler)
        service = ManagedPackAuthoringHandler(owner)
        actor = AuthenticatedActor("pkg-auth", "runtime-pack", "credential")
        first = service.author(pack, {"skill.md": b"first\n"}, logical_request_key="pack-first", actor=actor)
        second = service.author(pack, {"skill.md": b"second\n"}, logical_request_key="pack-second", actor=actor)
        assert second.revision != first.revision
        assert service.read("foreign-pack", revision=first.revision)["resources"]["skill.md"]["content_b64"]
        assert service.read("foreign-pack")["resources"]["skill.md"]["content_b64"] != service.read("foreign-pack", revision=first.revision)["resources"]["skill.md"]["content_b64"]
    finally:
        store.close()


def test_foreign_domain_capability_runs_shared_authoring_release_and_cleanup(tmp_path):
    store = Store.create(tmp_path / "foreign-authoring.sqlite3", authority="edt-store")
    try:
        handler = store.register_domain_handler((authoring_contribution(),))
        owner = _ForeignDomainOwner(store, handler)
        service = AuthoringSessionService(owner)
        target = ResourceRef(store.authority, "project", "foreign-authoring")
        actor = AuthenticatedActor(store.authority, "runtime-edt", "credential")

        opened = service.open(
            target, actor, request_id="foreign-authoring-open", target_kind="document",
            base_revision="initial", initial_content=b"draft",
        )
        assert opened.handle is not None
        released = service.release(opened.handle, request_id="foreign-authoring-release")
        assert released.status == "released"
        assert released.checkout is not None
        assert released.checkout.state == AuthoringState.RELEASED

        # The durable cleanup transition is the retry boundary.  Physical
        # file deletion remains owned by AuthoringLifecycle and its lease.
        cleaned = service.cleanup(
            opened.handle, request_id="foreign-authoring-cleanup",
            status=CleanupStatus.PENDING,
        )
        assert cleaned.cleanup == CleanupStatus.PENDING
        assert service.read(target).status == "available"

        with pytest.raises(StoreAdmissionError):
            DomainOwnerCapability.issue_runtime(owner, "herzchen.packs.authoring")
        capability = DomainOwnerCapability.issue_runtime(owner, "herzchen.authoring.sessions")
        with pytest.raises(TargetMismatchError):
            capability.put_reference(ResourceRef("other-runtime", "authoring-snapshot", "foreign"))
    finally:
        store.close()


def test_foreign_domain_capability_runs_shared_lifecycle_physical_cleanup(tmp_path):
    class Handler:
        def validate(self, snapshot, checkout, checkout_root):
            return True

        def apply(self, snapshot, checkout, tx, writer):
            return {"digest": snapshot.digest}

    store = Store.create(tmp_path / "foreign-lifecycle.sqlite3", authority="edt-lifecycle")
    try:
        handler = store.register_domain_handler((authoring_contribution(),))
        owner = _ForeignDomainOwner(store, handler)
        service = AuthoringSessionService(owner)
        leases = FileWriterLeaseAuthority(
            tmp_path / "writer-locks", authority="foreign-lifecycle-host",
            secret=b"foreign-lifecycle-writer-authority-key!", writer_identities=("editor",),
        )
        lifecycle = AuthoringLifecycle(service, writer_leases=leases, writer_identity="editor")
        target = ResourceRef(store.authority, "project", "foreign-lifecycle")
        actor = AuthenticatedActor(store.authority, "runtime-edt", "credential")
        checkout_root = tmp_path / "checkout"
        checkout_root.mkdir()
        draft = checkout_root / "draft.txt"
        draft.write_bytes(b"foreign lifecycle")

        opened = lifecycle.open(
            target, actor, request_id="foreign-lifecycle-open", target_kind="project",
            base_revision="initial", initial_content=b"foreign lifecycle",
        )
        finished = lifecycle.finish(
            opened, request_id="foreign-lifecycle-finish", mode="manual",
            checkout_root=checkout_root, registered_files=["draft.txt"],
            handler=Handler(), writer_check=lambda: True,
        )
        assert finished.status == "finished", finished.finish.error
        assert finished.cleanup is not None and finished.cleanup.status == CleanupStatus.COMPLETE
        assert not draft.exists()
        record = store.get_identity(opened.handle.scope)
        assert record.payload["checkout"]["cleanup"] == CleanupStatus.COMPLETE.value
        assert service.read(target).status == "available"
    finally:
        store.close()
