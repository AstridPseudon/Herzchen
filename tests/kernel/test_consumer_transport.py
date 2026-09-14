"""GF01 product proofs for the serialized owner/consumer boundary."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from herzchen.command_ports import (
    SERIALIZED_COMMAND_REVISION,
    close_consumer_facade,
    consumer_facade_audit,
)
from herzchen.contracts import AuthenticatedActor, ResourceRef
from herzchen.domains.work.module import WorkGraph, register_work
from herzchen.kernel.store import Store


SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src"
CONSUMER_IMPORT_ROOT = os.environ.get("GF01_CONSUMER_IMPORT_ROOT", str(SOURCE_ROOT))
ACTOR = AuthenticatedActor("consumer-auth", "worker-1", "credential-1")
FORBIDDEN = (
    "connection", "transaction", "mutate", "put_identity", "revise_identity",
    "put_reference", "append_event", "register_domain", "domain_handler",
)


def _fresh_consumer(transport, action: str) -> subprocess.CompletedProcess[str]:
    program = r'''
import json, os, sys
if sys.argv[1]:
    sys.path.insert(0, sys.argv[1])
from herzchen.command_ports import connect_consumer_facade, WriterAuthorityDenied
from herzchen.contracts import AuthenticatedActor, ResourceRef
spec = json.loads(sys.stdin.read())
client = connect_consumer_facade(spec)
result = {"pid": os.getpid(), "ppid": os.getppid(), "origin": __import__("herzchen.command_ports", fromlist=["x"]).__file__,
          "python": sys.version, "pythonpath": os.environ.get("PYTHONPATH"), "pythonhome": os.environ.get("PYTHONHOME"),
          "owner_registry_empty": not bool(__import__("herzchen.command_ports", fromlist=["x"])._OWNER_SERVICES),
          "transport_keys": sorted(spec), "descriptor_has_db_path": any(
              key in {"database", "db", "db_path", "sqlite", "connection"} or
              (isinstance(value, str) and value.endswith((".sqlite", ".sqlite3", ".db")))
              for key, value in spec.items())}
if sys.argv[2] == "forbidden":
    denied = []
    for name in ("connection", "transaction", "mutate", "put_identity", "revise_identity", "put_reference", "append_event", "register_domain", "domain_handler"):
        try:
            client.call(name)
        except WriterAuthorityDenied as exc:
            denied.append({"operation": name, "error": type(exc).__name__})
    result["denied"] = denied
    import socket
    forged = {"transport_revision": spec["transport_revision"], "token": spec["token"],
              "domain_id": spec["domain_id"], "facade": spec["facade"],
              "bindings": {"operation": "mutate"}}
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as channel:
        channel.connect(spec["socket_path"])
        stream = channel.makefile("rwb")
        stream.write((json.dumps(forged, sort_keys=True) + "\n").encode()); stream.flush()
        result["remote_denied"] = json.loads(stream.readline())
else:
    actor = AuthenticatedActor("consumer-auth", "worker-1", "credential-1")
    created = client.create_project(title="Serialized representative", outcome="finite command committed",
                                    logical_request_key="gf01-serialized-create", actor=actor)
    fresh = client.get(created.ref)
    def view(record):
        return {"id": record.id, "ref": record.ref.to_dict(), "title": record.title,
                "version": record.version, "lifecycle": record.lifecycle.value,
                "outcome": record.payload.get("outcome")}
    result.update({"created": view(created), "query": view(fresh), "same": created == fresh})
print(json.dumps(result, sort_keys=True))
'''
    env = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME"}}
    return subprocess.run(
        [sys.executable, "-I", "-c", program, CONSUMER_IMPORT_ROOT, action],
        input=json.dumps(transport.to_dict()), text=True, capture_output=True,
        check=False, close_fds=True, env=env,
    )


def test_representative_admitted_command_and_query_cross_fresh_serialized_process(tmp_path):
    owner = Store.create(tmp_path / "representative.sqlite", authority="gf01-owner")
    transport = None
    try:
        register_work(owner)
        graph = WorkGraph(owner, actor=ACTOR)
        transport = graph.consumer_transport(schema_revision="work.v1")
        descriptor = transport.to_dict()
        assert descriptor["transport_revision"] == SERIALIZED_COMMAND_REVISION
        assert set(descriptor) == {
            "transport_revision", "socket_path", "token", "domain_id", "facade",
            "endpoints", "schema_revision", "owner_pid", "session_id",
        }
        assert descriptor["owner_pid"] == os.getpid()
        assert not any(str(value).endswith((".sqlite", ".sqlite3", ".db")) for value in descriptor.values())

        before = dict(owner.consumer().snapshot_counts())
        run = _fresh_consumer(transport, "positive")
        assert run.returncode == 0, run.stderr
        proof = json.loads(run.stdout)
        assert proof["pid"] != os.getpid()
        assert proof["ppid"] == os.getpid()
        assert proof["pythonpath"] is None and proof["pythonhome"] is None
        assert proof["owner_registry_empty"] is True
        assert proof["descriptor_has_db_path"] is False
        assert proof["same"] is True
        assert proof["created"] == proof["query"]

        ref = ResourceRef("gf01-owner", "work.project", proof["created"]["id"])
        persisted = owner.get_identity(ref)
        receipt = owner.get_receipt("gf01-serialized-create")
        events = owner.list_events(stream="work:" + ref.id)
        after = dict(owner.consumer().snapshot_counts())
        assert persisted is not None and persisted.payload["title"] == "Serialized representative"
        assert receipt is not None and receipt.status.value == "committed"
        assert len(receipt.event_ids) == 1 and tuple(event.event_id for event in events) == receipt.event_ids
        assert after["identities"] == before["identities"] + 1
        assert after["command_receipts"] == before["command_receipts"] + 1
        assert after["events"] == before["events"] + 1

        audit = consumer_facade_audit(transport)
        assert [entry["request"]["bindings"]["operation"] for entry in audit] == ["create_project", "get"]
        create_bindings = audit[0]["request"]["bindings"]
        assert create_bindings["authenticated_caller"] is not None
        assert create_bindings["logical_request_key"] == "gf01-serialized-create"
        assert create_bindings["schema_revision"] == "work.v1"
        assert create_bindings["correlation_id"] is None and create_bindings["causation_id"] is None
        assert "token" not in audit[0]["request"]
    finally:
        if transport is not None:
            close_consumer_facade(transport)
        owner.close()


def test_forbidden_writer_operations_fail_in_fresh_consumer_with_zero_delta(tmp_path):
    owner = Store.create(tmp_path / "negative.sqlite", authority="gf01-negative")
    transport = None
    try:
        register_work(owner)
        transport = WorkGraph(owner, actor=ACTOR).consumer_transport(schema_revision="work.v1")
        before = dict(owner.consumer().snapshot_counts())
        before_events = owner.list_events()
        before_receipt = owner.get_receipt("gf01-forbidden")
        run = _fresh_consumer(transport, "forbidden")
        assert run.returncode == 0, run.stderr
        proof = json.loads(run.stdout)
        assert proof["pid"] != os.getpid() and proof["owner_registry_empty"] is True
        assert [entry["operation"] for entry in proof["denied"]] == list(FORBIDDEN)
        assert {entry["error"] for entry in proof["denied"]} == {"WriterAuthorityDenied"}
        assert proof["remote_denied"]["ok"] is False
        assert proof["remote_denied"]["error"]["type"].endswith(":WriterAuthorityDenied")
        assert owner.consumer().snapshot_counts() == before
        assert owner.list_events() == before_events
        assert owner.get_receipt("gf01-forbidden") is before_receipt is None
        audit = consumer_facade_audit(transport)
        assert len(audit) == 1
        assert audit[0]["request"]["bindings"] == {"operation": "mutate"}
        assert "token" not in audit[0]["request"]
    finally:
        if transport is not None:
            close_consumer_facade(transport)
        owner.close()
