import subprocess
import sys

import pytest

from herzchen.contracts import ContractError, DomainContribution
from herzchen.packs.composition import Composition, CompositionMetadata, TrustedDomain, compose


class Writer:
    def __init__(self):
        self.calls = []

    def register_domain(self, contribution):
        self.calls.append(contribution.domain_id)


def domain(
    name="alpha", *, resource_types=None, document_types=None,
    namespace_types=None, operation_types=None, event_types=None, **kwargs
):
    contribution = DomainContribution(
        name, "1.0", "owner", resource_types or (f"{name}.resource",),
        document_types or (f"{name}.document",), namespace_types or (f"{name}.namespace",),
        operation_types or (f"{name}.command",), event_types or (f"{name}.event",), "v1",
    )
    metadata = CompositionMetadata(edit_scope_resolver=f"{name}.scope", conformance_adapters=(f"{name}.adapter",), **kwargs)
    return TrustedDomain(contribution, metadata)


def test_allowed_composition_delegates_to_one_fnd_writer():
    writer = Writer()
    result = compose(writer, [domain()])
    assert result.ready and writer.calls == ["alpha"]


@pytest.mark.parametrize(
    ("field", "identity"),
    [
        ("domain", "alpha"),
        ("table_types", "shared.table"),
        ("resource_kinds", "alpha.resource"),
        ("document_types", "alpha.document"),
        ("command_types", "alpha.command"),
        ("event_types", "alpha.event"),
        ("namespace_types", "alpha.namespace"),
    ],
)
def test_duplicates_rejected_before_readiness(field, identity):
    writer = Writer()
    first = domain(table_types=(identity,)) if field == "table_types" else domain()
    if field == "domain":
        second = domain()
    else:
        second = domain("beta", **{field: (identity,)})
    composition = Composition(writer)
    composition.register(first)
    with pytest.raises(ContractError, match="duplicate"):
        composition.register(second)
    assert not composition.ready and writer.calls == []


def test_omission_rejected_before_readiness():
    with pytest.raises(ContractError, match="missing"):
        compose(Writer(), [TrustedDomain(domain().contribution, CompositionMetadata())])


def test_unknown_resource_kind_is_opaque_metadata():
    result = compose(Writer(), [domain(resource_kinds=("future.opaque",))])
    assert result.domains[0].metadata.resource_kinds == ("future.opaque",)


def test_neutral_import_without_optional_product_modules():
    code = "import herzchen.packs.composition; import sys; assert not any(x.startswith(('astrid','otto','runtime')) for x in sys.modules)"
    subprocess.run([sys.executable, "-c", code], check=True)
