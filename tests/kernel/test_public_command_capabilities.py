"""GF01 ordinary command objects/modules expose finite ports, never owners."""

import inspect
from types import ModuleType

import pytest

from herzchen.authoring.finish import SemanticFinishAdapter
from herzchen.authoring.idle import IdleCloseService
from herzchen.authoring.sessions import AuthoringSessionService, domain_contribution as edt_contribution
from herzchen.content.authoring import DocumentAuthoringHandler
from herzchen.content.commands import ContentCommandHandler
from herzchen.content.model import domain_contribution as content_contribution
from herzchen.content.packets import ContextPacketService, domain_contribution as packet_contribution
from herzchen.domains.assessment.module import AssessmentModule, contribution as assessment_contribution
from herzchen.domains.work.assignments import ResponsibilityAssignments
from herzchen.domains.work.batches import ProjectBatches
from herzchen.domains.work.decisions import DecisionsModule
from herzchen.domains.work.module import WorkGraph, register_work
from herzchen.domains.work.sheet import ProjectSheet
from herzchen.extensions.commands import ExtensionCommandService
from herzchen.extensions.model import domain_contribution as extension_contribution
from herzchen.kernel.limits import LimitService
from herzchen.kernel.operations import OperationManager
from herzchen.kernel.store import (
    ClosedStoreError,
    ConsumerStore,
    DomainCommandPort,
    DomainHandler,
    Store,
    StoreAdmissionError,
)

import herzchen.authoring.sessions as sessions_module
import herzchen.content.authoring as content_authoring_module
import herzchen.content.commands as content_commands_module
import herzchen.content.packets as packets_module
import herzchen.domains.assessment.module as assessment_module
import herzchen.domains.work.assignments as assignments_module
import herzchen.domains.work.batches as batches_module
import herzchen.domains.work.decisions as decisions_module
import herzchen.domains.work.module as work_module
import herzchen.domains.work.sheet as sheet_module
import herzchen.extensions.commands as extensions_module
import herzchen.kernel.limits as limits_module
import herzchen.kernel.operations as operations_module
import herzchen.packs.authoring as pack_authoring_module
import herzchen.packs.templates as templates_module
from herzchen.packs.authoring import ManagedPackAuthoringHandler, domain_contribution as pack_contribution
from herzchen.packs.templates import TemplateEngine


FORBIDDEN = (
    "connection", "transaction", "mutate", "put_identity", "revise_identity",
    "put_reference", "append_event", "register_domain", "domain_handler",
    "register_domain_handler",
)

PRIVATE_HELPERS = (
    "_session_transaction", "_records", "_validate_record", "_request_digest",
    "_transition_recovery", "_resolve", "_envelope", "_write_child_rows",
    "_require_writer",
)


def _assert_ordinary(value):
    # The historical escape was conventionally reachable as ``command.store``
    # or ``command.writer``.  Ordinary inspection now reaches only explicitly
    # named domain collaborators and the concrete read-only ConsumerStore.
    for name in ("store", "writer", "_writer"):
        assert not hasattr(value, name), (type(value).__name__, name)
    reader = getattr(value, "reader", None)
    if reader is not None:
        assert isinstance(reader, ConsumerStore)
        for name in FORBIDDEN:
            assert not hasattr(reader, name), (type(value).__name__, name)
    for name in FORBIDDEN:
        assert not hasattr(value, name), (type(value).__name__, name)
    # Name-mangling or renaming a broad writer is not a capability boundary.
    # No object retained directly by the command may be the Store/handler or
    # expose a generic SQL/mutation surface.
    for name, retained in vars(value).items():
        assert not isinstance(retained, (Store, DomainHandler)), (type(value).__name__, name)
        if isinstance(retained, ConsumerStore):
            continue
        assert not (hasattr(retained, "transaction") and hasattr(retained, "mutate")), (
            type(value).__name__, name
        )
    port = getattr(value, "command_port", None)
    if port is None:
        assert any(isinstance(retained, ConsumerStore) or hasattr(retained, "command_port") for retained in vars(value).values())
        return
    assert isinstance(port, DomainCommandPort)
    assert port.reader is reader
    assert port.endpoints
    for name in FORBIDDEN:
        assert not hasattr(port, name), (type(value).__name__, name)
    with pytest.raises(TypeError):
        vars(port)
    assert not any(name in FORBIDDEN for name in dir(port))


MODULES = (
    sessions_module, content_authoring_module, content_commands_module,
    packets_module, assessment_module, assignments_module, batches_module,
    decisions_module, work_module, sheet_module, extensions_module,
    limits_module, operations_module, pack_authoring_module, templates_module,
)


def _assert_module_has_no_owner_registry(module: ModuleType) -> None:
    assert "_COMMAND_PORTS" not in vars(module)
    assert "_KERNEL_PORTS" not in vars(module)
    for name, value in vars(module).items():
        if inspect.isclass(value) or inspect.ismodule(value) or inspect.isfunction(value):
            continue
        if isinstance(value, (dict, list, tuple, set, frozenset)):
            members = value.values() if isinstance(value, dict) else value
            assert not any(isinstance(member, (Store, DomainHandler)) for member in members), (
                module.__name__, name
            )


def test_every_ordinary_command_construction_has_no_public_store_writer_escape(tmp_path):
    owner = Store.create(tmp_path / "ordinary.sqlite", authority="ordinary")
    try:
        register_work(owner)
        owner.register_domain_handler((
            assessment_contribution(), content_contribution(), packet_contribution(),
            extension_contribution(), pack_contribution(), edt_contribution(),
        ))
        sessions = AuthoringSessionService(owner)
        finish = SemanticFinishAdapter(sessions)
        values = (
            WorkGraph(owner), ResponsibilityAssignments(owner), ProjectBatches(owner),
            ProjectSheet(owner), DecisionsModule(owner), AssessmentModule(owner),
            LimitService(owner), OperationManager(owner), ExtensionCommandService(owner, register=False),
            ContentCommandHandler(owner), ContextPacketService(owner),
            DocumentAuthoringHandler(owner, authoring=sessions),
            ManagedPackAuthoringHandler(owner), TemplateEngine(owner), sessions,
            finish, IdleCloseService(finish),
        )
        for value in values:
            _assert_ordinary(value)

        for module in MODULES:
            _assert_module_has_no_owner_registry(module)

        before = dict(owner.consumer().snapshot_counts())
        for value in values:
            for name in FORBIDDEN:
                try:
                    candidate = getattr(value, "store")
                    getattr(candidate, name)
                except AttributeError:
                    pass
                else:  # pragma: no cover - assertion branch
                    raise AssertionError((type(value).__name__, name))
        assert owner.consumer().snapshot_counts() == before
    finally:
        owner.close()


def test_private_engine_helpers_are_not_forwarded_or_assignable_and_make_no_delta(tmp_path):
    owner = Store.create(tmp_path / "private-helper.sqlite", authority="private-helper")
    try:
        register_work(owner)
        owner.register_domain_handler((
            assessment_contribution(), content_contribution(), packet_contribution(),
            extension_contribution(), pack_contribution(), edt_contribution(),
        ))
        sessions = AuthoringSessionService(owner)
        commands = (
            WorkGraph(owner), ResponsibilityAssignments(owner), ProjectBatches(owner),
            ProjectSheet(owner), DecisionsModule(owner), AssessmentModule(owner),
            LimitService(owner), OperationManager(owner), ExtensionCommandService(owner, register=False),
            ContentCommandHandler(owner), ContextPacketService(owner),
            DocumentAuthoringHandler(owner, authoring=sessions),
            ManagedPackAuthoringHandler(owner), TemplateEngine(owner), sessions,
        )
        before = dict(owner.consumer().snapshot_counts())
        for command in commands:
            port = command.command_port
            assert not any(name.startswith("_") for name in port.endpoints)
            for name in PRIVATE_HELPERS + FORBIDDEN:
                with pytest.raises(AttributeError):
                    getattr(command, name)
                with pytest.raises(AttributeError):
                    setattr(command, name, object())
                assert not hasattr(type(command), name)
                assert name not in port.endpoints
                assert name not in dir(port)
        assert owner.consumer().snapshot_counts() == before
    finally:
        owner.close()


def test_ports_are_store_issued_finite_and_fail_closed_for_counterfeit_foreign_and_stale(tmp_path):
    owner = Store.create(tmp_path / "owner.sqlite", authority="owner")
    foreign = Store.create(tmp_path / "foreign.sqlite", authority="foreign")
    try:
        register_work(owner)
        graph = WorkGraph(owner)
        before = dict(owner.consumer().snapshot_counts())

        with pytest.raises(StoreAdmissionError, match="trusted Store composition"):
            DomainCommandPort(object(), "counterfeit", ("create",), None)
        with pytest.raises(StoreAdmissionError, match="broad writer endpoint"):
            owner.issue_command_port(object(), "counterfeit", ("_private_helper",))
        with pytest.raises((StoreAdmissionError, TypeError, AttributeError)):
            WorkGraph(graph.command_port)
        assessment_only = foreign.register_domain_handler((assessment_contribution(),))
        foreign_before = dict(foreign.consumer().snapshot_counts())
        with pytest.raises((StoreAdmissionError, TypeError, AttributeError)):
            WorkGraph(assessment_only)
        assert owner.consumer().snapshot_counts() == before
        assert foreign.consumer().snapshot_counts() == foreign_before

        owner.close()
        with pytest.raises(ClosedStoreError):
            graph.get("missing")
    finally:
        if getattr(owner, "_closed", True) is False:
            owner.close()
        foreign.close()
