"""PKG-03 template resources exercised through FND and WRK public APIs."""

from __future__ import annotations

import pytest

from herzchen.contracts import AuthenticatedActor
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
    engine = TemplateEngine(store, graph=graph, actor=actor)
    try:
        yield store, graph, engine, actor
    finally:
        store.close()


def test_blank_resource_uses_common_fields_and_has_no_side_effects(harness):
    store, graph, engine, _ = harness

    rendered = render_blank_project()
    assert rendered["project"]["title"] == "Untitled project"
    assert rendered["project"]["outcome"] == ""
    assert rendered["tasks"] == []
    assert render_template(blank_project_template()).seed["tasks"] == []

    result = engine.instantiate("work.blank_project", logical_request_key="blank")
    project = graph.get(result.project.ref)
    assert project.kind is WorkKind.PROJECT
    assert project.payload["tasks"] == []
    assert project.payload["protocol"] is None
    assert project.payload["manager"] is None
    assert project.payload["budget"] is None
    assert project.payload["readiness"]["dispatch"] is False
    assert len(graph.list()) == 1
    assert len(store.list_events()) == 1
    assert result.receipts[0].event_ids


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
        context = TransactionContext(actor, "fixture-" + ident, "0" * 64, expected_version=0)
        store.mutate(CommandEnvelope("fixture.create", "fixture.v1", ref, context, {"kind": kind}), event_type="fixture.created")
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
