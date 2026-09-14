"""Bijective GF01 evidence inventory for all persisted mutation ports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Tuple

from herzchen.authoring.sessions import domain_contribution as edt_contribution
from herzchen.content.model import domain_contribution as content_contribution
from herzchen.content.packets import domain_contribution as packet_contribution
from herzchen.domains.assessment.module import contribution as assessment_contribution
from herzchen.domains.work import contributions as work_contributions
from herzchen.extensions.model import domain_contribution as extension_contribution
from herzchen.packs.authoring import domain_contribution as pack_contribution


@dataclass(frozen=True)
class MutatorEvidence:
    mutation_port: str
    domain_id: str
    supported_entry_point: str
    persisted_delta: Mapping[str, int]
    receipt_event_linkage: str
    replay: str
    rejection_rollback: str
    fresh_after_restart: str
    aggregate_child_effects: Tuple[str, ...] = ()


PERSISTED_DELTA = {
    "identities": 1,
    "record_references": 2,
    "events": 1,
    "command_receipts": 1,
    "event_sequences": 1,
}


ENTRY_POINTS = {
    "actor.open": "herzchen.authoring.sessions.AuthoringSessionService.open",
    "actor.release": "herzchen.authoring.sessions.AuthoringSessionService.release",
    "open": "herzchen.authoring.sessions.AuthoringSessionService.open",
    "metadata": "herzchen.authoring.sessions.AuthoringSessionService.open",
    "autosave": "herzchen.authoring.sessions.AuthoringSessionService.autosave",
    "finish.claim": "herzchen.authoring.sessions.AuthoringSessionService.finish",
    "finish": "herzchen.authoring.sessions.AuthoringSessionService.finish",
    "finish.recovery": "herzchen.authoring.sessions.AuthoringSessionService.finish",
    "release": "herzchen.authoring.sessions.AuthoringSessionService.release",
    "cleanup": "herzchen.authoring.sessions.AuthoringSessionService.cleanup",
    "cleanup.refresh": "herzchen.authoring.sessions.AuthoringSessionService.refresh_final_snapshot",
    "dat.content.document.create": "herzchen.content.commands.ContentCommandHandler.execute",
    "dat.content.revision.append": "herzchen.content.commands.ContentCommandHandler.execute",
    "dat.content.link": "herzchen.content.commands.ContentCommandHandler.execute",
    "dat.content.unlink": "herzchen.content.commands.ContentCommandHandler.execute",
    "dat.extensions.metadata.set": "herzchen.extensions.commands.ExtensionCommandService.set",
    "dat.extensions.metadata.remove": "herzchen.extensions.commands.ExtensionCommandService.remove",
    "dat.context.attention.create": "herzchen.content.packets.ContextPacketService.notify_amendment",
    "pack.content.author": "herzchen.packs.authoring.ManagedPackAuthoringHandler.author",
    "work.assignment.create": "herzchen.domains.work.assignments.ResponsibilityAssignments.assign",
    "work.assignment.reassign": "herzchen.domains.work.assignments.ResponsibilityAssignments.reassign",
    "work.assignment.dispatch": "herzchen.domains.work.assignments.ResponsibilityAssignments.dispatch",
    "work.result.append": "herzchen.domains.work.assignments.ResponsibilityAssignments.append_result",
    "work.report.append": "herzchen.domains.work.assignments.ResponsibilityAssignments.append_report",
    "work.project-sheet.apply": "herzchen.domains.work.batches.ProjectBatches.apply_project_sheet",
    "work.project.create": "herzchen.domains.work.batches.ProjectBatches.create_pending_project",
    "work.project.activate": "herzchen.domains.work.batches.ProjectBatches.activate_project",
    "work.readiness.observe": "herzchen.domains.work.batches.ProjectBatches.observe_readiness",
    "work.project-report.append": "herzchen.domains.work.batches.ProjectBatches.append_report",
    "work.amendment.link": "herzchen.domains.work.batches.ProjectBatches.cross_scope_amendment",
    "work.authoring.reconcile": "herzchen.domains.work.batches.ProjectBatches.retry_materialisation",
    "work.candidate.create": "herzchen.domains.work.decisions.DecisionsModule.create_candidate",
    "work.candidate.annotate": "herzchen.domains.work.decisions.DecisionsModule.annotate_candidate",
    "work.decision.record": "herzchen.domains.work.decisions.DecisionsModule.record_decision",
    "work.wait.record": "herzchen.domains.work.decisions.DecisionsModule.record_wait",
    "work.manager-choice.record": "herzchen.domains.work.decisions.DecisionsModule.choose_next_action",
    "work.assignment.route-pin": "herzchen.domains.work.sheet.ProjectSheet.pin_assignment_route",
    "assessment.scope.declare": "herzchen.domains.assessment.module.AssessmentModule.declare_scope",
    "assessment.input.freeze": "herzchen.domains.assessment.module.AssessmentModule.freeze_input",
    "assessment.candidate.select": "herzchen.domains.assessment.module.AssessmentModule.select_candidate",
    "assessment.run": "herzchen.domains.assessment.module.AssessmentModule.assess",
    "assessment.correction.create": "herzchen.domains.assessment.module.AssessmentModule.create_correction",
    "assessment.finding.close": "herzchen.domains.assessment.module.AssessmentModule.close_finding",
    "assessment.accept": "herzchen.domains.assessment.module.AssessmentModule.accept",
    "assessment.unknown.disposition": "herzchen.domains.assessment.module.AssessmentModule.dispose_unknown",
    "assessment.loop-facts.record": "herzchen.domains.assessment.module.AssessmentModule.record_loop_facts",
    "assessment.result.link-correction": "herzchen.domains.assessment.module.AssessmentModule.create_correction",
}


AGGREGATE_CHILD_EFFECTS = {
    "actor.open": ("authoring actor identity/reference",),
    "open": ("draft snapshot identity/reference", "authoring actor identity/reference"),
    "finish": ("final snapshot identity/reference", "authoring actor release revision"),
    "work.project-sheet.apply": (
        "task identity create/revise and dependency references",
        "document head/revision identities and revision references",
        "document-association identity/revision references",
    ),
    "work.project.create": ("optional authoring-reservation identity/reference",),
    "assessment.run": (
        "operation identity/receipt/event",
        "limit reservation identity/receipt/event",
        "assessment invocation and finding identities/references",
    ),
    "assessment.correction.create": ("assessment result correction-link revision",),
    "dat.content.document.create": ("initial content revision identity/reference",),
    "dat.content.revision.append": ("content revision identity/reference",),
}


def descriptors():
    values = work_contributions() + (
        assessment_contribution(), edt_contribution(), content_contribution(),
        extension_contribution(), packet_contribution(), pack_contribution(),
    )
    return tuple(sorted(values, key=lambda item: item.domain_id))


def mutation_ports(descriptor):
    return tuple(
        binding.split(":", 1)[1]
        for binding in descriptor.composition_bindings
        if binding.startswith("mutation-port:")
    )


def _work_entry(operation: str, resource: str, event: str) -> str:
    if operation == "work.create":
        suffix = resource.split(".", 1)[1]
        return "herzchen.domains.work.module.WorkGraph.create_{}".format(suffix)
    method = {
        "work.revised": "revise",
        "work.parent-linked": "link_parent",
        "work.dependency-linked": "link_dependency",
        "work.state-changed": "set_lifecycle",
    }[event]
    return "herzchen.domains.work.module.WorkGraph." + method


def build_inventory() -> Tuple[MutatorEvidence, ...]:
    rows = []
    for descriptor in descriptors():
        for mutation_port in mutation_ports(descriptor):
            schema, operation, resource, event = mutation_port.split("|")
            assert schema == descriptor.schema_revision
            entry = _work_entry(operation, resource, event) if descriptor.domain_id == "herzchen.work" else ENTRY_POINTS[operation]
            rows.append(MutatorEvidence(
                mutation_port=mutation_port,
                domain_id=descriptor.domain_id,
                supported_entry_point=entry,
                persisted_delta=dict(PERSISTED_DELTA),
                receipt_event_linkage="receipt.event_ids == persisted event ids; one transaction_id",
                replay="exact request returns original receipt after identity advances",
                rejection_rollback="changed semantic fields and forced transaction abort leave zero delta",
                fresh_after_restart="identity, receipt, event, and references re-read from reopened Store",
                aggregate_child_effects=AGGREGATE_CHILD_EFFECTS.get(operation, ()),
            ))
    return tuple(rows)


MUTATOR_INVENTORY = build_inventory()

