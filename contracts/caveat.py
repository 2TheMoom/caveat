# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

from dataclasses import dataclass
from datetime import datetime, timezone
from genlayer import *

CHALLENGE_WINDOW_SECONDS = 600  # 10 minutes - proven live across three sibling
                                  # projects (Waypoint, Tote, Salvage Arbiter)

REQUEST_HEADERS = {
    "Accept": "text/html,application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}


@allow_storage
@dataclass
class Verdict:
    creator: str
    created_at: u256
    outcome: str
    context_url: str
    context_note: str
    status: str  # "open" -> "challenged" -> "upheld"|"overturned", or "open" -> "final"
    challenge_reason: str
    challenger: str
    resolved_at: u256  # 0 until final/upheld/overturned


class Caveat(gl.Contract):
    """A generic dispute-escalation primitive: register a deterministic
    verdict, give anyone a time-boxed window to contest it, and escalate to
    AI judgment only when a genuine dispute is actually filed.

    This is the same three-step pattern - settle deterministically, open a
    short challenge window, escalate to `gl.nondet.exec_prompt` only on a
    real dispute, and only the uphold/overturn verdict is consensus-critical
    - independently reimplemented inline, three separate times, across this
    account's Waypoint (deliverable verification), Tote (market resolution)
    and Salvage Arbiter (fund-recovery adjudication). Caveat extracts it
    into one reusable building block: register any outcome your own
    contract already computed, and let Caveat own the challenge window and
    dispute escalation instead of rebuilding it.

    register_verdict(verdict_id, outcome, context_url, context_note) is
    deliberately unopinionated about how `outcome` was reached - Caveat
    doesn't recompute it, it only protects it. `context_url` is whatever a
    validator can re-fetch to judge a dispute against (a receipt, a report,
    a rendered page); `context_note` is the caller's own explanation of why
    `outcome` was reached, given to the LLM as background, not evidence.

    challenge(verdict_id, reason) - permissionless, callable by anyone
    within `CHALLENGE_WINDOW_SECONDS` of registration - freezes the verdict
    and records a reason. resolve_challenge(verdict_id) re-fetches
    context_url and asks an LLM to weigh the challenge reason against the
    original outcome and context; validators independently recompute the
    same prompt and must agree on the uphold/overturn verdict before
    consensus is reached - the reasoning text is informational, only the
    verdict itself is consensus-critical. Both outcomes are terminal: a
    challenge is one shot, not a loop, so a caller integrating this doesn't
    have to reason about repeated re-litigation.

    finalize(verdict_id) - callable once the window closes with no
    challenge - marks the verdict settled with no LLM involved at all. Any
    other contract can gate its own logic on is_valid(verdict_id): true
    once a verdict is final or upheld, false if overturned or still
    pending. No value ever moves through this contract.
    """

    verdicts: TreeMap[str, Verdict]

    def __init__(self):
        pass

    def _now(self) -> int:
        return int(datetime.now(timezone.utc).timestamp())

    def _get(self, verdict_id: str) -> Verdict:
        if verdict_id not in self.verdicts:
            raise gl.vm.UserError(f"Verdict '{verdict_id}' not found")
        return self.verdicts[verdict_id]

    @gl.public.write
    def register_verdict(
        self, verdict_id: str, outcome: str, context_url: str, context_note: str
    ) -> None:
        if verdict_id in self.verdicts:
            raise gl.vm.UserError(f"Verdict '{verdict_id}' already exists")
        if not outcome:
            raise gl.vm.UserError("outcome cannot be empty")
        if not context_url.startswith("https://"):
            raise gl.vm.UserError("context_url must start with https://")

        self.verdicts[verdict_id] = Verdict(
            creator=gl.message.sender_address.as_hex,
            created_at=self._now(),
            outcome=outcome,
            context_url=context_url,
            context_note=context_note,
            status="open",
            challenge_reason="",
            challenger="",
            resolved_at=0,
        )

    @gl.public.write
    def challenge(self, verdict_id: str, reason: str) -> None:
        v = self._get(verdict_id)
        if v.status != "open":
            raise gl.vm.UserError("Only an open verdict can be challenged")
        if self._now() > v.created_at + CHALLENGE_WINDOW_SECONDS:
            raise gl.vm.UserError("Challenge window has closed for this verdict")
        if not reason:
            raise gl.vm.UserError("reason cannot be empty")

        v.status = "challenged"
        v.challenge_reason = reason
        v.challenger = gl.message.sender_address.as_hex

    def _judge(
        self, outcome: str, context_url: str, context_note: str, challenge_reason: str
    ) -> dict:
        def leader_fn() -> dict:
            content = gl.nondet.web.render(context_url, mode="text")
            prompt = f"""You are adjudicating a challenge to a recorded verdict on
Caveat, a generic dispute-escalation primitive.

Recorded outcome: {outcome}

The registering contract's own explanation for this outcome:
{context_note}

A challenger disputes it, giving this reason:
{challenge_reason}

Current content at the verdict's reference URL ({context_url}):
\"\"\"
{content}
\"\"\"

Decide whether the challenge is credible: does the challenger's reason,
weighed against the reference content, show the recorded outcome was
actually wrong - not merely that the challenger disagrees with it or would
have preferred a different result. Uphold the outcome unless the challenge
is specific and substantiated by the reference content.

Respond in JSON only, perfectly parsable, no other text:
{{"verdict": str, "reasoning": str}}
verdict is "uphold" or "overturn"; reasoning is one or two sentences.
"""
            result = gl.nondet.exec_prompt(prompt, response_format="json")
            return {"verdict": str(result.get("verdict", "uphold")).lower()}

        def validator_fn(leaders_res) -> bool:
            if not isinstance(leaders_res, gl.vm.Return):
                return False
            mine = leader_fn()
            return mine["verdict"] == leaders_res.calldata["verdict"]

        return gl.vm.run_nondet_unsafe(leader_fn, validator_fn)

    @gl.public.write
    def resolve_challenge(self, verdict_id: str) -> None:
        v = self._get(verdict_id)
        if v.status != "challenged":
            raise gl.vm.UserError("This verdict is not currently challenged")

        result = self._judge(v.outcome, v.context_url, v.context_note, v.challenge_reason)
        v.status = "overturned" if result["verdict"] == "overturn" else "upheld"
        v.resolved_at = self._now()

    @gl.public.write
    def finalize(self, verdict_id: str) -> None:
        v = self._get(verdict_id)
        if v.status != "open":
            raise gl.vm.UserError("Only an open, unchallenged verdict can be finalized")
        if self._now() <= v.created_at + CHALLENGE_WINDOW_SECONDS:
            raise gl.vm.UserError("Challenge window has not yet closed")

        v.status = "final"
        v.resolved_at = self._now()

    @gl.public.view
    def get_verdict(self, verdict_id: str) -> dict:
        v = self._get(verdict_id)
        return {
            "creator": v.creator,
            "created_at": v.created_at,
            "outcome": v.outcome,
            "context_url": v.context_url,
            "context_note": v.context_note,
            "status": v.status,
            "challenge_reason": v.challenge_reason,
            "challenger": v.challenger,
            "resolved_at": v.resolved_at,
        }

    @gl.public.view
    def is_valid(self, verdict_id: str) -> bool:
        if verdict_id not in self.verdicts:
            return False
        return self.verdicts[verdict_id].status in ("final", "upheld")
