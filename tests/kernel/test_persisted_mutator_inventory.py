"""The versioned GF01 inventory is derived from the persisted descriptors."""

from herzchen.authoring.sessions import domain_contribution as edt_contribution
from herzchen.content.model import domain_contribution as content_contribution
from herzchen.content.packets import domain_contribution as packet_contribution
from herzchen.domains.assessment.module import contribution as assessment_contribution
from herzchen.domains.work import contributions as work_contributions
from herzchen.extensions.model import domain_contribution as extension_contribution
from herzchen.kernel.store import Store
from herzchen.packs.authoring import domain_contribution as pack_contribution


EXPECTED_PORT_COUNTS = {
    "herzchen.work": 29,
    "herzchen.work.assignments": 5,
    "herzchen.work.batches": 7,
    "herzchen.work.decisions": 5,
    "herzchen.work.sheet": 1,
    "herzchen.assessment": 10,
    "herzchen.authoring.sessions": 11,
    "dat.content": 4,
    "dat.extensions": 2,
    "herzchen.content.packets": 1,
    "herzchen.packs.authoring": 1,
}


def _descriptors():
    values = work_contributions() + (
        assessment_contribution(), edt_contribution(), content_contribution(),
        extension_contribution(), packet_contribution(), pack_contribution(),
    )
    return tuple(sorted(values, key=lambda item: item.domain_id))


def _ports(descriptor):
    return tuple(
        binding.split(":", 1)[1]
        for binding in descriptor.composition_bindings
        if binding.startswith("mutation-port:")
    )


def test_persisted_descriptor_set_has_the_complete_exact_mutator_inventory(tmp_path):
    path = tmp_path / "inventory.sqlite"
    descriptors = _descriptors()
    owner = Store.create(path, authority="inventory")
    try:
        owner.register_domain_handler(descriptors)
        persisted = {item.domain_id: item for item in owner.registered_domains()}
        assert set(persisted) == set(EXPECTED_PORT_COUNTS)
        assert sum(EXPECTED_PORT_COUNTS.values()) == 76
        assert "work.v1|work.revise|work.project|work.parent-linked" not in _ports(
            persisted["herzchen.work"]
        )
        for domain_id, expected_count in EXPECTED_PORT_COUNTS.items():
            descriptor = persisted[domain_id]
            ports = _ports(descriptor)
            assert len(ports) == expected_count, domain_id
            assert len(set(ports)) == len(ports), domain_id
            for port in ports:
                schema, operation, resource, event = port.split("|")
                assert schema == descriptor.schema_revision
                assert operation in descriptor.operation_types
                assert event in descriptor.event_types
                assert resource == "*" or resource in descriptor.resource_types or (
                    "mutation-resource:" + resource in descriptor.composition_bindings
                )
    finally:
        expected_digest = owner.domain_descriptor_digest
        owner.close()

    reopened = Store.open(path, authority="inventory", expected_domains=descriptors)
    try:
        assert reopened.domain_descriptor_digest == expected_digest
        assert {item.domain_id: _ports(item) for item in reopened.registered_domains()} == {
            item.domain_id: _ports(item) for item in descriptors
        }
    finally:
        reopened.close()
