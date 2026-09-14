"""GF01 ordinary command objects expose reads, never the Store owner."""

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
from herzchen.kernel.store import ConsumerStore, DomainHandler, Store
from herzchen.packs.authoring import ManagedPackAuthoringHandler, domain_contribution as pack_contribution
from herzchen.packs.templates import TemplateEngine


FORBIDDEN = (
    "connection", "transaction", "mutate", "put_identity", "revise_identity",
    "put_reference", "append_event", "register_domain", "domain_handler",
    "register_domain_handler",
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
