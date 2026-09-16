"""Finite command facades and their serialized consumer boundary.

Trusted composition builds local facades.  Consumers use the JSON/Unix-socket
transport below, so the owner retains the engine, Store and SQLite connection.
"""

from __future__ import annotations

import base64
from dataclasses import fields, is_dataclass
from enum import Enum
import importlib
import inspect
import json
import os
from pathlib import Path
import secrets
import socket
import tempfile
import threading
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple


SERIALIZED_COMMAND_REVISION = "herzchen.command-transport.v1"
_TAG = "$herzchen"
_MAX_BYTES = 8 * 1024 * 1024
_FORBIDDEN = frozenset({
    "connection", "transaction", "mutate", "put_identity", "revise_identity",
    "put_reference", "append_event", "register_domain", "register_domain_handler",
    "domain_handler", "execute_sql", "cursor",
})
_COMPOSITION = threading.local()
_READER_ENDPOINTS = (
    "foreign_keys_enabled", "get_identity", "get_record", "registered_domains",
    "get_reference", "get_receipt", "list_events", "snapshot_counts",
)
_OWNER_ONLY_ENDPOINTS = frozenset({"create_and_open", "lifecycle_handler", "retry_materialisation"})


class CommandTransportError(RuntimeError):
    pass


class WriterAuthorityDenied(CommandTransportError, AttributeError):
    pass


class CommandTransportClosed(CommandTransportError):
    pass


class RemoteCommandError(CommandTransportError):
    pass


def _qname(value: type[Any]) -> str:
    return value.__module__ + ":" + value.__qualname__


def _load_type(name: str) -> type[Any]:
    module_name, separator, qualname = name.partition(":")
    if not separator or not module_name.startswith("herzchen."):
        raise CommandTransportError("wire types must be declared Herzchen values")
    value: Any = importlib.import_module(module_name)
    for part in qualname.split("."):
        if not part or part.startswith("_"):
            raise CommandTransportError("private wire types are forbidden")
        value = getattr(value, part)
    if not isinstance(value, type) or not (is_dataclass(value) or issubclass(value, Enum)):
        raise CommandTransportError("wire type is not a declared data value")
    return value


def _reject_authority(value: Any) -> None:
    if type(value).__module__ == "sqlite3" and type(value).__name__ in {"Connection", "Cursor"}:
        raise WriterAuthorityDenied("SQLite connections cannot cross the consumer boundary")
    kind = type(value)
    if kind.__module__ == "herzchen.kernel.store" and kind.__name__ in {
        "Store", "DomainHandler", "DomainCommandPort", "OperationOwnerCapability", "DomainOwnerCapability", "RuntimeDomainOwner", "RuntimeOperationReader", "Transaction", "ConsumerStore",
    }:
        raise WriterAuthorityDenied(kind.__name__ + " cannot cross the consumer boundary")
    if callable(value) and not isinstance(value, type):
        raise WriterAuthorityDenied("callables cannot cross the consumer boundary")


def encode_wire(value: Any) -> Any:
    """Encode bounded data as JSON; pickle and executable values are absent."""
    _reject_authority(value)
    if isinstance(value, Enum):
        return {_TAG: "enum", "type": _qname(type(value)), "value": encode_wire(value.value)}
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (bytes, bytearray)):
        return {_TAG: "bytes", "base64": base64.b64encode(bytes(value)).decode("ascii")}
    if is_dataclass(value) and not isinstance(value, type):
        return {_TAG: "dataclass", "type": _qname(type(value)),
                "fields": {field.name: encode_wire(getattr(value, field.name)) for field in fields(value)}}
    if isinstance(value, tuple):
        return {_TAG: "tuple", "items": [encode_wire(item) for item in value]}
    if isinstance(value, list):
        return [encode_wire(item) for item in value]
    if isinstance(value, Mapping):
        return {_TAG: "mapping", "items": [[encode_wire(key), encode_wire(item)] for key, item in value.items()]}
    if isinstance(value, Path):
        return {_TAG: "path", "value": str(value)}
    raise CommandTransportError("unsupported wire value: " + _qname(type(value)))


def decode_wire(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, list):
        return [decode_wire(item) for item in value]
    if not isinstance(value, dict):
        raise CommandTransportError("wire values must be JSON values")
    tag = value.get(_TAG)
    if tag == "bytes":
        return base64.b64decode(value["base64"], validate=True)
    if tag == "tuple":
        return tuple(decode_wire(item) for item in value["items"])
    if tag == "mapping":
        return {decode_wire(key): decode_wire(item) for key, item in value["items"]}
    if tag == "path":
        return Path(value["value"])
    if tag == "enum":
        return _load_type(value["type"])(decode_wire(value["value"]))
    if tag == "dataclass":
        data_type = _load_type(value["type"])
        supplied = value.get("fields")
        declared = {field.name: field for field in fields(data_type)}
        if not isinstance(supplied, dict) or set(supplied) != set(declared):
            raise CommandTransportError("dataclass fields do not match the declared type")
        init = {name: decode_wire(item) for name, item in supplied.items() if declared[name].init}
        result = data_type(**init)
        for name, item in supplied.items():
            if not declared[name].init and getattr(result, name) != decode_wire(item):
                raise CommandTransportError("derived dataclass field does not match")
        return result
    raise CommandTransportError("unknown wire value tag")


def _frame(value: Mapping[str, Any]) -> bytes:
    result = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if len(result) > _MAX_BYTES:
        raise CommandTransportError("serialized command exceeds the transport limit")
    return result + b"\n"


def _read(stream: Any) -> Mapping[str, Any]:
    line = stream.readline(_MAX_BYTES + 2)
    if not line or len(line) > _MAX_BYTES + 1 or not line.endswith(b"\n"):
        raise CommandTransportError("invalid or oversized command frame")
    result = json.loads(line)
    if not isinstance(result, dict):
        raise CommandTransportError("command frame must be an object")
    return result


def _context(args: Sequence[Any], kwargs: Mapping[str, Any]) -> Any:
    for value in tuple(args) + tuple(kwargs.values()):
        candidate = getattr(value, "context", None)
        if candidate is not None and hasattr(candidate, "logical_request_key"):
            return candidate
        if hasattr(value, "logical_request_key") and hasattr(value, "actor"):
            return value
    return None


def _target(args: Sequence[Any], kwargs: Mapping[str, Any]) -> Any:
    for value in tuple(args) + tuple(kwargs.values()):
        candidate = getattr(value, "target", None)
        if candidate is not None and hasattr(candidate, "authority"):
            return candidate
        candidate = getattr(value, "ref", value)
        if hasattr(candidate, "authority") and hasattr(candidate, "kind") and hasattr(candidate, "id"):
            return candidate
    return None


def _bindings(operation: str, args: Sequence[Any], kwargs: Mapping[str, Any], schema: Optional[str]) -> Mapping[str, Any]:
    context, target = _context(args, kwargs), _target(args, kwargs)
    actor = kwargs.get("actor") or getattr(context, "actor", None)
    return {
        "authenticated_caller": encode_wire(actor),
        "authority": getattr(target, "authority", getattr(actor, "authority", None)),
        "target": encode_wire(target),
        "operation": operation,
        "payload": encode_wire({"args": tuple(args), "kwargs": dict(kwargs)}),
        "expected_version": kwargs.get("expected_version", getattr(context, "expected_version", None)),
        "expected_revision": kwargs.get("expected_revision", kwargs.get("base_revision", getattr(context, "expected_revision", None))),
        "logical_request_key": kwargs.get("logical_request_key", kwargs.get("request_id", getattr(context, "logical_request_key", None))),
        "correlation_id": kwargs.get("correlation_id", getattr(context, "correlation_id", None)),
        "causation_id": kwargs.get("causation_id", getattr(context, "causation_id", None)),
        "schema_revision": schema,
    }


class SerializedFacadeTransport:
    """JSON metadata naming only a socket and an exact finite endpoint set."""
    __slots__ = ("socket_path", "token", "domain_id", "facade", "endpoints", "schema_revision", "owner_pid", "session_id")

    def __init__(self, socket_path: str, token: str, domain_id: str, facade: str,
                 endpoints: Sequence[str], schema_revision: Optional[str], owner_pid: int, session_id: str) -> None:
        self.socket_path, self.token, self.domain_id, self.facade = socket_path, token, domain_id, facade
        self.endpoints, self.schema_revision = tuple(sorted(endpoints)), schema_revision
        self.owner_pid, self.session_id = owner_pid, session_id

    def to_dict(self) -> Mapping[str, Any]:
        return {"transport_revision": SERIALIZED_COMMAND_REVISION, "socket_path": self.socket_path,
                "token": self.token, "domain_id": self.domain_id, "facade": self.facade,
                "endpoints": list(self.endpoints), "schema_revision": self.schema_revision,
                "owner_pid": self.owner_pid, "session_id": self.session_id}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SerializedFacadeTransport":
        allowed = {"transport_revision", "socket_path", "token", "domain_id", "facade", "endpoints",
                   "schema_revision", "owner_pid", "session_id"}
        if value.get("transport_revision") != SERIALIZED_COMMAND_REVISION or set(value) != allowed:
            raise CommandTransportError("invalid command transport descriptor")
        path, endpoints = value["socket_path"], value["endpoints"]
        if not isinstance(path, str) or not path or path.endswith((".sqlite", ".sqlite3", ".db")):
            raise CommandTransportError("transport must name a socket, not a database")
        if not isinstance(endpoints, list) or not endpoints or any(not isinstance(item, str) for item in endpoints):
            raise CommandTransportError("transport endpoints must be finite names")
        if _FORBIDDEN.intersection(endpoints) or any(item.startswith("_") for item in endpoints):
            raise WriterAuthorityDenied("transport contains a writer operation")
        return cls(path, value["token"], value["domain_id"], value["facade"], endpoints,
                   value["schema_revision"], int(value["owner_pid"]), value["session_id"])


class SerializedCommandClient:
    """Consumer client retaining no owner object, database path, or callable."""
    __slots__ = ("__transport",)

    def __init__(self, transport: SerializedFacadeTransport) -> None:
        object.__setattr__(self, "_SerializedCommandClient__transport", transport)

    @property
    def transport(self) -> SerializedFacadeTransport:
        return object.__getattribute__(self, "_SerializedCommandClient__transport")

    @property
    def endpoints(self) -> Tuple[str, ...]:
        return self.transport.endpoints

    @property
    def domain_id(self) -> str:
        return self.transport.domain_id

    def call(self, operation: str, *args: Any, **kwargs: Any) -> Any:
        transport = self.transport
        if transport.owner_pid == os.getpid():
            service = _OWNER_SERVICES.get(transport.session_id)
            owner_endpoints = service.owner_endpoints if service is not None else ()
            if service is not None and operation in owner_endpoints and operation not in _FORBIDDEN and not operation.startswith("_"):
                endpoint = getattr(service.facade, operation)
                if callable(endpoint):
                    inspect.signature(endpoint).bind(*args, **kwargs)
                    return endpoint(*args, **kwargs)
                if args or kwargs: raise TypeError("property endpoint takes no arguments")
                return endpoint
        if operation in _FORBIDDEN or operation.startswith("_") or operation not in transport.endpoints:
            raise WriterAuthorityDenied("operation is outside the finite consumer boundary: " + operation)
        request = {"transport_revision": SERIALIZED_COMMAND_REVISION, "token": transport.token,
                   "domain_id": transport.domain_id, "facade": transport.facade,
                   "bindings": _bindings(operation, args, kwargs, transport.schema_revision)}
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as channel:
                channel.connect(transport.socket_path)
                stream = channel.makefile("rwb")
                stream.write(_frame(request)); stream.flush()
                response = _read(stream)
        except (FileNotFoundError, ConnectionError, OSError) as exc:
            raise CommandTransportClosed("owner command service is unavailable") from exc
        if response.get("ok") is True:
            return decode_wire(response.get("result"))
        error = response.get("error", {})
        kind, message = str(error.get("type", "")), str(error.get("message", "remote command failed"))
        if kind.endswith(":WriterAuthorityDenied"):
            raise WriterAuthorityDenied(message)
        if kind.startswith("herzchen.") or kind.startswith("builtins:"):
            try:
                module_name, _, qualname = kind.rpartition(":")
                error_type: Any = importlib.import_module(module_name)
                for part in qualname.split("."):
                    error_type = getattr(error_type, part)
                if isinstance(error_type, type) and issubclass(error_type, Exception):
                    raise error_type(message)
            except (ImportError, AttributeError, TypeError):
                pass
        raise RemoteCommandError(kind + ": " + message)

    def __getattr__(self, name: str) -> Any:
        if name in _FORBIDDEN or name.startswith("_"):
            raise WriterAuthorityDenied("writer operation is outside the finite consumer boundary: " + name)
        if name not in self.endpoints:
            service = _OWNER_SERVICES.get(self.transport.session_id) if self.transport.owner_pid == os.getpid() else None
            if service is None or name not in service.owner_endpoints:
                raise AttributeError(name)
        return lambda *args, **kwargs: self.call(name, *args, **kwargs)

    def __dir__(self) -> list[str]:
        return sorted({"call", "domain_id", "endpoints", "transport"} | set(self.endpoints))


class SerializedReaderClient:
    """Finite read-only companion using the same serialized protocol."""
    __slots__ = ("__client", "authority", "domain_descriptor_digest")

    def __init__(self, client: SerializedCommandClient, authority: str, digest: str) -> None:
        object.__setattr__(self, "_SerializedReaderClient__client", client)
        object.__setattr__(self, "authority", authority)
        object.__setattr__(self, "domain_descriptor_digest", digest)

    @property
    def transport(self) -> SerializedFacadeTransport:
        return object.__getattribute__(self, "_SerializedReaderClient__client").transport

    def __getattr__(self, name: str) -> Any:
        if name in _FORBIDDEN or name.startswith("_"):
            raise WriterAuthorityDenied("writer operation is outside the finite reader boundary: " + name)
        return getattr(object.__getattribute__(self, "_SerializedReaderClient__client"), name)

    def __dir__(self) -> list[str]:
        return sorted({"authority", "domain_descriptor_digest", "transport"} | set(_READER_ENDPOINTS))


class _OwnerService:
    def __init__(self, facade: Any, transport: SerializedFacadeTransport) -> None:
        self.facade, self.transport, self.closed, self.audit = facade, transport, threading.Event(), []
        self.owner_endpoints = tuple(getattr(facade, "endpoints", transport.endpoints))
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.bind(transport.socket_path); os.chmod(transport.socket_path, 0o600); self.socket.listen(16)
        self.socket.settimeout(0.2)
        self.thread: Optional[threading.Thread] = None

    def activate(self) -> None:
        if self.thread is None:
            self.thread = threading.Thread(target=self._serve, name="herzchen-owner-" + self.transport.session_id, daemon=True)
            self.thread.start()

    def _serve(self) -> None:
        while not self.closed.is_set():
            try: channel, _ = self.socket.accept()
            except socket.timeout: continue
            except OSError: return
            threading.Thread(target=self._handle, args=(channel,), daemon=True).start()

    def _handle(self, channel: socket.socket) -> None:
        try:
            with channel:
                stream = channel.makefile("rwb"); request = _read(stream)
                stream.write(_frame(self._dispatch(request))); stream.flush()
        except Exception:
            return

    def _dispatch(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            if request.get("transport_revision") != SERIALIZED_COMMAND_REVISION:
                raise CommandTransportError("unsupported command transport revision")
            if not secrets.compare_digest(str(request.get("token", "")), self.transport.token):
                raise WriterAuthorityDenied("command transport authentication failed")
            if request.get("domain_id") != self.transport.domain_id or request.get("facade") != self.transport.facade:
                raise WriterAuthorityDenied("command target does not match the issued transport")
            bindings = request.get("bindings")
            if not isinstance(bindings, dict): raise CommandTransportError("command bindings must be an object")
            operation = bindings.get("operation")
            if not isinstance(operation, str) or operation not in self.transport.endpoints or operation in _FORBIDDEN or operation.startswith("_"):
                raise WriterAuthorityDenied("operation is outside the finite consumer boundary")
            payload = decode_wire(bindings.get("payload"))
            if not isinstance(payload, dict) or set(payload) != {"args", "kwargs"}:
                raise CommandTransportError("command payload must bind args and kwargs")
            args, kwargs = payload["args"], payload["kwargs"]
            if not isinstance(args, tuple) or not isinstance(kwargs, dict):
                raise CommandTransportError("command arguments have invalid wire shape")
            expected = _bindings(operation, args, kwargs, self.transport.schema_revision)
            if json.dumps(bindings, sort_keys=True, separators=(",", ":")) != json.dumps(expected, sort_keys=True, separators=(",", ":")):
                raise WriterAuthorityDenied("security bindings do not match the typed payload")
            endpoint = getattr(self.facade, operation)
            if callable(endpoint):
                inspect.signature(endpoint).bind(*args, **kwargs)
                result = endpoint(*args, **kwargs)
            else:
                if args or kwargs: raise TypeError("property endpoint takes no arguments")
                result = endpoint
            response = {"ok": True, "result": encode_wire(result)}
            self.audit.append({"request": {key: value for key, value in request.items() if key != "token"}, "response": response})
            return response
        except Exception as exc:
            response = {"ok": False, "error": {"type": _qname(type(exc)), "message": str(exc)}}
            self.audit.append({"request": {key: value for key, value in request.items() if key != "token"}, "response": response})
            return response

    def close(self) -> None:
        self.closed.set(); self.socket.close()
        if self.thread is not None and self.thread is not threading.current_thread(): self.thread.join(timeout=1.0)
        try: os.unlink(self.transport.socket_path); os.rmdir(os.path.dirname(self.transport.socket_path))
        except OSError: pass


_OWNER_SERVICES: Dict[str, _OwnerService] = {}


def _start_service(value: Any, domain_id: str, facade_name: str, endpoints: Sequence[str],
                   schema_revision: Optional[str], socket_directory: Optional[str] = None) -> SerializedFacadeTransport:
    consumer_endpoints = tuple(name for name in endpoints if name not in _OWNER_ONLY_ENDPOINTS)
    if not consumer_endpoints or _FORBIDDEN.intersection(consumer_endpoints) or any(name.startswith("_") for name in consumer_endpoints):
        raise WriterAuthorityDenied("service must expose a non-empty finite endpoint set")
    directory = tempfile.mkdtemp(prefix="herzchen-command-", dir=socket_directory)
    session_id = secrets.token_hex(12)
    transport = SerializedFacadeTransport(os.path.join(directory, "owner.sock"), secrets.token_urlsafe(32),
        domain_id, facade_name, consumer_endpoints, schema_revision, os.getpid(), session_id)
    _OWNER_SERVICES[session_id] = _OwnerService(value, transport)
    return transport


def _activate_transport(transport: SerializedFacadeTransport) -> SerializedFacadeTransport:
    service = _OWNER_SERVICES.get(transport.session_id)
    if service is None: raise CommandTransportClosed("owner command service is unavailable")
    service.activate()
    return transport


def _reader_client(reader: Any, *, authority: Optional[str] = None) -> SerializedReaderClient:
    transport = _start_service(reader, "herzchen.kernel.reader", "herzchen.kernel.store.ConsumerStore",
                               _READER_ENDPOINTS, SERIALIZED_COMMAND_REVISION)
    reader_authority = authority if authority is not None else reader.authority
    return SerializedReaderClient(SerializedCommandClient(transport), reader_authority, reader.domain_descriptor_digest)


def _schema_revision(engine_type: type[Any]) -> Optional[str]:
    module = importlib.import_module(engine_type.__module__)
    for name in ("SCHEMA_REVISION", "AUTHORING_SCHEMA_REVISION", "PACK_SCHEMA_REVISION", "ASSESSMENT_SCHEMA_REVISION"):
        value = getattr(module, name, None)
        if isinstance(value, str): return value
    candidates = [value for name, value in vars(module).items() if name.endswith("SCHEMA_REVISION") and isinstance(value, str)]
    return candidates[0] if len(candidates) == 1 else None


def serve_consumer_facade(facade: Any, *, schema_revision: Optional[str] = None,
                          socket_directory: Optional[str] = None) -> SerializedFacadeTransport:
    """Issue a JSON-only capability while retaining the live facade in owner custody."""
    port = getattr(facade, "command_port", None)
    if isinstance(port, SerializedCommandClient):
        return _activate_transport(port.transport)
    endpoints, domain_id = tuple(getattr(port, "endpoints", ())), getattr(port, "domain_id", None)
    if not endpoints or not isinstance(domain_id, str):
        raise TypeError("facade must have a finite Store-issued command port")
    if _FORBIDDEN.intersection(endpoints) or any(name.startswith("_") for name in endpoints):
        raise WriterAuthorityDenied("facade exposes a forbidden writer endpoint")
    return _activate_transport(_start_service(port, domain_id, type(facade).__module__ + "." + type(facade).__qualname__,
                          endpoints, schema_revision, socket_directory))


def connect_consumer_facade(value: Mapping[str, Any] | SerializedFacadeTransport) -> SerializedCommandClient:
    transport = value if isinstance(value, SerializedFacadeTransport) else SerializedFacadeTransport.from_dict(value)
    return SerializedCommandClient(transport)


def close_consumer_facade(transport: SerializedFacadeTransport) -> None:
    service = _OWNER_SERVICES.pop(transport.session_id, None)
    if service is not None: service.close()


def consumer_facade_audit(transport: SerializedFacadeTransport) -> Tuple[Mapping[str, Any], ...]:
    """Return owner-side request/response evidence with bearer tokens removed."""
    service = _OWNER_SERVICES.get(transport.session_id)
    if service is None: raise CommandTransportClosed("owner command service is unavailable")
    return tuple(service.audit)


def owner_local_command_port(value: Any) -> Any:
    """Resolve a proxy only for composition code already in its owner process.

    This is deliberately unusable in a transported consumer: an exec-created
    process has an empty owner registry and a different PID.  It lets trusted
    owner adapters keep callback and transaction work on the owner side rather
    than serializing callables or Transaction objects.
    """
    client = value.command_port if hasattr(value, "command_port") else value
    if not isinstance(client, SerializedCommandClient): return value
    transport = client.transport
    if transport.owner_pid != os.getpid():
        raise WriterAuthorityDenied("owner-local composition is unavailable in a consumer process")
    service = _OWNER_SERVICES.get(transport.session_id)
    if service is None:
        raise CommandTransportClosed("owner command service is unavailable")
    return service.facade


def owner_local_engine(value: Any) -> Any:
    """Return an engine transiently to trusted owner composition only."""
    port = owner_local_command_port(value)
    if port is value: return value
    return object.__getattribute__(port, "_DomainCommandPort__engine")


def command_facade(engine_type: type[Any], domain_id: str) -> type[Any]:
    """Build a trusted-composition facade backed by one finite command port."""
    if not isinstance(engine_type, type): raise TypeError("engine_type must be a class")
    descriptors: Dict[str, Any] = {}
    for base in reversed(engine_type.__mro__[:-1]):
        for name, value in base.__dict__.items():
            if not name.startswith("_") and (inspect.isfunction(value) or isinstance(value, (staticmethod, classmethod, property))):
                descriptors[name] = value
    endpoints, public_name = tuple(descriptors), engine_type.__name__.removeprefix("_").removesuffix("Engine")

    class CommandFacade:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            from herzchen.kernel.store import ConsumerStore, DomainCommandPort, DomainHandler, DomainOwnerCapability, OperationOwnerCapability, RuntimeDomainOwner, RuntimeOperationOwner, RuntimeOperationReader, Store, StoreAdmissionError, _COMMAND_PORT_CONSTRUCTION_TOKEN
            constructor_args, constructor_kwargs = args, kwargs
            issuer = (args[0] if args else kwargs.get("store", kwargs.get("writer")))
            if isinstance(issuer, OperationOwnerCapability) and domain_id != "herzchen.kernel.operations":
                raise StoreAdmissionError("OperationOwnerCapability is scoped to the kernel operations domain")
            if isinstance(issuer, RuntimeDomainOwner):
                scoped = DomainOwnerCapability.issue_runtime(issuer, domain_id)
                if args:
                    constructor_args = (scoped,) + args[1:]
                else:
                    constructor_kwargs = dict(kwargs)
                    if "store" in constructor_kwargs:
                        constructor_kwargs["store"] = scoped
                    elif "writer" in constructor_kwargs:
                        constructor_kwargs["writer"] = scoped
                    else:
                        raise StoreAdmissionError("RuntimeDomainOwner must be supplied as the command writer")
                issuer = scoped
            depth = getattr(_COMPOSITION, "depth", 0)
            _COMPOSITION.depth = depth + 1
            try:
                engine = engine_type(*constructor_args, **constructor_kwargs)
            finally:
                _COMPOSITION.depth = depth
            issuer, reader = (constructor_args[0] if constructor_args else constructor_kwargs.get("store", constructor_kwargs.get("writer"))), getattr(engine, "reader", None)
            if reader is not None and not isinstance(reader, (ConsumerStore, RuntimeOperationReader)):
                raise StoreAdmissionError("public command readers must be finite ConsumerStore or RuntimeOperationReader instances")
            if issuer is None:
                port = DomainCommandPort(engine, domain_id, endpoints, reader, _construction_token=_COMMAND_PORT_CONSTRUCTION_TOKEN)
            elif isinstance(issuer, DomainOwnerCapability):
                port = issuer.issue_command_port(engine, domain_id, endpoints, reader=reader)
            elif isinstance(issuer, RuntimeOperationOwner):
                issuer = OperationOwnerCapability.issue_runtime(issuer)
                port = issuer.issue_command_port(engine, domain_id, endpoints, reader=reader)
            elif isinstance(issuer, OperationOwnerCapability):
                if domain_id != "herzchen.kernel.operations":
                    raise StoreAdmissionError("OperationOwnerCapability is scoped to the kernel operations domain")
                port = issuer.issue_command_port(engine, domain_id, endpoints, reader=reader)
            elif isinstance(issuer, (Store, DomainHandler)):
                port = issuer.issue_command_port(engine, domain_id, endpoints, reader=reader)
            else: raise StoreAdmissionError("public commands require a Store-issued owner capability")
            if depth:
                object.__setattr__(self, "_CommandFacade__owner_port", port)
                if reader is not None: object.__setattr__(self, "reader", reader)
                return
            transport = _start_service(port, domain_id, engine_type.__module__ + "." + public_name,
                                       endpoints, _schema_revision(engine_type))
            object.__setattr__(self, "_CommandFacade__client", SerializedCommandClient(transport))
            safe: Dict[str, Any] = {}
            for name, value in vars(engine).items():
                if name.startswith("_") or callable(value): continue
                if isinstance(value, ConsumerStore):
                    safe[name] = _reader_client(value)
                elif isinstance(value, RuntimeOperationReader):
                    safe[name] = _reader_client(value, authority=getattr(issuer, "authority", None))
                elif hasattr(value, "command_port"):
                    nested_port = value.command_port
                    nested_transport = _start_service(nested_port, nested_port.domain_id,
                        type(value).__module__ + "." + type(value).__qualname__, nested_port.endpoints,
                        _schema_revision(type(value)))
                    safe[name] = SerializedCommandClient(nested_transport)
                else:
                    try: safe[name] = decode_wire(encode_wire(value))
                    except CommandTransportError: continue
            for base in engine_type.__mro__[:-1]:
                for name, value in vars(base).items():
                    if name.startswith("_") or name in safe or name in descriptors or callable(value): continue
                    try: safe[name] = decode_wire(encode_wire(value))
                    except CommandTransportError: continue
            object.__setattr__(self, "_CommandFacade__attributes", safe)
            if "reader" in safe: object.__setattr__(self, "reader", safe["reader"])

        @property
        def command_port(self):
            try: return object.__getattribute__(self, "_CommandFacade__owner_port")
            except AttributeError: return object.__getattribute__(self, "_CommandFacade__client")

        def consumer_transport(self, *, schema_revision: Optional[str] = None) -> SerializedFacadeTransport:
            port = self.command_port
            if isinstance(port, SerializedCommandClient): return _activate_transport(port.transport)
            return serve_consumer_facade(self, schema_revision=schema_revision or _schema_revision(engine_type))

        def __getattr__(self, name: str) -> Any:
            from herzchen.kernel.store import DomainCommandPort, DomainHandler, DomainOwnerCapability, OperationOwnerCapability, RuntimeOperationReader, Store, Transaction
            if name.startswith("_") or name in DomainCommandPort._FORBIDDEN: raise AttributeError(name)
            try: port = object.__getattribute__(self, "_CommandFacade__owner_port")
            except AttributeError:
                attributes = object.__getattribute__(self, "_CommandFacade__attributes")
                if name in attributes: return attributes[name]
                raise AttributeError(name)
            engine = object.__getattribute__(port, "_DomainCommandPort__engine"); value = getattr(engine, name)
            if isinstance(value, (Store, DomainHandler, DomainOwnerCapability, OperationOwnerCapability, Transaction)): raise AttributeError(name)
            return value

        def __setattr__(self, name: str, value: Any) -> None:
            from herzchen.kernel.store import DomainCommandPort
            if name.startswith("_") or name in DomainCommandPort._FORBIDDEN: raise AttributeError(name)
            try: port = object.__getattribute__(self, "_CommandFacade__owner_port")
            except AttributeError: raise AttributeError("serialized consumer facades are immutable")
            engine = object.__getattribute__(port, "_DomainCommandPort__engine")
            facade_descriptor = getattr(type(self), name, None)
            if inspect.ismethod(value) and value.__self__ is self and value.__func__ is facade_descriptor:
                engine.__dict__.pop(name, None); return
            setattr(engine, name, value)

    def forward(name: str) -> Any:
        original = descriptors[name]
        if isinstance(original, (staticmethod, classmethod)): return original
        if isinstance(original, property):
            return property(lambda self, n=name: (getattr(self.command_port, n) if not isinstance(self.command_port, SerializedCommandClient) else self.command_port.call(n)), doc=original.__doc__)
        def endpoint(self: Any, *args: Any, **kwargs: Any) -> Any:
            return getattr(self.command_port, name)(*args, **kwargs)
        endpoint.__name__, endpoint.__qualname__, endpoint.__doc__ = name, public_name + "." + name, getattr(original, "__doc__", None)
        return endpoint

    for endpoint_name in endpoints: setattr(CommandFacade, endpoint_name, forward(endpoint_name))
    CommandFacade.__name__, CommandFacade.__qualname__, CommandFacade.__module__, CommandFacade.__doc__ = public_name, public_name, engine_type.__module__, engine_type.__doc__
    return CommandFacade


__all__ = ["SERIALIZED_COMMAND_REVISION", "SerializedFacadeTransport", "SerializedCommandClient", "SerializedReaderClient",
           "CommandTransportError", "CommandTransportClosed", "RemoteCommandError", "WriterAuthorityDenied",
           "serve_consumer_facade", "connect_consumer_facade", "close_consumer_facade", "consumer_facade_audit",
           "owner_local_command_port", "owner_local_engine", "command_facade",
           "encode_wire", "decode_wire"]
