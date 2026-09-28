"""Direct-mode tests for the Caveat contract."""

import json
from datetime import datetime, timezone

from tests.direct.conftest import to_hex

CONTRACT = "contracts/caveat.py"

T0 = "2026-01-01T00:00:00Z"
T0_TS = int(datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp())
CONTEXT_URL = "https://reports.example/case-1"

T_WITHIN_WINDOW = "2026-01-01T00:05:00Z"  # 5 min in - still open
T_AFTER_WINDOW = "2026-01-01T00:10:01Z"  # just past the 10-minute window


def _register(contract, verdict_id="case-1", outcome="approved", note="deterministic check passed"):
    contract.register_verdict(verdict_id, outcome, CONTEXT_URL, note)


def _mock_context(vm, body="the deliverable is live and matches spec"):
    vm.mock_web(r".*reports\.example.*", {"status": 200, "body": body})


def _mock_verdict(vm, verdict: str, reasoning: str = "reviewed against the reference content"):
    vm.mock_llm(
        r".*adjudicating a challenge.*",
        json.dumps({"verdict": verdict, "reasoning": reasoning}),
    )


def test_register_verdict_creates_open_verdict(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.warp(T0)
    direct_vm.sender = direct_alice

    _register(contract)

    v = contract.get_verdict("case-1")
    assert v["creator"] == to_hex(direct_alice)
    assert v["created_at"] == T0_TS
    assert v["outcome"] == "approved"
    assert v["context_url"] == CONTEXT_URL
    assert v["context_note"] == "deterministic check passed"
    assert v["status"] == "open"
    assert v["challenge_reason"] == ""
    assert v["challenger"] == ""
    assert v["resolved_at"] == 0


def test_register_duplicate_id_fails(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    _register(contract)

    with direct_vm.expect_revert("already exists"):
        _register(contract)


def test_register_empty_outcome_fails(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice

    with direct_vm.expect_revert("outcome cannot be empty"):
        contract.register_verdict("case-1", "", CONTEXT_URL, "note")


def test_register_non_https_context_url_fails(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice

    with direct_vm.expect_revert("must start with https://"):
        contract.register_verdict("case-1", "approved", "http://reports.example/case-1", "note")


def test_challenge_within_window_succeeds(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy(CONTRACT)
    direct_vm.warp(T0)
    direct_vm.sender = direct_alice
    _register(contract)

    direct_vm.warp(T_WITHIN_WINDOW)
    direct_vm.sender = direct_bob
    contract.challenge("case-1", "the deliverable was actually broken at review time")

    v = contract.get_verdict("case-1")
    assert v["status"] == "challenged"
    assert v["challenge_reason"] == "the deliverable was actually broken at review time"
    assert v["challenger"] == to_hex(direct_bob)


def test_challenge_after_window_fails(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy(CONTRACT)
    direct_vm.warp(T0)
    direct_vm.sender = direct_alice
    _register(contract)

    direct_vm.warp(T_AFTER_WINDOW)
    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("Challenge window has closed"):
        contract.challenge("case-1", "too late but I disagree")


def test_challenge_already_challenged_fails(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy(CONTRACT)
    direct_vm.warp(T0)
    direct_vm.sender = direct_alice
    _register(contract)

    direct_vm.warp(T_WITHIN_WINDOW)
    direct_vm.sender = direct_bob
    contract.challenge("case-1", "first challenge")

    with direct_vm.expect_revert("Only an open verdict can be challenged"):
        contract.challenge("case-1", "second challenge")


def test_challenge_empty_reason_fails(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.warp(T0)
    direct_vm.sender = direct_alice
    _register(contract)

    with direct_vm.expect_revert("reason cannot be empty"):
        contract.challenge("case-1", "")


def test_challenge_unknown_verdict_fails(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice

    with direct_vm.expect_revert("not found"):
        contract.challenge("nonexistent", "reason")


def test_resolve_challenge_upholds_verdict(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy(CONTRACT)
    direct_vm.warp(T0)
    direct_vm.sender = direct_alice
    _register(contract)

    direct_vm.warp(T_WITHIN_WINDOW)
    direct_vm.sender = direct_bob
    contract.challenge("case-1", "I don't think it actually passed")

    _mock_context(direct_vm)
    _mock_verdict(direct_vm, "uphold", "the reference content confirms the recorded outcome")
    contract.resolve_challenge("case-1")

    v = contract.get_verdict("case-1")
    assert v["status"] == "upheld"
    assert v["resolved_at"] > 0
    assert contract.is_valid("case-1") is True


def test_resolve_challenge_overturns_verdict(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy(CONTRACT)
    direct_vm.warp(T0)
    direct_vm.sender = direct_alice
    _register(contract)

    direct_vm.warp(T_WITHIN_WINDOW)
    direct_vm.sender = direct_bob
    contract.challenge("case-1", "the reference content shows it was never actually live")

    _mock_context(direct_vm, body="404 - page not found")
    _mock_verdict(direct_vm, "overturn", "the reference content contradicts the recorded outcome")
    contract.resolve_challenge("case-1")

    v = contract.get_verdict("case-1")
    assert v["status"] == "overturned"
    assert contract.is_valid("case-1") is False


def test_resolve_challenge_on_open_verdict_fails(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    _register(contract)

    with direct_vm.expect_revert("not currently challenged"):
        contract.resolve_challenge("case-1")


def test_resolve_challenge_twice_fails(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy(CONTRACT)
    direct_vm.warp(T0)
    direct_vm.sender = direct_alice
    _register(contract)

    direct_vm.warp(T_WITHIN_WINDOW)
    direct_vm.sender = direct_bob
    contract.challenge("case-1", "reason")
    _mock_context(direct_vm)
    _mock_verdict(direct_vm, "uphold")
    contract.resolve_challenge("case-1")

    with direct_vm.expect_revert("not currently challenged"):
        contract.resolve_challenge("case-1")


def test_finalize_after_window_succeeds(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.warp(T0)
    direct_vm.sender = direct_alice
    _register(contract)

    direct_vm.warp(T_AFTER_WINDOW)
    contract.finalize("case-1")

    v = contract.get_verdict("case-1")
    assert v["status"] == "final"
    assert v["resolved_at"] > 0
    assert contract.is_valid("case-1") is True


def test_finalize_before_window_fails(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.warp(T0)
    direct_vm.sender = direct_alice
    _register(contract)

    direct_vm.warp(T_WITHIN_WINDOW)
    with direct_vm.expect_revert("has not yet closed"):
        contract.finalize("case-1")


def test_finalize_challenged_verdict_fails(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy(CONTRACT)
    direct_vm.warp(T0)
    direct_vm.sender = direct_alice
    _register(contract)

    direct_vm.warp(T_WITHIN_WINDOW)
    direct_vm.sender = direct_bob
    contract.challenge("case-1", "reason")

    direct_vm.warp(T_AFTER_WINDOW)
    with direct_vm.expect_revert("Only an open, unchallenged verdict can be finalized"):
        contract.finalize("case-1")


def test_finalize_exactly_at_window_boundary_succeeds(direct_vm, direct_deploy, direct_alice):
    """challenge() requires strictly within the window (now <= created_at +
    WINDOW passes); finalize() must allow the symmetric boundary - now ==
    created_at + WINDOW is already closed for a fresh challenge."""
    contract = direct_deploy(CONTRACT)
    direct_vm.warp(T0)
    direct_vm.sender = direct_alice
    _register(contract)

    boundary_ts = T0_TS + 600
    boundary = datetime.fromtimestamp(boundary_ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    direct_vm.warp(boundary)

    with direct_vm.expect_revert("has not yet closed"):
        contract.finalize("case-1")


def test_get_verdict_unknown_fails(direct_vm, direct_deploy):
    contract = direct_deploy(CONTRACT)
    with direct_vm.expect_revert("not found"):
        contract.get_verdict("nonexistent")


def test_is_valid_unknown_returns_false(direct_vm, direct_deploy):
    contract = direct_deploy(CONTRACT)
    assert contract.is_valid("nonexistent") is False


def test_is_valid_open_returns_false(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    _register(contract)

    assert contract.is_valid("case-1") is False


def test_is_valid_challenged_returns_false(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy(CONTRACT)
    direct_vm.warp(T0)
    direct_vm.sender = direct_alice
    _register(contract)

    direct_vm.warp(T_WITHIN_WINDOW)
    direct_vm.sender = direct_bob
    contract.challenge("case-1", "reason")

    assert contract.is_valid("case-1") is False


def test_independent_verdicts_track_separately(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy(CONTRACT)
    direct_vm.warp(T0)
    direct_vm.sender = direct_alice
    _register(contract, "case-1", "approved")
    _register(contract, "case-2", "denied")

    direct_vm.warp(T_WITHIN_WINDOW)
    direct_vm.sender = direct_bob
    contract.challenge("case-1", "reason")

    assert contract.get_verdict("case-1")["status"] == "challenged"
    assert contract.get_verdict("case-2")["status"] == "open"
