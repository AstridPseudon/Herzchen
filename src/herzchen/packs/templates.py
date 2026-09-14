"""Resource-only work templates and protocols.

The pack layer owns the shape and expansion of reusable resources.  It does
not own persistence: instantiated work is written by :class:`WorkGraph` to a
caller-supplied FND store, and all writes retain the pack resource identity in
ordinary work payload metadata.

Only two deliberately small substitutions are supported in a seed::

    {"$param": "title"}       # one scalar parameter
    {"$local": "build-task"}  # one seed-local typed reference

Strings are always literal.  In particular, no expression, format string,
shell fragment, import, or network lookup is evaluated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from copy import deepcopy
import hashlib
import uuid
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from herzchen.content import ContentCommandHandler, ContentDocument, ContentRevision, DocumentAssociation
from herzchen.contracts import AuthenticatedActor, ReferenceBinding, ResourceRef, TransactionContext, canonical_json
from herzchen.domains.work import Lifecycle, WorkKind, WorkRecord, WorkValidationError


TEMPLATE_KIND = "work_template"
PROTOCOL_KIND = "work_protocol"
RESOURCE_AUTHORITY = "pack"
RESOURCE_REVISION = "pkg-03.v1"
BLANK_TEMPLATE_ID = "work.blank_project"
TASK_NAMESPACE = "work.tasks"
CRITERION_NAMESPACE = "work.criteria"
_WORK_LINKS_KEY = "__template_links__"


class TemplateError(ValueError):
    """Base error for resource validation and instantiation."""


class TemplateValidationError(TemplateError):
    """The resource, parameters, or expanded seed is invalid."""


class TemplateReferenceError(TemplateValidationError):
    """A typed or local reference cannot be resolved."""


class TemplateCycleError(TemplateValidationError):
    """The expanded parent/dependency graph is cyclic."""


class UnknownTemplateError(TemplateError):
    """A catalog lookup did not find the requested template."""


def _json(value: Any) -> str:
    try:
        return canonical_json(value)
    except (TypeError, ValueError) as exc:
        raise TemplateValidationError("resource values must be JSON-safe") from exc


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise TemplateValidationError(f"{field} must be non-blank text")
    if "/" in value or "\\" in value:
        raise TemplateValidationError(f"{field} must be an opaque identifier")
    return value


def _ref(value: Any, field: str = "reference") -> ResourceRef:
    if isinstance(value, ResourceRef):
        return value
    if isinstance(value, Mapping):
        try:
            return ResourceRef.from_dict(value)
        except (KeyError, TypeError, ValueError) as exc:
            raise TemplateReferenceError(f"{field} is not a typed ResourceRef") from exc
    raise TemplateReferenceError(f"{field} must be a typed ResourceRef")


def _ref_dict(value: ResourceRef) -> dict[str, Any]:
    return value.to_dict()


def _origin(resource: Union["WorkTemplate", "WorkProtocol"]) -> dict[str, Any]:
    return {
        "authority": RESOURCE_AUTHORITY,
        "kind": resource.kind,
        "id": resource.id,
        "revision": resource.revision,
    }


def _request_key(value: Optional[str], resource: WorkTemplate, rendered: RenderedTemplate) -> str:
    """Use caller idempotency when supplied; otherwise issue a fresh request."""
    if value is None:
        return "template-request-" + uuid.uuid4().hex
    return _text(value, "logical_request_key")


@dataclass(frozen=True)
class WorkTemplate:
    """An immutable ``work_template`` resource declaration."""

    id: str
    revision: str
    parameters: Mapping[str, Any]
    seed: Mapping[str, Any]
    source_ref: Optional[ResourceRef] = None

    kind: str = TEMPLATE_KIND

    def __post_init__(self) -> None:
        _text(self.id, "template id")
        _text(self.revision, "template revision")
        if not isinstance(self.parameters, Mapping):
            raise TemplateValidationError("template parameters must be a JSON Schema object")
        if not isinstance(self.seed, Mapping):
            raise TemplateValidationError("template seed must be an object")
        if self.source_ref is not None and not isinstance(self.source_ref, ResourceRef):
            raise TemplateReferenceError("source_ref must be a ResourceRef")
        _json(self.parameters)
        _json(self.seed)
        _validate_parameter_schema(self.parameters)

    @property
    def ref(self) -> ResourceRef:
        return ResourceRef(RESOURCE_AUTHORITY, self.kind, self.id, self.revision)

    @property
    def parameter_schema(self) -> Mapping[str, Any]:
        return self.parameters

    def to_dict(self) -> dict[str, Any]:
        value = {"kind": self.kind, "id": self.id, "revision": self.revision,
                 "parameters": deepcopy(dict(self.parameters)), "seed": deepcopy(dict(self.seed))}
        if self.source_ref is not None:
            value["source_ref"] = self.source_ref.to_dict()
        return value


@dataclass(frozen=True)
class WorkProtocol:
    """An immutable ``work_protocol`` resource declaration.

    Protocols are data and choice metadata.  They never launch a worker or
    charge an allowance merely because a template mentions one.
    """

    id: str
    revision: str
    definition: Mapping[str, Any]
    source_ref: Optional[ResourceRef] = None

    kind: str = PROTOCOL_KIND

    def __post_init__(self) -> None:
        _text(self.id, "protocol id")
        _text(self.revision, "protocol revision")
        if not isinstance(self.definition, Mapping):
            raise TemplateValidationError("protocol definition must be an object")
        if self.source_ref is not None and not isinstance(self.source_ref, ResourceRef):
            raise TemplateReferenceError("source_ref must be a ResourceRef")
        _json(self.definition)
        _validate_protocol(self.definition)

    @property
    def ref(self) -> ResourceRef:
        return ResourceRef(RESOURCE_AUTHORITY, self.kind, self.id, self.revision)

    @property
    def choices(self) -> Mapping[str, Any]:
        return self.definition.get("choices", {})

    def to_dict(self) -> dict[str, Any]:
        value = {"kind": self.kind, "id": self.id, "revision": self.revision,
                 "definition": deepcopy(dict(self.definition))}
        if self.source_ref is not None:
            value["source_ref"] = self.source_ref.to_dict()
        return value


def work_template(
    id: str,
    revision: str = RESOURCE_REVISION,
    *,
    parameters: Optional[Mapping[str, Any]] = None,
    seed: Optional[Mapping[str, Any]] = None,
    source_ref: Optional[ResourceRef] = None,
) -> WorkTemplate:
    """Construct a typed work-template resource."""
    return WorkTemplate(id, revision, parameters or {"type": "object", "properties": {}, "additionalProperties": False}, seed or {}, source_ref)


def work_protocol(
    id: str,
    revision: str = RESOURCE_REVISION,
    *,
    definition: Optional[Mapping[str, Any]] = None,
    choices: Optional[Mapping[str, Any]] = None,
    source_ref: Optional[ResourceRef] = None,
) -> WorkProtocol:
    """Construct a typed work-protocol resource."""
    value = dict(definition or {})
    if choices is not None:
        if "choices" in value:
            raise TemplateValidationError("protocol choices were supplied twice")
        value["choices"] = dict(choices)
    return WorkProtocol(id, revision, value, source_ref)


def _validate_parameter_schema(schema: Mapping[str, Any]) -> None:
    if schema.get("type", "object") != "object":
        raise TemplateValidationError("template parameter schema must have object type")
    properties = schema.get("properties", {})
    if not isinstance(properties, Mapping):
        raise TemplateValidationError("parameter properties must be an object")
    required = schema.get("required", ())
    if not isinstance(required, (list, tuple)) or any(not isinstance(item, str) for item in required):
        raise TemplateValidationError("parameter required must be a list of names")
    if len(set(required)) != len(required) or any(name not in properties for name in required):
        raise TemplateValidationError("required parameters must be declared properties")
    for name, definition in properties.items():
        _text(name, "parameter name")
        if not isinstance(definition, Mapping):
            raise TemplateValidationError(f"parameter {name!r} definition must be an object")
        if "default" in definition:
            _json(definition["default"])
        if definition.get("type") not in (None, "string", "integer", "number", "boolean", "null", "array", "object"):
            raise TemplateValidationError(f"unsupported parameter type for {name!r}")


def _validate_protocol(definition: Mapping[str, Any]) -> None:
    _json(definition)
    choices = definition.get("choices", {})
    if choices and not isinstance(choices, Mapping):
        raise TemplateValidationError("protocol choices must be an object")
    for name, choice in choices.items():
        if name not in {"normal", "xhard"}:
            continue
        if not isinstance(choice, Mapping):
            raise TemplateValidationError(f"protocol choice {name!r} must be an object")
        if choice.get("review_sequence") and len(choice["review_sequence"]) > 1:
            raise TemplateValidationError("a review choice cannot force two reviews")
        if choice.get("extra_stage"):
            raise TemplateValidationError("a review choice cannot add an automatic stage")


def _type_matches(value: Any, expected: Optional[str]) -> bool:
    if expected is None:
        return True
    return {
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
        "array": isinstance(value, list),
        "object": isinstance(value, Mapping),
    }.get(expected, False)


def validate_parameters(template: WorkTemplate, parameters: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """Apply only literal schema defaults and validate supplied parameters."""
    if not isinstance(template, WorkTemplate):
        raise TemplateValidationError("template must be a WorkTemplate")
    supplied = {} if parameters is None else dict(parameters)
    if not isinstance(parameters, (type(None), Mapping)):
        raise TemplateValidationError("parameters must be an object")
    schema = template.parameters
    properties = schema.get("properties", {})
    if schema.get("additionalProperties", True) is False:
        unknown = set(supplied).difference(properties)
        if unknown:
            raise TemplateValidationError("unknown parameters: " + ", ".join(sorted(unknown)))
    result = dict(supplied)
    for name, definition in properties.items():
        if name not in result and "default" in definition:
            result[name] = deepcopy(definition["default"])
    missing = [name for name in schema.get("required", ()) if name not in result]
    if missing:
        raise TemplateValidationError("missing parameters: " + ", ".join(missing))
    for name, value in result.items():
        definition = properties.get(name, {})
        if not _type_matches(value, definition.get("type")):
            raise TemplateValidationError(f"parameter {name!r} has the wrong type")
        if isinstance(value, str) and "minLength" in definition and len(value) < definition["minLength"]:
            raise TemplateValidationError(f"parameter {name!r} is too short")
        if "enum" in definition and value not in definition["enum"]:
            raise TemplateValidationError(f"parameter {name!r} is not an allowed value")
    _json(result)
    return result


def expand_seed(value: Any, parameters: Mapping[str, Any]) -> Any:
    """Expand safe markers while leaving all ordinary strings untouched."""
    active: set[int] = set()

    def visit(item: Any) -> Any:
        if isinstance(item, Mapping):
            marker_keys = [key for key in item if isinstance(key, str) and key.startswith("$")]
            if marker_keys:
                if set(item) == {"$param"}:
                    name = item["$param"]
                    if not isinstance(name, str) or name not in parameters:
                        raise TemplateValidationError(f"undefined scalar parameter: {name!r}")
                    result = parameters[name]
                    if isinstance(result, (Mapping, list, tuple)):
                        raise TemplateValidationError("$param can substitute scalar values only")
                    return deepcopy(result)
                if set(item) == {"$local"}:
                    name = item["$local"]
                    if not isinstance(name, str) or not name.strip():
                        raise TemplateReferenceError("$local must name a seed-local identity")
                    return {"$local": name}
                raise TemplateValidationError("unknown or mixed resource marker")
            ident = id(item)
            if ident in active:
                raise TemplateValidationError("cyclic seed value")
            active.add(ident)
            try:
                return {key: visit(child) for key, child in item.items()}
            finally:
                active.remove(ident)
        if isinstance(item, (list, tuple)):
            ident = id(item)
            if ident in active:
                raise TemplateValidationError("cyclic seed value")
            active.add(ident)
            try:
                return [visit(child) for child in item]
            finally:
                active.remove(ident)
        return item

    result = visit(value)
    _json(result)
    return result


@dataclass(frozen=True)
class RenderedTemplate:
    template: WorkTemplate
    parameters: Mapping[str, Any]
    seed: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"template": self.template.ref.to_dict(), "parameters": deepcopy(dict(self.parameters)), "seed": deepcopy(dict(self.seed))}


def render_template(template: WorkTemplate, parameters: Optional[Mapping[str, Any]] = None) -> RenderedTemplate:
    checked = validate_parameters(template, parameters)
    seed = expand_seed(template.seed, checked)
    return RenderedTemplate(template, checked, seed)


def clone_seed(template: WorkTemplate) -> WorkTemplate:
    """Clone planning data while omitting live, evidence, and usage facts."""
    if not isinstance(template, WorkTemplate):
        raise TemplateValidationError("template must be a WorkTemplate")
    excluded = {"live", "live_state", "evidence", "evidence_refs", "consumed", "consumed_state", "charged_usage", "active_session", "execution"}

    def scrub(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {key: scrub(child) for key, child in value.items() if key not in excluded}
        if isinstance(value, list):
            return [scrub(child) for child in value]
        return deepcopy(value)

    return WorkTemplate(template.id + ".clone", template.revision, deepcopy(dict(template.parameters)), scrub(template.seed), template.source_ref)


def validate_template(template: WorkTemplate) -> WorkTemplate:
    """Validate and return a typed resource without resolving or writing it."""
    if not isinstance(template, WorkTemplate):
        raise TemplateValidationError("template must be a WorkTemplate")
    # Construction validates the resource envelope; this also validates the
    # seed's JSON shape before a caller puts it in a catalog.
    _json(template.to_dict())
    _node_list(template.seed)
    return template


def _blank_seed() -> dict[str, Any]:
    return {
        "project": {"local_id": "project", "kind": "project", "title": {"$param": "title"}, "outcome": "", "fields": {}},
        "efforts": [], "tasks": [], "criteria": [], "documents": [],
        "protocol": None,
    }


def blank_project_template() -> WorkTemplate:
    return work_template(
        BLANK_TEMPLATE_ID,
        parameters={
            "type": "object", "additionalProperties": False,
            "properties": {"title": {"type": "string", "default": "Untitled project", "minLength": 1}},
        },
        seed=_blank_seed(),
    )


def render_blank_project(parameters: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """Render the built-in zero-task starter using the common work fields."""
    rendered = render_template(blank_project_template(), parameters)
    project = dict(rendered.seed["project"])
    project.pop("local_id", None)
    project.setdefault("instructions", "")
    project.setdefault("requires", [])
    project.setdefault("acceptance", {})
    project.setdefault("custom", {})
    project.setdefault("documents", [])
    result = {"project": project, "tasks": []}
    validate_project_fields(result["project"])
    return result


PROJECT_FIELDS = ("title", "outcome", "scope", "approach", "acceptance", "tasks", "documents", "metadata")
TASK_FIELDS = ("title", "name", "namespace", "key", "instructions", "dependencies", "criteria", "review_choice", "profile_ref", "allowance_ref")
CRITERION_FIELDS = ("title", "name", "namespace", "key", "description", "review_choice", "profile_ref", "allowance_ref")
COMMON_FIELD_DEFINITIONS = {"project": PROJECT_FIELDS, "task": TASK_FIELDS, "criterion": CRITERION_FIELDS}


def validate_project_fields(value: Mapping[str, Any], *, pending: bool = True) -> None:
    """Validate the project projection used by both blank rendering and work."""
    if not isinstance(value, Mapping):
        raise TemplateValidationError("project projection must be an object")
    for field in ("title", "outcome"):
        if field in value and not isinstance(value[field], str):
            raise TemplateValidationError(f"project {field} must be text")
    if value.get("title") is not None and not str(value["title"]).strip():
        raise TemplateValidationError("project title must be non-blank")
    if not pending and not str(value.get("outcome", "")).strip():
        raise TemplateValidationError("prepared projects require a non-blank outcome")
    if "tasks" in value and (not isinstance(value["tasks"], list) or value["tasks"]):
        raise TemplateValidationError("blank project projection must contain zero tasks")


@dataclass(frozen=True)
class TemplateResult:
    """Durable result of one template request."""

    project: WorkRecord
    records: Tuple[WorkRecord, ...]
    local_refs: Mapping[str, ResourceRef]
    receipts: Tuple[Any, ...]
    rendered: RenderedTemplate
    protocol_adopted: bool = False
    document_refs: Mapping[str, ResourceRef] = field(default_factory=dict)
    association_refs: Mapping[str, ResourceRef] = field(default_factory=dict)

    @property
    def record(self) -> WorkRecord:
        return self.records[0] if self.records else self.project

    @property
    def receipt(self) -> Any:
        return self.receipts[0] if self.receipts else None

    @property
    def mapping(self) -> Mapping[str, ResourceRef]:
        return self.local_refs

    @property
    def dat_receipts(self) -> Tuple[Any, ...]:
        """The DAT receipts included in the one result receipt envelope."""
        return tuple(receipt for receipt in self.receipts if getattr(receipt, "operation", "").startswith("dat.content."))


def _node_list(seed: Mapping[str, Any]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    if "work" in seed:
        work = seed["work"]
        if not isinstance(work, list):
            raise TemplateValidationError("seed work must be a list")
        all_work: dict[str, dict[str, Any]] = {}
        project_names: set[str] = set()
        for node in work:
            if not isinstance(node, Mapping):
                raise TemplateValidationError("each seed work entry must be an object")
            value = dict(node)
            name = _local_name(value)
            if name in all_work:
                raise TemplateValidationError("seed local identities must be unique")
            kind = value.get("kind")
            if not isinstance(kind, str) or not kind.strip():
                raise TemplateValidationError(f"work kind for {name!r} must be text")
            all_work[name] = value
            if kind.removeprefix("work.") == "project":
                project_names.add(name)
                continue
            nodes.append(value)
        if len(project_names) > 1:
            raise TemplateValidationError("seed work may contain at most one project")
        links = seed.get("links", [])
        if not isinstance(links, list):
            raise TemplateValidationError("seed links must be a list")
        for link in links:
            if not isinstance(link, Mapping):
                raise TemplateValidationError("each seed link must be an object")
            relation = link.get("relation")
            if relation not in {"requires", "covers"}:
                raise TemplateValidationError(f"unsupported work link relation: {relation!r}")
            source = _marker_name(link.get("from"))
            target = _marker_name(link.get("to"))
            if source is None or target is None:
                raise TemplateReferenceError("work links must use local references")
            _text(source, "work link from")
            _text(target, "work link to")
            if source not in all_work or target not in all_work:
                raise TemplateReferenceError("work link references an unknown local identity")
            source_node = all_work[source]
            if source not in project_names:
                if relation == "requires":
                    source_node.setdefault("dependencies", []).append({"$local": target})
                source_node.setdefault(_WORK_LINKS_KEY, []).append(
                    {"from": {"$local": source}, "to": {"$local": target}, "relation": relation}
                )
    categories = (("efforts", "effort"), ("tasks", "task"), ("criteria", "criterion"), ("scenarios", "scenario"), ("gates", "gate"))
    if "nodes" in seed:
        if not isinstance(seed["nodes"], list):
            raise TemplateValidationError("seed nodes must be a list")
        for node in seed["nodes"]:
            if not isinstance(node, Mapping):
                raise TemplateValidationError("each seed node must be an object")
            nodes.append(dict(node))
    for plural, kind in categories:
        values = seed.get(plural, [])
        singular = seed.get(kind)
        if singular is not None:
            if values:
                raise TemplateValidationError(f"seed cannot contain both {plural} and {kind}")
            values = [singular]
        if plural == "tasks" and "task_bundle" in seed:
            bundle = seed["task_bundle"]
            if not isinstance(bundle, list):
                raise TemplateValidationError("seed task_bundle must be a list")
            if values:
                raise TemplateValidationError("seed cannot contain both tasks and task_bundle")
            values = bundle
        if not isinstance(values, list):
            raise TemplateValidationError(f"seed {plural} must be a list")
        for node in values:
            if not isinstance(node, Mapping):
                raise TemplateValidationError(f"each {plural} entry must be an object")
            value = dict(node)
            value.setdefault("kind", kind)
            nodes.append(value)
    return nodes


def _seed_work_fields(node: Mapping[str, Any], *, status: Any = None, links: Any = None, documents: Any = None, document_links: Any = None) -> dict[str, Any]:
    """Admit neutral seed fields into the public WRK ``fields`` mapping."""
    fields = dict(node.get("fields", {}))
    for key in ("outcome", "custom", "description", "instructions", "criteria", "body", "acceptance", "metadata", "documents", "document_links"):
        if key in node:
            fields[key] = deepcopy(node[key])
    if status is not None:
        fields["status"] = deepcopy(status)
    if links:
        fields["links"] = deepcopy(links)
    if documents:
        fields["documents"] = deepcopy(documents)
    if document_links:
        fields["document_links"] = deepcopy(document_links)
    return fields


def _local_name(node: Mapping[str, Any]) -> str:
    value = node.get("local_id", node.get("key", node.get("id")))
    if isinstance(value, Mapping):
        raise TemplateValidationError("node identity must be a literal local name")
    return _text(value, "node local_id")


def _marker_name(value: Any) -> Optional[str]:
    if isinstance(value, Mapping) and set(value) == {"$local"}:
        return value["$local"]
    return None


def _edges(nodes: Sequence[Mapping[str, Any]], names: set[str]) -> dict[str, set[str]]:
    edges = {name: set() for name in names}
    for node in nodes:
        name = _local_name(node)
        parent = node.get("parent", node.get("parent_ref"))
        parent_name = _marker_name(parent)
        if parent_name is not None:
            if parent_name not in names:
                raise TemplateReferenceError(f"missing local parent: {parent_name}")
            edges[name].add(parent_name)
        deps = node.get("dependencies", node.get("depends_on", []))
        if not isinstance(deps, list):
            raise TemplateValidationError(f"dependencies for {name!r} must be a list")
        for dependency in deps:
            dependency_name = _marker_name(dependency)
            if dependency_name is not None:
                if dependency_name not in names:
                    raise TemplateReferenceError(f"missing local dependency: {dependency_name}")
                edges[name].add(dependency_name)
    state: dict[str, int] = {}
    def visit(name: str) -> None:
        if state.get(name) == 1:
            raise TemplateCycleError("parent/dependency graph contains a cycle")
        if state.get(name) == 2:
            return
        state[name] = 1
        for prerequisite in edges[name]:
            visit(prerequisite)
        state[name] = 2
    for name in names:
        visit(name)
    return edges


def _review_choice(value: Any) -> Optional[dict[str, Any]]:
    if value is None:
        return None
    if isinstance(value, str):
        if value not in {"normal", "xhard"}:
            raise TemplateValidationError("review_choice must be normal or xhard")
        return {"choice": value, "separate_reviewer": True, "extra_stage": False}
    if not isinstance(value, Mapping):
        raise TemplateValidationError("review_choice must be a choice name or object")
    choice = value.get("choice", value.get("route", value.get("purpose")))
    if choice not in {"normal", "xhard"}:
        raise TemplateValidationError("review_choice must name normal or xhard")
    result = dict(value)
    result["choice"] = choice
    if result.get("extra_stage") or len(result.get("review_sequence", ())) > 1:
        raise TemplateValidationError("review choice cannot force two reviews")
    result.setdefault("separate_reviewer", True)
    result.setdefault("extra_stage", False)
    return result


class TemplateCatalog:
    """Explicit in-process catalog of already-resolved pack resources."""

    def __init__(self, resources: Iterable[Union[WorkTemplate, WorkProtocol]] = ()) -> None:
        self.templates: dict[str, WorkTemplate] = {}
        self.protocols: dict[str, WorkProtocol] = {}
        for resource in resources:
            self.register(resource)

    def register(self, resource: Union[WorkTemplate, WorkProtocol]) -> Union[WorkTemplate, WorkProtocol]:
        if isinstance(resource, WorkTemplate):
            if resource.id in self.templates and self.templates[resource.id] != resource:
                raise TemplateValidationError(f"template identity already has another revision: {resource.id}")
            self.templates[resource.id] = resource
            return resource
        if isinstance(resource, WorkProtocol):
            if resource.id in self.protocols and self.protocols[resource.id] != resource:
                raise TemplateValidationError(f"protocol identity already has another revision: {resource.id}")
            self.protocols[resource.id] = resource
            return resource
        raise TemplateValidationError("catalog resources must be WorkTemplate or WorkProtocol")

    def template(self, value: Union[str, WorkTemplate]) -> WorkTemplate:
        if isinstance(value, WorkTemplate):
            return value
        if value == BLANK_TEMPLATE_ID:
            return self.templates.get(value, blank_project_template())
        try:
            return self.templates[value]
        except KeyError as exc:
            raise UnknownTemplateError(f"unknown work template: {value}") from exc

    def protocol(self, value: Union[str, WorkProtocol]) -> WorkProtocol:
        if isinstance(value, WorkProtocol):
            return value
        try:
            return self.protocols[value]
        except KeyError as exc:
            raise TemplateError(f"unknown work protocol: {value}") from exc


class TemplateEngine:
    """Instantiate resolved resources through a supplied store and WRK API."""

    def __init__(self, store: Any, *, graph: Any = None, actor: Any = None, resources: Iterable[Union[WorkTemplate, WorkProtocol]] = ()) -> None:
        if not hasattr(store, "get_identity") or not hasattr(store, "transaction"):
            raise TypeError("store must be the supplied FND Store")
        self.store = store
        if graph is None:
            from herzchen.domains.work import WorkGraph
            graph = WorkGraph(store, actor=actor)
        self.graph = graph
        self.actor = actor
        self.catalog = TemplateCatalog(resources)

    def register(self, resource: Union[WorkTemplate, WorkProtocol]) -> Union[WorkTemplate, WorkProtocol]:
        return self.catalog.register(resource)

    def render(self, template: Union[str, WorkTemplate], parameters: Optional[Mapping[str, Any]] = None) -> RenderedTemplate:
        return render_template(self.catalog.template(template), parameters)

    def instantiate(
        self,
        template: Union[str, WorkTemplate],
        parameters: Optional[Mapping[str, Any]] = None,
        *,
        project: Any = None,
        owner: Any = None,
        logical_request_key: Optional[str] = None,
        actor: Any = None,
    ) -> TemplateResult:
        resource = self.catalog.template(template)
        rendered = render_template(resource, parameters)
        seed = rendered.seed
        nodes = _node_list(seed)
        names = [_local_name(node) for node in nodes]
        if len(set(names)) != len(names):
            raise TemplateValidationError("seed local identities must be unique")
        name_set = set(names)
        edges = _edges(nodes, name_set)
        namespaces = seed.get("namespaces", {})
        owner_target = project if project is not None else owner
        project_seed = seed.get("project")
        if project_seed is None and isinstance(seed.get("work"), list):
            project_seed = next(
                (node for node in seed["work"]
                 if isinstance(node, Mapping) and node.get("kind") == "project"),
                None,
            )
        if project_seed is not None and not isinstance(project_seed, Mapping):
            raise TemplateValidationError("seed project must be an object")
        if owner_target is None and resource.id != BLANK_TEMPLATE_ID and project_seed is None:
            raise TemplateReferenceError("template instantiation requires an existing project owner")
        if owner_target is not None:
            owner_record = self.graph.get(owner_target)
            if owner_record.kind is not WorkKind.PROJECT:
                raise TemplateReferenceError("template owner must be a project")
        else:
            owner_record = None
        if resource.id == BLANK_TEMPLATE_ID and nodes:
            raise TemplateValidationError("blank project must contain zero work nodes")
        request = _request_key(logical_request_key, resource, rendered)
        self._validate_seed_references(seed, nodes, owner_record, name_set)
        document_values, document_link_values = self._document_seed_values(seed, name_set)
        ordered = self._ordered_nodes(nodes, edges)

        # All checks above are intentionally before the first public WRK
        # command.  The public commands then provide the real FND receipts and
        # events; no parallel writer or test-only transaction is introduced.
        receipts: list[Any] = []
        local_refs: dict[str, ResourceRef] = {}
        records: list[WorkRecord] = []
        with self.store.transaction():
            if owner_record is None:
                title = project_seed.get("title") if project_seed else None
                outcome = project_seed.get("outcome", "") if project_seed else ""
                metadata = dict(project_seed.get("fields", {})) if project_seed else {}
                metadata["template_origin"] = _origin(resource)
                owner_record = self.graph.create_project(title=title, outcome=outcome, metadata=metadata,
                                                         logical_request_key=request + ":project", actor=actor)
                receipts.append(self.store.get_receipt(request + ":project"))
            if resource.id == BLANK_TEMPLATE_ID:
                return TemplateResult(owner_record, (), {"project": owner_record.ref}, tuple(receipts), rendered, False)

            for node in ordered:
                name = _local_name(node)
                kind = node.get("kind")
                if isinstance(kind, str):
                    kind = kind.removeprefix("work.")
                try:
                    work_kind = WorkKind(kind)
                except (TypeError, ValueError) as exc:
                    raise TemplateValidationError(f"unsupported template work kind: {kind!r}") from exc
                parent = self._resolve_seed_ref(node.get("parent", node.get("parent_ref")), local_refs, owner_record)
                if parent is None:
                    parent = owner_record
                dependencies = tuple(self._resolve_seed_ref(ref, local_refs, owner_record, required=True) for ref in node.get("dependencies", node.get("depends_on", [])))
                if not isinstance(node.get("fields", {}), Mapping):
                    raise TemplateValidationError(f"fields for {name!r} must be an object")
                fields = _seed_work_fields(
                    node,
                    status=seed.get("status") if "work" in seed else None,
                    links=node.get(_WORK_LINKS_KEY),
                    documents=document_values.get(name),
                    document_links=document_link_values.get(name),
                )
                fields.update({key: deepcopy(value) for key, value in node.items() if key in {"namespace", "key", "instructions", "description", "criteria", "profile_ref", "allowance_ref"}})
                default_namespace = TASK_NAMESPACE if work_kind is WorkKind.TASK else CRITERION_NAMESPACE if work_kind is WorkKind.CRITERION else "work"
                namespace = node.get("namespace", namespaces.get(work_kind.value, namespaces.get(work_kind.value + "s", default_namespace)))
                fields["namespace"] = _text(namespace, "node namespace")
                fields["key"] = node.get("key", name)
                choice = _review_choice(node.get("review_choice", node.get("review")))
                if choice is not None:
                    fields["review_choice"] = choice
                fields["template_origin"] = dict(_origin(resource), local_id=name)
                for field in ("profile_ref", "allowance_ref"):
                    if field in node:
                        fields[field] = _ref_dict(_ref(node[field], field))
                kwargs = {"title": node.get("title", node.get("name", name)), "name": node.get("name", node.get("title", name)),
                          "alias": node.get("alias", name), "aliases": tuple(node.get("aliases", ())), "parent": parent,
                          "dependencies": dependencies, "fields": fields, "logical_request_key": request + ":" + name, "actor": actor}
                record = self.graph.create(work_kind, project=owner_record, **kwargs)
                local_refs[name] = record.ref
                records.append(record)
                receipts.append(self.store.get_receipt(request + ":" + name))

            # DAT's command handler uses nested FND savepoints here.  The
            # outer TemplateEngine transaction remains the single durable
            # boundary for work, document, and association mutations.
            content = ContentCommandHandler(self.store)
            content_actor = self._content_actor(actor)
            document_refs: dict[str, ResourceRef] = {}
            association_refs: dict[str, ResourceRef] = {}
            for document in seed.get("documents", []):
                if "local_id" not in document:
                    continue
                local_id = document["local_id"]
                document_ref = ResourceRef(
                    self.store.authority,
                    "dat.content.document",
                    self._document_identity(request, resource, rendered, document),
                )
                document_value = self._content_document(document, document_ref, owner_record, content_actor)
                revision = ContentRevision(
                    document_value.ref,
                    self._document_revision(request, resource, rendered, document),
                    document["content"],
                    content_actor,
                    initial=True,
                )
                document_receipt = content.execute(
                    content.build_create_document(
                        self._content_context(
                            content_actor,
                            request + ":document:" + local_id,
                            {"document": document_value, "revision": revision},
                        ),
                        document_value,
                        revision,
                    )
                )
                document_refs[local_id] = document_value.ref
                receipts.append(document_receipt)

            for index, link in enumerate(seed.get("document_links", [])):
                subject_name = _marker_name(link["subject"])
                if subject_name is None:
                    raise TemplateReferenceError(f"document link[{index}] subject must use a local reference")
                subject = local_refs.get(subject_name)
                if subject is None:
                    raise TemplateReferenceError(f"document link[{index}] subject was not instantiated: {subject_name}")
                binding = self._document_binding(link, document_refs)
                association = DocumentAssociation(
                    subject,
                    link["namespace"],
                    link["key"],
                    binding,
                    link.get("access_mode", "read"),
                )
                link_key = request + ":link:" + subject_name + ":" + link["namespace"] + ":" + link["key"]
                link_receipt = content.execute(
                    content.build_link(
                        self._content_context(content_actor, link_key, {"association": association}),
                        association,
                    )
                )
                association_refs["{}:{}:{}".format(subject_name, link["namespace"], link["key"])] = ResourceRef(
                    subject.authority, "document-association", association.identity,
                )
                receipts.append(link_receipt)
        return TemplateResult(owner_record, tuple(records), local_refs, tuple(receipts), rendered, False, document_refs, association_refs)

    def instantiate_task(self, template: Union[str, WorkTemplate], parameters: Optional[Mapping[str, Any]] = None, *, project: Any, logical_request_key: Optional[str] = None, actor: Any = None) -> TemplateResult:
        return self.instantiate(template, parameters, project=project, logical_request_key=logical_request_key, actor=actor)

    instantiate_bundle = instantiate

    def instantiate_effort(self, template: Union[str, WorkTemplate], parameters: Optional[Mapping[str, Any]] = None, *, project: Any, logical_request_key: Optional[str] = None, actor: Any = None) -> TemplateResult:
        result = self.instantiate(template, parameters, project=project, logical_request_key=logical_request_key, actor=actor)
        if not any(record.kind is WorkKind.EFFORT for record in result.records):
            raise TemplateValidationError("template does not instantiate an effort")
        return result

    def adopt_protocol(self, project: Any, protocol: Union[str, WorkProtocol], *, logical_request_key: Optional[str] = None, actor: Any = None) -> WorkRecord:
        """Explicitly attach protocol metadata; never called by instantiate."""
        resource = self.catalog.protocol(protocol)
        for field in ("profile_ref", "allowance_ref"):
            if field in resource.definition:
                self._resolve_external(_ref(resource.definition[field], field), field)
        record = self.graph.get(project)
        if record.kind is not WorkKind.PROJECT:
            raise TemplateReferenceError("protocol adoption requires a project")
        fields = dict(record.payload.get("fields", {}))
        fields["protocol_ref"] = _origin(resource)
        fields["protocol_definition"] = deepcopy(dict(resource.definition))
        return self.graph.revise(record, fields=fields, logical_request_key=logical_request_key, actor=actor)

    def resume(self, target: Any) -> WorkRecord:
        """Read the existing durable record; this operation never creates."""
        return self.graph.get(target)

    def clone_seed(self, template: Union[str, WorkTemplate]) -> WorkTemplate:
        """Return a planning clone with live/evidence/consumed facts removed."""
        resource = self.catalog.template(template)
        return clone_seed(resource)

    clone = clone_seed

    def _validate_seed_references(self, seed: Mapping[str, Any], nodes: Sequence[Mapping[str, Any]], owner: Optional[WorkRecord], names: set[str]) -> None:
        namespaces = seed.get("namespaces", {})
        if namespaces and not isinstance(namespaces, Mapping):
            raise TemplateValidationError("seed namespaces must be an object")
        for node in nodes:
            name = _local_name(node)
            kind = str(node.get("kind", "")).removeprefix("work.")
            try:
                work_kind = WorkKind(kind)
            except ValueError as exc:
                raise TemplateValidationError(f"unsupported template work kind: {kind!r}") from exc
            title = node.get("title", node.get("name", name))
            _text(title, "node title")
            if "name" in node:
                _text(node["name"], "node name")
            if "alias" in node:
                _text(node["alias"], "node alias")
            aliases = node.get("aliases", ())
            if not isinstance(aliases, (list, tuple)):
                raise TemplateValidationError(f"aliases for {name!r} must be a list")
            for alias in aliases:
                _text(alias, "node alias")
            alias_values = list(aliases)
            if node.get("alias") is not None:
                alias_values.insert(0, node["alias"])
            if len(alias_values) != len(set(alias_values)):
                raise TemplateValidationError(f"aliases for {name!r} must be unique")
            if not isinstance(node.get("fields", {}), Mapping):
                raise TemplateValidationError(f"fields for {name!r} must be an object")
            default_namespace = TASK_NAMESPACE if work_kind is WorkKind.TASK else CRITERION_NAMESPACE if work_kind is WorkKind.CRITERION else "work"
            namespace = node.get("namespace", namespaces.get(work_kind.value, namespaces.get(work_kind.value + "s", default_namespace)))
            _text(namespace, "node namespace")
            for ref_value, field in ((node.get("parent", node.get("parent_ref")), "parent"),):
                self._validate_ref_value(ref_value, names, owner, field)
            deps = node.get("dependencies", node.get("depends_on", []))
            if not isinstance(deps, list):
                raise TemplateValidationError(f"dependencies for {name!r} must be a list")
            for ref_value in deps:
                self._validate_ref_value(ref_value, names, owner, "dependency")
            for field in ("profile_ref", "allowance_ref"):
                if field in node:
                    self._resolve_external(_ref(node[field], field), field)
            _review_choice(node.get("review_choice", node.get("review")))
            if work_kind is WorkKind.CRITERION and node.get("namespace", CRITERION_NAMESPACE) != CRITERION_NAMESPACE:
                _text(node["namespace"], "criterion namespace")

        # Document references are resolved, but document creation/adoption is
        # DAT's responsibility.  A template cannot smuggle an untyped path or
        # a same-looking identifier into a work payload.
        self._document_seed_values(seed, names)
        for field in ("profile_ref", "allowance_ref"):
            if field in seed:
                self._resolve_external(_ref(seed[field], field), field)
        protocol_ref = seed.get("protocol_ref")
        if protocol_ref is not None:
            reference = _ref(protocol_ref, "protocol ref")
            if reference.authority == RESOURCE_AUTHORITY and reference.kind == PROTOCOL_KIND:
                protocol = self.catalog.protocol(reference.id)
                if protocol.revision != reference.revision:
                    raise TemplateReferenceError("protocol ref revision is not the catalog revision")
            else:
                self._resolve_external(reference, "protocol ref")

    def _document_seed_values(self, seed: Mapping[str, Any], names: set[str]) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
        documents = seed.get("documents", [])
        if not isinstance(documents, list):
            raise TemplateValidationError("seed documents must be a list")
        by_local: dict[str, dict[str, Any]] = {}
        for index, document in enumerate(documents):
            if not isinstance(document, Mapping):
                raise TemplateValidationError(f"document[{index}] must be an object")
            _json(document)
            if "local_id" in document:
                local_id = _text(document["local_id"], f"document[{index}] local_id")
                if local_id in by_local:
                    raise TemplateValidationError(f"duplicate document local_id: {local_id}")
                if "title" not in document or "content" not in document:
                    raise TemplateValidationError(f"document[{index}] requires title and content")
                _text(document["title"], f"document[{index}] title")
                _json(document["content"])
                for field in ("role", "maintainer"):
                    if field in document:
                        _text(document[field], f"document[{index}] {field}")
                if document.get("visibility", "private") not in {"private", "shared", "public"}:
                    raise TemplateValidationError(f"document[{index}] visibility is invalid")
                if document.get("access_mode", document.get("access", "append")) not in {"read", "write", "append"}:
                    raise TemplateValidationError(f"document[{index}] access_mode is invalid")
                if "authoring_scope" in document and "scope" in document:
                    raise TemplateValidationError(f"document[{index}] supplied scope twice")
                if "authoring_scope" in document:
                    _ref(document["authoring_scope"], f"document[{index}] authoring_scope")
                if "scope" in document:
                    _ref(document["scope"], f"document[{index}] scope")
                if document.get("import_mode", "owned") != "owned":
                    raise TemplateValidationError(f"document[{index}] local import_mode must be owned")
                if "source_ref" in document:
                    raise TemplateValidationError(f"document[{index}] local documents cannot carry source_ref")
                by_local[local_id] = dict(document)
            elif "ref" in document:
                self._resolve_document_external(_ref(document["ref"], f"document[{index}] ref"), f"document[{index}] ref")
            else:
                raise TemplateValidationError(f"document[{index}] requires local_id or typed ref")

        links = seed.get("document_links", [])
        if not isinstance(links, list):
            raise TemplateValidationError("seed document_links must be a list")
        by_subject: dict[str, list[dict[str, Any]]] = {}
        for index, link in enumerate(links):
            if not isinstance(link, Mapping):
                raise TemplateValidationError(f"document link[{index}] must be an object")
            _json(link)
            subject = _marker_name(link.get("subject"))
            if subject is None:
                raise TemplateReferenceError(f"document link[{index}] subject must use a local reference")
            _text(subject, f"document link[{index}] subject")
            if subject not in names:
                raise TemplateReferenceError(f"document link[{index}] references unknown subject: {subject}")
            document = link.get("document")
            document_local = _marker_name(document)
            external_document = None
            if document_local is not None:
                _text(document_local, f"document link[{index}] document")
                if document_local not in by_local:
                    raise TemplateReferenceError(f"document link[{index}] references unknown document: {document_local}")
            else:
                external_document = _ref(document, f"document link[{index}] document")
                self._resolve_document_external(external_document, f"document link[{index}] document")
            namespace = _text(link.get("namespace", "work"), f"document link[{index}] namespace")
            key = _text(link.get("key", "document"), f"document link[{index}] key")
            binding = link.get("binding", "current")
            if binding not in {"current", "pinned"}:
                raise TemplateValidationError(f"document link[{index}] binding must be current or pinned")
            if binding == "current" and external_document is not None and external_document.revision is not None:
                raise TemplateValidationError(f"document link[{index}] current binding cannot carry a revision")
            access_mode = link.get("access_mode", "read")
            if access_mode not in {"read", "append"}:
                raise TemplateValidationError(f"document link[{index}] access_mode must be read or append")
            if binding == "pinned":
                revision = link.get("revision_ref", link.get("revision"))
                if revision is None:
                    raise TemplateValidationError(f"document link[{index}] pinned binding requires a revision")
                if isinstance(revision, Mapping):
                    self._resolve_external(_ref(revision, f"document link[{index}] revision"), f"document link[{index}] revision")
                else:
                    _text(revision, f"document link[{index}] revision")
            value = dict(link)
            value["namespace"] = namespace
            value["key"] = key
            value["binding"] = binding
            if "access_mode" in link:
                value["access_mode"] = access_mode
            by_subject.setdefault(subject, []).append(value)

        return ({subject: [deepcopy(by_local[_marker_name(link["document"])]) for link in subject_links if _marker_name(link.get("document")) is not None] for subject, subject_links in by_subject.items()}, by_subject)

    def _content_actor(self, actor: Any) -> AuthenticatedActor:
        selected = actor or self.actor or getattr(self.graph, "default_actor", None)
        if selected is None:
            return AuthenticatedActor(self.store.authority, "pkg-template-engine", "pkg-template-engine")
        if not isinstance(selected, AuthenticatedActor):
            raise TemplateValidationError("template DAT writes require an authenticated actor")
        return selected

    @staticmethod
    def _content_context(actor: AuthenticatedActor, key: str, payload: Mapping[str, Any]) -> TransactionContext:
        digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
        return TransactionContext(actor, key, digest, expected_version=0)

    @staticmethod
    def _document_identity(request: str, resource: WorkTemplate, rendered: RenderedTemplate, document: Mapping[str, Any]) -> str:
        material = {"request": request, "resource": resource.ref, "rendered": rendered.seed, "document": document}
        return "template-" + hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()[:32]

    @staticmethod
    def _document_revision(request: str, resource: WorkTemplate, rendered: RenderedTemplate, document: Mapping[str, Any]) -> str:
        material = {"request": request, "resource": resource.ref, "rendered": rendered.seed, "document": document, "purpose": "initial"}
        return "rev-" + hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()[:32]

    @staticmethod
    def _content_document(document: Mapping[str, Any], reference: ResourceRef, owner: Optional[WorkRecord], actor: AuthenticatedActor) -> ContentDocument:
        scope_value = document.get("authoring_scope", document.get("scope", owner.ref if owner is not None else None))
        scope = None if scope_value is None else _ref(scope_value, "document authoring_scope")
        import_mode = document.get("import_mode", "owned")
        if import_mode != "owned":
            raise TemplateValidationError("local template documents must use owned import_mode")
        if "source_ref" in document:
            raise TemplateValidationError("local template documents cannot carry source_ref")
        writable = document.get("writable", True)
        if not isinstance(writable, bool):
            raise TemplateValidationError("document writable must be a boolean")
        try:
            return ContentDocument(
                reference,
                document.get("role", "template-document"),
                document.get("visibility", "private"),
                document.get("access_mode", document.get("access", "append")),
                document.get("maintainer", actor.actor),
                scope,
                import_mode=import_mode,
                writable=writable,
            )
        except ValueError as exc:
            raise TemplateValidationError("local document metadata violates the DAT contract") from exc

    @staticmethod
    def _document_binding(link: Mapping[str, Any], document_refs: Mapping[str, ResourceRef]) -> ReferenceBinding:
        local = _marker_name(link.get("document"))
        if local is not None:
            try:
                document = document_refs[local]
            except KeyError as exc:
                raise TemplateReferenceError(f"document link references an unmaterialized document: {local}") from exc
        else:
            document = _ref(link["document"], "document link document")
        binding = link["binding"]
        if binding == "current":
            document = ResourceRef(document.authority, document.kind, document.id)
        else:
            revision = link.get("revision_ref", link.get("revision"))
            if revision is None:
                if document.revision is None:
                    raise TemplateValidationError("pinned document binding requires a revision")
            elif isinstance(revision, Mapping):
                document = _ref(revision, "document link revision")
            else:
                document = ResourceRef(document.authority, document.kind, document.id, revision)
        return ReferenceBinding(document, binding)

    def _validate_ref_value(self, value: Any, names: set[str], owner: Optional[WorkRecord], field: str) -> None:
        if value is None:
            return
        local = _marker_name(value)
        if local is not None:
            if local not in names:
                raise TemplateReferenceError(f"missing local {field}: {local}")
            return
        if isinstance(value, str):
            raise TemplateReferenceError(f"{field} must use an explicit $local or typed ResourceRef")
        reference = self._resolve_external(_ref(value, field), field)
        try:
            record = self.graph.get(reference)
        except Exception as exc:
            raise TemplateReferenceError(f"{field} is not a work reference: {reference.to_json()}") from exc
        if record.kind not in set(WorkKind):
            raise TemplateReferenceError(f"{field} is not a supported work reference")

    def _resolve_external(self, reference: ResourceRef, field: str) -> ResourceRef:
        if reference.authority != self.store.authority:
            raise TemplateReferenceError(f"{field} crosses store authority")
        if self.store.get_identity(reference) is None:
            raise TemplateReferenceError(f"missing {field}: {reference.to_json()}")
        return reference

    def _resolve_document_external(self, reference: ResourceRef, field: str) -> ResourceRef:
        self._resolve_external(reference, field)
        if not ContentCommandHandler(self.store).read(reference):
            raise TemplateReferenceError(f"missing DAT document: {reference.to_json()}")
        return reference

    def _resolve_seed_ref(self, value: Any, local_refs: Mapping[str, ResourceRef], owner: WorkRecord, *, required: bool = False) -> Optional[WorkRecord]:
        if value is None:
            return None
        local = _marker_name(value)
        if local is not None:
            try:
                return self.graph.get(local_refs[local])
            except KeyError as exc:
                raise TemplateReferenceError(f"local reference not yet instantiated: {local}") from exc
        reference = self._resolve_external(_ref(value), "work reference")
        return self.graph.get(reference)

    @staticmethod
    def _ordered_nodes(nodes: Sequence[Mapping[str, Any]], edges: Mapping[str, set[str]]) -> list[Mapping[str, Any]]:
        remaining = {_local_name(node): node for node in nodes}
        ordered: list[Mapping[str, Any]] = []
        while remaining:
            ready = sorted(name for name in remaining if not (edges[name] & set(remaining)))
            if not ready:
                raise TemplateCycleError("parent/dependency graph cannot be ordered")
            for name in ready:
                ordered.append(remaining.pop(name))
        return ordered


TemplateManager = TemplateEngine
WorkTemplateEngine = TemplateEngine


__all__ = [
    "BLANK_TEMPLATE_ID", "COMMON_FIELD_DEFINITIONS", "CRITERION_NAMESPACE", "PROJECT_FIELDS", "TASK_NAMESPACE",
    "TemplateCatalog", "TemplateEngine", "TemplateError", "TemplateManager", "TemplateReferenceError",
    "TemplateResult", "TemplateValidationError", "RenderedTemplate", "UnknownTemplateError", "WorkProtocol",
    "WorkTemplate", "WorkTemplateEngine", "blank_project_template", "expand_seed", "render_blank_project",
    "render_template", "validate_parameters", "validate_project_fields", "validate_template", "clone_seed", "work_protocol", "work_template",
]
