"""Explicit, product-neutral composition of trusted domain contributions.

This module is deliberately a registration seam: persistence, transactions,
DDL and lifecycle remain owned by the FND writer supplied by the application.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Protocol, Sequence, Tuple

from herzchen.contracts import ContractError, DomainContribution, DomainRegistry


class DomainWriter(Protocol):
    """FND-owned persistence boundary; PKG never implements this interface."""

    def register_domain(self, contribution: DomainContribution) -> Any: ...


@dataclass(frozen=True)
class CompositionMetadata:
    resource_types: Tuple[str, ...] = ()
    command_types: Tuple[str, ...] = ()
    event_types: Tuple[str, ...] = ()
    edit_scope_resolver: Optional[str] = None
    conformance_adapters: Tuple[str, ...] = ()
    table_types: Tuple[str, ...] = ()
    resource_kinds: Tuple[str, ...] = ()


@dataclass(frozen=True)
class TrustedDomain:
    contribution: DomainContribution
    metadata: CompositionMetadata


_FIELDS = ("domain", "table", "resource", "document", "command", "event", "namespace")


class Composition:
    """One explicit trusted composition, ready only after all checks pass."""

    def __init__(self, writer: DomainWriter) -> None:
        self._writer = writer
        self._domains = DomainRegistry()
        self._seen: dict[str, dict[str, str]] = {field: {} for field in _FIELDS}
        self._entries: list[TrustedDomain] = []
        self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def domains(self) -> Tuple[TrustedDomain, ...]:
        return tuple(self._entries)

    def register(self, domain: TrustedDomain) -> None:
        if not isinstance(domain, TrustedDomain):
            raise ContractError("composition requires a TrustedDomain")
        contribution, metadata = domain.contribution, domain.metadata
        if not metadata.edit_scope_resolver:
            raise ContractError("missing edit-scope resolver")
        if not metadata.conformance_adapters:
            raise ContractError("missing conformance adapter")
        groups = {
            "domain": (contribution.domain_id,),
            "table": metadata.table_types,
            "resource": contribution.resource_types + metadata.resource_types + metadata.resource_kinds,
            "document": contribution.document_types,
            "command": contribution.operation_types + metadata.command_types,
            "event": contribution.event_types + metadata.event_types,
            "namespace": contribution.namespace_types,
        }
        local: set[tuple[str, str]] = set()
        for category, identities in groups.items():
            for identity in identities:
                key = (category, identity)
                if key in local or identity in self._seen[category]:
                    raise ContractError(f"duplicate {category} identity: {identity}")
                local.add(key)
        # DomainRegistry applies the FND-owned contribution validation too.
        self._domains.register(contribution)
        for category, identities in groups.items():
            for identity in identities:
                self._seen[category][identity] = contribution.domain_id
        self._entries.append(domain)

    def finalize(self) -> None:
        """Atomically mark the declaration ready, then delegate registration."""
        if not self._entries:
            raise ContractError("composition has no trusted domains")
        if self._ready:
            raise ContractError("composition is already ready")
        for entry in self._entries:
            self._writer.register_domain(entry.contribution)
        self._ready = True


def compose(writer: DomainWriter, domains: Sequence[TrustedDomain]) -> Composition:
    composition = Composition(writer)
    for domain in domains:
        composition.register(domain)
    composition.finalize()
    return composition


__all__ = ["Composition", "CompositionMetadata", "DomainWriter", "TrustedDomain", "compose"]
