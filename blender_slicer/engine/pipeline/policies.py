"""Failure policy decisions, kept in one place for the runner and the facade."""

from __future__ import annotations

from dataclasses import dataclass

from ...protocol.operations import FailurePolicy


@dataclass(frozen=True)
class FailureDecision:
    abort_request: bool = False
    fail_slice: bool = False
    rollback: bool = False


def operation_failure(policy: FailurePolicy) -> FailureDecision:
    if policy == FailurePolicy.STRICT:
        return FailureDecision(abort_request=True)
    if policy == FailurePolicy.PER_SLICE:
        return FailureDecision(fail_slice=True)
    return FailureDecision(rollback=True)


def final_failure(policy: FailurePolicy) -> FailureDecision:
    return operation_failure(policy)
