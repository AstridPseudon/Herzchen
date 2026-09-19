"""Thin adapter over the FND neutral HostPort.

No process, queue, persistence, or session ledger is owned here. The injected
port is the only transport authority; this layer adds truthful envelope data.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Mapping, Optional
import hashlib
import json
import os
import subprocess
from pathlib import Path

from herzchen.contracts.model import HostOperation, HostOutcome, HostPort, HostReceipt, HostRequest, ContractError
from .receipt import AdapterReceiptEnvelope

RUNNER_ID = "codex-cli"


class CodexCliBinding(HostPort):
    """Opt-in receiving binding for the observed local Codex executable.

    Construction is inert. ``preflight`` checks only the executable metadata;
    ``execute`` is the explicit, authority-gated launcher operation. It never
    invents a session: a physical session is taken only from native JSONL.
    """

    def __init__(self, worktree: str, *, launcher: str = "/Users/hannahomalley/.local/bin/codex",
                 model: str = "gpt-5.6-luna", reasoning: str = "high",
                 receipt_path: Optional[str] = None, prompt: str = "",
                 evidence_path: Optional[str] = None,
                 native_receipt_path: Optional[str] = None) -> None:
        super().__init__({HostOperation.INVOKE, HostOperation.RESUME})
        self.worktree, self.launcher, self.model, self.reasoning = worktree, launcher, model, reasoning
        self.receipt_path = native_receipt_path or receipt_path
        self.prompt = prompt
        self.evidence_path = evidence_path

    def preflight(self) -> dict[str, Any]:
        try:
            result = subprocess.run([self.launcher, "--version"], capture_output=True, text=True,
                                    check=False, timeout=10)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"available": False, "launcher": self.launcher, "error": str(exc)}
        return {"available": result.returncode == 0, "launcher": self.launcher,
                "command": [self.launcher, "--version"], "exit_status": result.returncode,
                "stdout": result.stdout, "stderr": result.stderr}

    def execute(self, request: HostRequest) -> tuple[HostReceipt, Mapping[str, Any]]:
        if request.operation not in {HostOperation.INVOKE, HostOperation.RESUME}:
            return (HostReceipt(request.operation, HostOutcome.UNSUPPORTED, request.identity,
                                request.identity.logical_agent_id, request.requested_profile,
                                unsupported_reason=f"codex CLI binding does not support {request.operation.value}"), {})
        if request.operation == HostOperation.RESUME and not request.identity.physical_session_id:
            return (HostReceipt(request.operation, HostOutcome.UNKNOWN, request.identity,
                                request.identity.logical_agent_id, request.requested_profile,
                                observed_runner=RUNNER_ID,
                                unsupported_reason="resume requires supplied physical session identity"),
                    {"reconciliation": "resume cannot run without an observed physical session",
                     "delivery_state": "unknown"})
        if request.operation == HostOperation.INVOKE:
            command = [self.launcher, "exec", "-C", self.worktree, "-m", self.model,
                       "-c", f"model_reasoning_effort={self.reasoning}", "-s", "read-only", "--json"]
        else:
            command = [self.launcher, "exec", "resume", request.identity.physical_session_id,
                       "-m", self.model, "-c", f"model_reasoning_effort={self.reasoning}", "--json"]
        if self.receipt_path:
            command.extend(["-o", self.receipt_path])
        command.append("-")
        started = _now()
        try:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True, cwd=self.worktree,
                                       env=os.environ.copy())
            stdout, stderr = process.communicate(self.prompt, timeout=120)
            exit_status = process.returncode
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            exit_status = None
        except OSError as exc:
            return (HostReceipt(request.operation, HostOutcome.FAILED, request.identity,
                                request.identity.logical_agent_id, request.requested_profile,
                                observed_runner=RUNNER_ID, unsupported_reason="codex_launcher_os_error"),
                    {"command": command, "started_at": started, "stderr": str(exc),
                     "delivery_state": "unknown"})
        if self.evidence_path:
            Path(self.evidence_path).write_text(stdout, encoding="utf-8")
        observed_session = None
        observed_model = None
        observed_reasoning = None
        def first_value(value: Any, names: set[str]) -> Optional[str]:
            if isinstance(value, Mapping):
                for name in names:
                    candidate = value.get(name)
                    if isinstance(candidate, str) and candidate:
                        return candidate
                for child in value.values():
                    found = first_value(child, names)
                    if found:
                        return found
            elif isinstance(value, list):
                for child in value:
                    found = first_value(child, names)
                    if found:
                        return found
            return None

        for line in stdout.splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            observed_session = observed_session or first_value(item, {"thread_id", "session_id"})
            observed_model = observed_model or first_value(item, {"model", "model_name"})
            observed_reasoning = observed_reasoning or first_value(item, {"reasoning_effort", "reasoning"})
        physical_session = observed_session
        if request.operation == HostOperation.RESUME and not physical_session and exit_status == 0:
            physical_session = request.identity.physical_session_id
        identity = type(request.identity)(request.identity.logical_agent_id, physical_session)
        if exit_status == 0 and physical_session:
            outcome = HostOutcome.SUCCEEDED
        elif exit_status == 0 or exit_status is None:
            outcome = HostOutcome.UNKNOWN
        else:
            outcome = HostOutcome.FAILED
        receipt = HostReceipt(request.operation, outcome, identity, request.identity.logical_agent_id,
                              request.requested_profile, observed_runner=RUNNER_ID,
                              observed_profile=None, process_id=str(process.pid),
                              unsupported_reason=None if outcome == HostOutcome.SUCCEEDED else (
                                  "codex_execution_timeout" if exit_status is None else "codex_execution_failed"))
        return receipt, {"command": command, "stdout": stdout, "stderr": stderr,
                         "exit_status": exit_status, "observed_model": observed_model,
                         "observed_reasoning": observed_reasoning,
                         "stdout_ref": self.evidence_path,
                         "native_receipt_ref": self.receipt_path,
                         "delivery_state": "done" if outcome == HostOutcome.SUCCEEDED else "unknown",
                         "reconciliation": None if physical_session else "session unresolved",
                         "started_at": started, "ended_at": _now()}

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

class HerzchenHostAdapter:
    def __init__(self, port: HostPort, *, owner: str, source: str, worktree: str,
                 launcher: str, requested_model: str = "gpt-5.6-luna",
                 requested_reasoning: str = "high") -> None:
        self.port = port
        # Otto uses this finite capability marker to require the owner-bound
        # attempt gate before invoking this host transport.
        self.owner_bound = True
        self.owner, self.source, self.worktree, self.launcher = owner, source, worktree, launcher
        self.requested_model, self.requested_reasoning = requested_model, requested_reasoning

    def _packet_digest(self, request: HostRequest) -> str:
        return hashlib.sha256(request.to_json().encode()).hexdigest()

    def _envelope(self, request: HostRequest, receipt: HostReceipt, started: str,
                  *, ended: Optional[str] = None, status: Optional[str] = None,
                  delivery_state: str = "unknown", error: Optional[str] = None,
                  metadata: Optional[Mapping[str, Any]] = None) -> AdapterReceiptEnvelope:
        metadata = dict(metadata or {})
        physical = receipt.identity.physical_session_id
        envelope_started = metadata.get("started_at", started)
        envelope_ended = metadata.get("ended_at", ended)
        return AdapterReceiptEnvelope(self.owner, request.identity.logical_agent_id, physical,
            self.source, self.worktree, self._packet_digest(request), self.requested_model,
            self.requested_reasoning, request.requested_profile or "default",
            metadata.get("observed_model"), metadata.get("observed_reasoning"),
            metadata.get("observed_profile", receipt.observed_profile), self.launcher,
            receipt.observed_runner, receipt.process_id, envelope_started, envelope_ended,
            metadata.get("exit_status"), status or receipt.outcome.value,
            metadata.get("stdout_ref"), metadata.get("native_receipt_ref"), delivery_state,
            metadata.get("cursor"), metadata.get("timeout"), metadata.get("cancel"),
            metadata.get("reconciliation"), error or receipt.unsupported_reason,
            receipt.result_ref.to_json() if receipt.result_ref else None, receipt.to_dict(),
            command=tuple(metadata["command"]) if metadata.get("command") else None)

    def _reject_duplicate(self, request: HostRequest) -> None:
        """Ask the owning host binding about unresolved logical work.

        The adapter deliberately does not maintain a second session ledger. A
        binding may expose ``resolve_logical_session``; its answer is authoritative.
        """
        if request.operation not in {HostOperation.INVOKE, HostOperation.RESUME}:
            return
        resolver = getattr(self.port, "resolve_logical_session", None)
        if resolver is None or request.identity.physical_session_id is not None:
            return
        physical = resolver(request.identity.logical_agent_id)
        if physical:
            raise ContractError("unresolved logical delivery cannot create a second session")

    def execute(self, request: HostRequest) -> tuple[HostReceipt, AdapterReceiptEnvelope]:
        started = _now()
        self._reject_duplicate(request)
        metadata: Mapping[str, Any] = {}
        try:
            if not self.port.supports(request.operation):
                receipt = HostReceipt(request.operation, HostOutcome.UNSUPPORTED, request.identity,
                    request.identity.logical_agent_id, request.requested_profile,
                    unsupported_reason=f"adapter does not support {request.operation.value}")
            elif hasattr(self.port, "execute"):
                observed = self.port.execute(request)  # FND-owned transport boundary
                if isinstance(observed, tuple):
                    receipt, metadata = observed
                else:
                    receipt = observed
            else:
                receipt = HostReceipt(request.operation, HostOutcome.UNSUPPORTED, request.identity,
                    request.identity.logical_agent_id, request.requested_profile,
                    unsupported_reason="configured host has no execution binding")
        except Exception as exc:
            receipt = HostReceipt(request.operation, HostOutcome.FAILED, request.identity,
                request.identity.logical_agent_id, request.requested_profile, unsupported_reason=str(exc))
        state = metadata.get("delivery_state")
        if not state:
            state = "unknown" if receipt.outcome in {HostOutcome.UNKNOWN, HostOutcome.UNSUPPORTED} else ("done" if receipt.outcome == HostOutcome.SUCCEEDED else "unknown")
        return receipt, self._envelope(request, receipt, started, ended=_now(), delivery_state=state, metadata=metadata)

    def invoke(self, request: HostRequest): return self.execute(replace(request, operation=HostOperation.INVOKE))
    def resume(self, request: HostRequest): return self.execute(replace(request, operation=HostOperation.RESUME))
    def send(self, request: HostRequest): return self.execute(replace(request, operation=HostOperation.SEND))
    def inspect(self, request: HostRequest): return self.execute(replace(request, operation=HostOperation.INSPECT))
    def cancel(self, request: HostRequest): return self.execute(replace(request, operation=HostOperation.CANCEL))
    def wait(self, request: HostRequest): return self.execute(replace(request, operation=HostOperation.WAIT))
