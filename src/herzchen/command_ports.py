"""Lightweight public command facade construction.

This module intentionally imports no Store or SQLite implementation so
resource-only modules remain importable without opening the persistence layer.
Actual command construction resolves the concrete Store types lazily and asks
that trusted owner to issue the authenticated narrow port.
"""

from __future__ import annotations

import inspect
from typing import Any, Dict


def command_facade(engine_type: type[Any], domain_id: str) -> type[Any]:
    """Build a public command class backed by one finite domain command port."""
    if not isinstance(engine_type, type):
        raise TypeError("engine_type must be a class")
    endpoint_descriptors: Dict[str, Any] = {}
    for base in reversed(engine_type.__mro__[:-1]):
        for name, value in base.__dict__.items():
            if not name.startswith("_") and (
                inspect.isfunction(value)
                or isinstance(value, (staticmethod, classmethod, property))
            ):
                endpoint_descriptors[name] = value
    endpoints = tuple(endpoint_descriptors)
    public_name = engine_type.__name__.removeprefix("_").removesuffix("Engine")

    class CommandFacade:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            from herzchen.kernel.store import (
                ConsumerStore, DomainCommandPort, DomainHandler, Store,
                StoreAdmissionError, _COMMAND_PORT_CONSTRUCTION_TOKEN,
            )

            engine = engine_type(*args, **kwargs)
            issuer = args[0] if args else kwargs.get("store", kwargs.get("writer"))
            reader = getattr(engine, "reader", None)
            if reader is not None and not isinstance(reader, ConsumerStore):
                raise StoreAdmissionError("public command readers must be ConsumerStore instances")
            if issuer is None:
                port = DomainCommandPort(
                    engine, domain_id, endpoints, reader,
                    _construction_token=_COMMAND_PORT_CONSTRUCTION_TOKEN,
                )
            elif isinstance(issuer, (Store, DomainHandler)):
                port = issuer.issue_command_port(engine, domain_id, endpoints, reader=reader)
            else:
                raise StoreAdmissionError("public commands require a Store-issued owner capability")
            object.__setattr__(self, "_CommandFacade__port", port)
            if reader is not None:
                object.__setattr__(self, "reader", reader)

        @property
        def command_port(self):
            return object.__getattribute__(self, "_CommandFacade__port")

        def __getattr__(self, name: str) -> Any:
            from herzchen.kernel.store import DomainCommandPort, DomainHandler, Store, Transaction

            if name.startswith("_") or name in DomainCommandPort._FORBIDDEN:
                raise AttributeError(name)
            port = object.__getattribute__(self, "_CommandFacade__port")
            engine = object.__getattribute__(port, "_DomainCommandPort__engine")
            value = getattr(engine, name)
            if isinstance(value, (Store, DomainHandler, Transaction)):
                raise AttributeError(name)
            return value

        def __setattr__(self, name: str, value: Any) -> None:
            from herzchen.kernel.store import DomainCommandPort

            if name.startswith("_") or name in DomainCommandPort._FORBIDDEN:
                raise AttributeError(name)
            port = object.__getattribute__(self, "_CommandFacade__port")
            engine = object.__getattribute__(port, "_DomainCommandPort__engine")
            facade_descriptor = getattr(type(self), name, None)
            if inspect.ismethod(value) and value.__self__ is self and value.__func__ is facade_descriptor:
                engine.__dict__.pop(name, None)
                return
            setattr(engine, name, value)

    def forward(name: str) -> Any:
        original = endpoint_descriptors[name]
        if isinstance(original, (staticmethod, classmethod)):
            return original
        if isinstance(original, property):
            return property(
                lambda self, n=name: getattr(self.command_port, n),
                doc=original.__doc__,
            )

        def endpoint(self: Any, *args: Any, **kwargs: Any) -> Any:
            port = object.__getattribute__(self, "_CommandFacade__port")
            return getattr(port, name)(*args, **kwargs)

        endpoint.__name__ = name
        endpoint.__qualname__ = "{}.{}".format(public_name, name)
        endpoint.__doc__ = getattr(original, "__doc__", None)
        return endpoint

    for endpoint_name in endpoints:
        setattr(CommandFacade, endpoint_name, forward(endpoint_name))
    CommandFacade.__name__ = public_name
    CommandFacade.__qualname__ = public_name
    CommandFacade.__module__ = engine_type.__module__
    CommandFacade.__doc__ = engine_type.__doc__
    return CommandFacade
