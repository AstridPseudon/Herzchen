"""PKG-03 template resources exercised through FND and WRK public APIs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from herzchen.content import ContentCommandHandler
from herzchen.content.model import domain_contribution as content_contribution
from herzchen.contracts import AuthenticatedActor, ReferenceBinding, ReplayConflictError, ResourceRef
from herzchen.authoring.finish import SemanticFinishAdapter
from herzchen.authoring.idle import IdleCloseService
from herzchen.authoring.sessions import AuthoringSessionService, register_authoring
from herzchen.domains.work import WorkGraph, WorkKind
from herzchen.kernel import Store
from herzchen.packs.templates import (
    CRITERION_NAMESPACE,
    TASK_NAMESPACE,
    TemplateEngine,
    TemplateCycleError,
    TemplateReferenceError,
    TemplateValidationError,
    WorkProtocol,
    blank_project_template,
    render_blank_project,
    render_template,
    work_protocol,
    work_template,
)


@pytest.fixture
def harness(tmp_path):
    store = Store.create(tmp_path / "pkg03.sqlite", authority="pkg03-test")
    actor = AuthenticatedActor("pkg03-test", "tester", "test-credential")
    graph = WorkGraph(store, actor=actor)
    graph.register()
    store.register_domain(content_contribution())
    register_authoring(store)
    engine = TemplateEngine(store, graph=graph, actor=actor)
    try:
        yield store, graph, engine, actor
    finally:
        store.close()


def _shipped_delivery():
    root = Path(__file__).resolve().parents[2]
    data = json.loads((root / "packs/megado/templates/delivery.json").read_bytes())
    return work_template(data["id"], data["version"], parameters=data["parameters"], seed=data["seed"])


def _shipped_delivery_data():
    root = Path(__file__).resolve().parents[2]
    return json.loads((root / "packs/megado/templates/delivery.json").read_bytes())


def _durable_counts(store):
    counts = {}
    for table in ("identities", "record_references", "command_receipts", "events", "event_sequences"):
        counts[table] = store.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    return counts


def test_shipped_delivery_seed_work_is_expanded_from_real_resource(harness):
    store, graph, engine, _ = harness
    project = graph.create_project(title="Owner", outcome="Import", logical_request_key="owner")
    template = _shipped_delivery()
    engine.register(template)
    result = engine.instantiate(template.id, {"title": "Ship", "outcome": "Build", "proof": "Check"}, project=project, logical_request_key="delivery")
    assert result.project.ref == project.ref
    assert set(result.local_refs) == {"effort", "implement", "verify", "criterion"}
    assert {record.kind for record in result.records} == {WorkKind.EFFORT, WorkKind.TASK, WorkKind.CRITERION}
    by_id = {record.payload["fields"]["template_origin"]["local_id"]: record for record in result.records}
    assert by_id["effort"].title == "Ship"
    assert by_id["effort"].payload["fields"]["outcome"] == "Build"
    assert by_id["effort"].payload["fields"]["status"] == "planning_only"
    assert by_id["effort"].payload["fields"]["namespace"] == "work"
    assert by_id["effort"].payload["fields"]["documents"] == [{"local_id": "goal", "title": "Bounded goal", "content": "Build"}]
    assert by_id["effort"].payload["fields"]["document_links"] == [{
        "subject": {"$local": "effort"}, "document": {"$local": "goal"},
        "namespace": "megado", "key": "goal", "binding": "current",
    }]
    assert by_id["implement"].payload["fields"]["outcome"] == "Build"
    assert by_id["implement"].payload["fields"]["custom"] == {"megado": {"execution_class": "normal"}}
    assert by_id["implement"].payload["fields"]["namespace"] == "work.tasks"
    assert by_id["implement"].payload["fields"]["key"] == "implement"
    assert by_id["implement"].payload["fields"]["links"] == [{
        "from": {"$local": "implement"}, "to": {"$local": "criterion"}, "relation": "covers",
    }]
    assert by_id["verify"].payload["fields"]["custom"] == {"megado": {"execution_class": "normal"}}
    assert by_id["verify"].payload["fields"]["links"] == [{
        "from": {"$local": "verify"}, "to": {"$local": "implement"}, "relation": "requires",
    }]
    assert by_id["criterion"].payload["fields"]["outcome"] == "Check"
    assert by_id["criterion"].payload["fields"]["namespace"] == "work.criteria"
    assert by_id["implement"].parent.id == by_id["effort"].id
    assert by_id["verify"].parent.id == by_id["effort"].id
    assert by_id["criterion"].parent.id == by_id["effort"].id
    assert tuple(dependency.id for dependency in by_id["verify"].dependencies) == (by_id["implement"].id,)
    assert by_id["implement"].dependencies == ()
    assert result.rendered.seed["work"][0]["title"] == "Ship"
    assert result.rendered.seed["work"][0]["outcome"] == "Build"
    assert result.rendered.seed["documents"][0]["content"] == "Build"
    assert result.document_refs["goal"].kind == "dat.content.document"
    assert result.document_refs["goal"].revision is None
    assert result.association_refs["effort:megado:goal"].kind == "document-association"
    assert len(result.dat_receipts) == 2
    assert {receipt.operation for receipt in result.dat_receipts} == {"dat.content.document.create", "dat.content.link"}
    document_read = ContentCommandHandler(store).read(result.document_refs["goal"])
    assert document_read["document"]["role"] == "template-document"
    assert document_read["document"]["visibility"] == "private"
    assert document_read["document"]["authoring_scope"] == project.ref.to_dict()
    assert document_read["revision"]["content"] == "Build"
    association_read = ContentCommandHandler(store).read(result.association_refs["effort:megado:goal"])
    assert association_read["payload"]["association"]["document"]["ref"] == result.document_refs["goal"].to_dict()
    assert association_read["payload"]["association"]["document"]["mode"] == "current"
    assert association_read["payload"]["active"] is True
    assert len(result.receipts) == 6
    assert all(receipt.status.value == "committed" and receipt.event_ids for receipt in result.receipts)
    assert len(store.list_events()) == 7
    document_receipt, link_receipt = result.dat_receipts
    assert document_receipt.result_ref.revision == document_read["current_revision"]["revision"]
    assert link_receipt.target == result.association_refs["effort:megado:goal"]

    expected_domains = store.registered_domains()
    store.close()
    reopened = Store.open(store.path, authority=store.authority, expected_domains=expected_domains)
    try:
        reopened_content = ContentCommandHandler(reopened)
        assert reopened_content.read(result.document_refs["goal"])["revision"]["content"] == "Build"
        assert reopened_content.read(result.association_refs["effort:megado:goal"])["payload"]["active"] is True
    finally:
        reopened.close()


def test_shipped_delivery_is_idempotent_and_conflicts_on_changed_parameters(harness):
    store, graph, engine, _ = harness
    project = graph.create_project(title="Owner", outcome="Import", logical_request_key="owner")
    template = _shipped_delivery()
    first = engine.instantiate(template, {"title": "Ship", "outcome": "Build", "proof": "Check"}, project=project, logical_request_key="delivery")
    before_replay = _durable_counts(store)
    events_before_replay = store.list_events()
    replay = engine.instantiate(template, {"title": "Ship", "outcome": "Build", "proof": "Check"}, project=project, logical_request_key="delivery")
    assert replay.project.ref == first.project.ref
    assert [x.ref for x in replay.records] == [x.ref for x in first.records]
    assert replay.local_refs == first.local_refs
    assert replay.document_refs == first.document_refs
    assert replay.association_refs == first.association_refs
    assert replay.receipts == first.receipts
    assert tuple(receipt.logical_request_key for receipt in replay.receipts) == tuple(receipt.logical_request_key for receipt in first.receipts)
    assert _durable_counts(store) == before_replay
    assert store.list_events() == events_before_replay
    before_conflict = (graph.list(), store.list_events(), _durable_counts(store))
    with pytest.raises(ReplayConflictError):
        engine.instantiate(template, {"title": "Changed", "outcome": "Build", "proof": "Check"}, project=project, logical_request_key="delivery")
    assert (graph.list(), store.list_events(), _durable_counts(store)) == before_conflict


@pytest.mark.parametrize("mutation, error", [
    (lambda data: data["seed"].update(work="not-a-list"), TemplateValidationError),
    (lambda data: data["seed"]["work"][0].pop("local_id"), TemplateValidationError),
    (lambda data: data["seed"]["work"].append(dict(data["seed"]["work"][0])), TemplateValidationError),
    (lambda data: data["seed"]["links"][0].update(to={"$local": "missing"}), TemplateReferenceError),
    (lambda data: data["seed"]["links"][0].update(relation="blocks"), TemplateValidationError),
    (lambda data: data["seed"]["document_links"][0].update(document={"$local": "missing"}), TemplateReferenceError),
    (lambda data: data["seed"]["document_links"][0].update(binding="pinned"), TemplateValidationError),
    (lambda data: data["seed"]["documents"][0].update(visibility="not-a-visibility"), TemplateValidationError),
    (lambda data: data["seed"]["documents"][0].update(role={"not": "text"}), TemplateValidationError),
    (lambda data: data["seed"]["document_links"][0].update(document={"authority": "pkg03-test", "kind": "dat.content.document", "id": "missing"}), TemplateReferenceError),
])
def test_invalid_shipped_shape_writes_nothing(harness, mutation, error):
    store, graph, engine, _ = harness
    project = graph.create_project(title="Owner", outcome="Import", logical_request_key="owner")
    data = _shipped_delivery_data()
    mutation(data)
    bad = work_template(data["id"] + ".bad", data["version"], parameters=data["parameters"], seed=data["seed"])
    before = (graph.list(), store.list_events(), _durable_counts(store))
    with pytest.raises(error):
        engine.instantiate(bad, {"title": "Ship", "outcome": "Build", "proof": "Check"}, project=project, logical_request_key="bad")
    assert (graph.list(), store.list_events(), _durable_counts(store)) == before


def test_document_association_failure_rolls_back_work_and_dat_savepoints(harness, monkeypatch):
    store, graph, engine, _ = harness
    project = graph.create_project(title="Owner", outcome="Import", logical_request_key="owner")
    template = _shipped_delivery()
    before = (graph.list(), store.list_events(), _durable_counts(store))
    original_execute = ContentCommandHandler.execute

    def fail_link(handler, envelope):
        if envelope.operation == "dat.content.link":
            raise RuntimeError("injected DAT association failure")
        return original_execute(handler, envelope)

    monkeypatch.setattr(ContentCommandHandler, "execute", fail_link)
    with pytest.raises(RuntimeError, match="injected DAT association failure"):
        engine.instantiate(template, {"title": "Ship", "outcome": "Build", "proof": "Check"}, project=project, logical_request_key="association-failure")
    assert (graph.list(), store.list_events(), _durable_counts(store)) == before
    assert store.connection.execute("SELECT COUNT(*) FROM identities WHERE kind LIKE 'dat.content.%'").fetchone()[0] == 0


def test_typed_external_document_is_validated_and_linked_without_local_materialization(harness):
    store, graph, engine, actor = harness
    project = graph.create_project(title="Owner", outcome="Import", logical_request_key="owner")
    content = ContentCommandHandler(store)
    external = ResourceRef(store.authority, "dat.content.document", "existing-document")
    from herzchen.content import ContentDocument, ContentRevision
    from herzchen.contracts import TransactionContext

    document = ContentDocument(external, "source", "shared", "append", actor.actor, project.ref)
    revision = ContentRevision(external, "source-rev", {"body": "existing"}, actor, initial=True)
    content.execute(content.build_create_document(TransactionContext(actor, "external-create", "1" * 64, expected_version=0), document, revision))
    template = work_template(
        "external-document",
        seed={
            "tasks": [{"local_id": "task", "title": "Task"}],
            "documents": [{"ref": external.to_dict()}],
            "document_links": [{"subject": {"$local": "task"}, "document": external.to_dict(), "namespace": "megado", "key": "source", "binding": "current"}],
        },
    )
    result = engine.instantiate(template, project=project, logical_request_key="external-document")
    assert result.document_refs == {}
    assert len(result.dat_receipts) == 1
    assert store.get_identity(external) is not None
    association = next(iter(result.association_refs.values()))
    assert content.read(association)["payload"]["association"]["document"]["ref"] == external.to_dict()


def test_existing_plural_seed_shape_remains_compatible(harness):
    _, graph, engine, _ = harness
    project = graph.create_project(title="Owner", outcome="Import", logical_request_key="owner")
    template = work_template("legacy-shape", seed={"tasks": [{"local_id": "task", "title": "Still works"}]})
    result = engine.instantiate(template, project=project, logical_request_key="legacy")
    assert [record.title for record in result.records] == ["Still works"]


def test_blank_resource_persists_pending_project_initial_spec_and_association(harness):
    store, graph, engine, _ = harness

    rendered = render_blank_project()
    assert rendered["project"]["title"] == "Untitled project"
    assert rendered["project"]["outcome"] == ""
    assert rendered["tasks"] == []
    static_seed = render_template(blank_project_template()).seed
    assert static_seed["tasks"] == []
    assert static_seed["documents"] == []
    assert static_seed.get("document_links", []) == []

    result = engine.instantiate("work.blank_project", logical_request_key="blank")
    project = graph.get(result.project.ref)
    assert project.kind is WorkKind.PROJECT
    assert project.payload["tasks"] == []
    assert project.payload["protocol"] is None
    assert project.payload["manager"] is None
    assert project.payload["budget"] is None
    assert project.payload["readiness"]["dispatch"] is False
    assert len(graph.list()) == 1
    assert result.local_refs == {"project": project.ref}
    assert set(result.document_refs) == {"initial-specification"}
    assert set(result.association_refs) == {"project:project.documents:specification"}
    document = ContentCommandHandler(store).read(result.document_refs["initial-specification"])
    assert document["document"]["role"] == "initial-specification"
    assert document["revision"]["initial"] is True
    assert document["revision"]["parent_revision"] is None
    expected_content = dict(rendered["project"])
    expected_content["tasks"] = rendered["tasks"]
    expected_content["metadata"] = {
        "template_ref": blank_project_template().ref.to_dict(),
        "template_revision": blank_project_template().revision,
        "projection_schema": "pending-project-sheet/v1",
    }
    assert document["revision"]["content"] == expected_content
    association = ContentCommandHandler(store).read(result.association_refs["project:project.documents:specification"])
    assert association["payload"]["active"] is True
    assert association["payload"]["association"]["subject"] == project.ref.to_dict()
    assert association["payload"]["association"]["document"]["ref"] == result.document_refs["initial-specification"].to_dict()
    assert len(result.receipts) == 3
    assert all(receipt.event_ids for receipt in result.receipts)
    assert len(store.list_events()) == 3


def test_blank_creation_replays_conflicts_and_rejects_invalid_input_before_mutation(harness):
    store, graph, engine, _ = harness
    first = engine.instantiate("work.blank_project", {"title": "A title"}, logical_request_key="blank")
    events = store.list_events()
    receipts = tuple(store.get_receipt(receipt.logical_request_key) for receipt in first.receipts)
    replay = engine.instantiate("work.blank_project", {"title": "A title"}, logical_request_key="blank")
    assert replay.project.ref == first.project.ref
    assert replay.document_refs == first.document_refs
    assert replay.association_refs == first.association_refs
    assert replay.receipts == first.receipts
    assert store.list_events() == events
    assert tuple(store.get_receipt(receipt.logical_request_key) for receipt in replay.receipts) == receipts
    with pytest.raises(ReplayConflictError):
        engine.instantiate("work.blank_project", {"title": "Changed"}, logical_request_key="blank")
    assert store.list_events() == events
    assert tuple(store.get_receipt(receipt.logical_request_key) for receipt in first.receipts) == receipts

    invalid_store = Store.create(harness[0].path + ".invalid", authority="pkg03-invalid")
    invalid_graph = WorkGraph(invalid_store, actor=harness[3])
    invalid_graph.register()
    try:
        invalid_engine = TemplateEngine(invalid_store, graph=invalid_graph, actor=harness[3])
        with pytest.raises(TemplateValidationError):
            invalid_engine.instantiate("work.blank_project", {"title": ""}, logical_request_key="invalid")
        assert invalid_graph.list() == ()
        assert invalid_store.list_events() == ()
        assert invalid_store.get_receipt("invalid:project") is None
    finally:
        invalid_store.close()


def test_blank_initial_spec_untouched_pending_close_retains_durable_content_and_cleans_registered_files(harness, tmp_path):
    store, graph, engine, actor = harness
    result = engine.instantiate("work.blank_project", logical_request_key="close-blank", actor=actor)
    document_ref = result.document_refs["initial-specification"]
    initial = ContentCommandHandler(store).read(document_ref)
    initial_bytes = json.dumps(initial["revision"]["content"], sort_keys=True, separators=(",", ":")).encode()
    service = AuthoringSessionService(store)
    opened = service.open(
        result.project.ref, actor, request_id="close-open", target_kind="project-sheet",
        base_revision=result.project.revision, initial_content=initial_bytes, pending=True,
    )
    root = tmp_path / "checkout"
    root.mkdir()
    (root / "project.json").write_bytes(initial_bytes)
    idle = IdleCloseService(SemanticFinishAdapter(service), clock=lambda: 10.0)
    closed = idle.close_if_idle(
        opened.handle, request_id="close-idle", checkout_root=root,
        registered_files=["project.json"], inactivity_seconds=1, last_content_edit=0, now=10,
        quiesce=lambda: True, writer_check=lambda: True,
    )
    assert closed.status == "closed_cleaned"
    assert not (root / "project.json").exists()
    assert service.read(result.project.ref).status == "available"
    fresh_project = graph.get(result.project.ref)
    assert fresh_project.payload["tasks"] == []
    assert fresh_project.revision == result.project.revision
    fresh_document = ContentCommandHandler(store).read(document_ref)
    assert fresh_document["current_revision"]["revision"] == initial["current_revision"]["revision"]
    assert ContentCommandHandler(store).read(result.association_refs["project:project.documents:specification"])["payload"]["active"] is True


def test_bundle_is_literal_idempotent_and_retains_origin_namespaces_and_review(harness):
    store, graph, engine, _ = harness
    project = engine.instantiate("work.blank_project", logical_request_key="owner").project
    template = work_template(
        "independent.template",
        revision="tree-17",
        parameters={
            "type": "object", "required": ["title"],
            "properties": {"title": {"type": "string"}},
        },
        seed={
            "namespaces": {"task": "named.tasks", "criterion": "named.criteria"},
            "tasks": [{
                "local_id": "task-local", "key": "same-visible-key",
                "title": {"$param": "title"}, "review_choice": "normal",
                "namespace": "named.tasks",
            }],
            "criteria": [{
                "local_id": "criterion-local", "key": "same-visible-key",
                "title": "Criterion", "parent": {"$local": "task-local"},
                "namespace": "named.criteria", "review_choice": {"choice": "xhard", "extra_stage": False},
            }],
        },
    )
    engine.register(template)

    result = engine.instantiate(template, {"title": "literal {{title}}"}, project=project, logical_request_key="bundle")
    assert [record.kind for record in result.records] == [WorkKind.TASK, WorkKind.CRITERION]
    task, criterion = result.records
    assert task.title == "literal {{title}}"
    assert task.payload["fields"]["namespace"] == "named.tasks"
    assert criterion.payload["fields"]["namespace"] == "named.criteria"
    assert task.payload["fields"]["review_choice"]["choice"] == "normal"
    assert criterion.payload["fields"]["review_choice"]["choice"] == "xhard"
    assert criterion.parent.id == task.id
    assert task.payload["fields"]["key"] == criterion.payload["fields"]["key"]
    assert task.payload["fields"]["template_origin"] == {
        "authority": "pack", "kind": "work_template", "id": "independent.template",
        "revision": "tree-17", "local_id": "task-local",
    }
    before = len(store.list_events())

    replay = engine.instantiate(template, {"title": "literal {{title}}"}, project=project, logical_request_key="bundle")
    assert [record.ref for record in replay.records] == [task.ref, criterion.ref]
    assert len(store.list_events()) == before
    assert graph.get(task.ref).title == "literal {{title}}"


def test_bundle_rolls_back_later_node_failure_and_replays_once(harness, monkeypatch):
    store, graph, engine, _ = harness
    template = work_template(
        "atomic-bundle",
        revision="atomic-1",
        seed={
            "project": {"title": "Atomic project", "outcome": "Complete atomically"},
            "tasks": [
                {"local_id": "first", "title": "First task"},
                {"local_id": "second", "title": "Second task"},
            ],
        },
    )

    original_create = graph.create
    calls = 0

    def fail_on_second_node(kind, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected later-node failure")
        return original_create(kind, **kwargs)

    monkeypatch.setattr(graph, "create", fail_on_second_node)
    with pytest.raises(RuntimeError, match="injected later-node failure"):
        engine.instantiate(template, logical_request_key="atomic-request")

    assert graph.list() == ()
    assert store.list_events() == ()
    assert store.get_receipt("atomic-request:project") is None
    assert store.get_receipt("atomic-request:first") is None
    assert store.get_receipt("atomic-request:second") is None

    monkeypatch.setattr(graph, "create", original_create)
    result = engine.instantiate(template, logical_request_key="atomic-request")
    assert [record.title for record in result.records] == ["First task", "Second task"]
    assert len(graph.list()) == 3
    assert len(store.list_events()) == 3
    assert all(store.get_receipt(key) is not None for key in (
        "atomic-request:project", "atomic-request:first", "atomic-request:second",
    ))

    replay = engine.instantiate(template, logical_request_key="atomic-request")
    assert [record.ref for record in replay.records] == [record.ref for record in result.records]
    assert replay.project.ref == result.project.ref
    assert len(graph.list()) == 3
    assert len(store.list_events()) == 3


def test_all_invalid_seed_fail_before_any_work_record_is_written(harness):
    store, graph, engine, _ = harness
    project = engine.instantiate("work.blank_project", logical_request_key="owner").project
    before_records = graph.list()
    before_events = store.list_events()

    bad_templates = [
        work_template("missing-param", parameters={"type": "object", "required": ["title"], "properties": {"title": {"type": "string"}}}, seed={"tasks": [{"local_id": "a", "title": {"$param": "title"}}]}),
        work_template("missing-local", seed={"tasks": [{"local_id": "a", "parent": {"$local": "not-there"}}]}),
        work_template("cycle", seed={"tasks": [{"local_id": "a", "parent": {"$local": "b"}}, {"local_id": "b", "parent": {"$local": "a"}}]}),
        work_template("unsafe", seed={"tasks": [{"local_id": "a", "title": {"$param": "missing"}, "fields": {"code": "__import__('os').system('x')"}}]}),
    ]
    for template in bad_templates:
        with pytest.raises((TemplateValidationError, TemplateCycleError, TemplateReferenceError)):
            engine.instantiate(template, project=project, logical_request_key="invalid-" + template.id)
        assert graph.list() == before_records
        assert store.list_events() == before_events


def test_profile_and_allowance_are_resolved_but_not_granted(harness):
    store, graph, engine, actor = harness
    project = engine.instantiate("work.blank_project", logical_request_key="owner").project
    # These are pre-existing typed identities, created through the same FND
    # mutation port solely as an external-resource fixture.  No allowance
    # command or grant operation is supplied to the template layer.
    from herzchen.contracts import CommandEnvelope, ResourceRef, TransactionContext

    refs = []
    for kind, ident in (("profile", "normal-profile"), ("allowance", "existing-pool")):
        ref = ResourceRef(store.authority, kind, ident)
        store.put_identity(ResourceRef(ref.authority, ref.kind, ref.id, "rev-1"), {"kind": kind}, version=1)
        refs.append(ref)
    template = work_template("resolved-refs", seed={"tasks": [{
        "local_id": "task", "profile_ref": refs[0].to_dict(), "allowance_ref": refs[1].to_dict(),
    }]})
    before = len(store.list_events())
    result = engine.instantiate(template, project=project, logical_request_key="resolved")
    assert result.record.payload["fields"]["profile_ref"] == refs[0].to_dict()
    assert result.record.payload["fields"]["allowance_ref"] == refs[1].to_dict()
    assert len(store.list_events()) == before + 1
    assert not any(event.event_type == "allowance.granted" for event in store.list_events())


def test_resume_clone_and_protocol_adoption_are_separate_operations(harness):
    _, graph, engine, _ = harness
    project = engine.instantiate("work.blank_project", logical_request_key="owner").project
    protocol = work_protocol(
        "review.protocol", revision="protocol-4",
        definition={"choices": {"normal": {"model": "gpt-5.6-luna"}, "xhard": {"model": "gpt-5.6-sol"}}},
    )
    engine.register(protocol)
    template = work_template("mentions-protocol", seed={"protocol_ref": {"authority": "pkg03-test", "kind": "work_protocol", "id": "absent", "revision": "4"}, "tasks": [{"local_id": "task", "fields": {"live": {"session": "s"}, "evidence": ["e"], "consumed_state": {"charged": 1}}}]})
    # A protocol mention is metadata only and an absent external ref is
    # rejected before any work is written.  Use a plain protocol declaration
    # in the next template to prove non-adoption without needing a store row.
    with pytest.raises(TemplateReferenceError):
        engine.instantiate(template, project=project, logical_request_key="mention-fails")
    plain = work_template("plain", seed={"protocol_ref": protocol.ref.to_dict(), "protocol": protocol.to_dict(), "tasks": [{"local_id": "task", "fields": {"live": {"session": "s"}, "evidence": ["e"], "consumed_state": {"charged": 1}}}]})
    result = engine.instantiate(plain, project=project, logical_request_key="plain")
    assert graph.get(project.ref).payload["protocol"] is None
    adopted = engine.adopt_protocol(project, protocol, logical_request_key="adopt")
    assert adopted.payload["fields"]["protocol_ref"]["revision"] == "protocol-4"
    assert engine.resume(result.record.ref).ref == result.record.ref
    clone = engine.clone_seed(plain)
    assert clone.seed["tasks"][0]["fields"] == {}
    assert "live" not in clone.seed["tasks"][0]


def test_bounded_effort_uses_the_existing_owner(harness):
    _, graph, engine, _ = harness
    project = engine.instantiate("work.blank_project", logical_request_key="owner").project
    effort = work_template("bounded-effort", seed={"efforts": [{"local_id": "bounded", "title": "Bounded effort"}]})
    result = engine.instantiate_effort(effort, project=project, logical_request_key="effort")
    assert len(result.records) == 1
    assert result.record.kind is WorkKind.EFFORT
    assert result.record.project_ref.id == project.id
    assert graph.get(result.record.ref).id == result.record.id


def test_builtin_names_are_public_and_namespaces_are_stable():
    assert TASK_NAMESPACE == "work.tasks"
    assert CRITERION_NAMESPACE == "work.criteria"
    assert isinstance(work_protocol("p"), WorkProtocol)
