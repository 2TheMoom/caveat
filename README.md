# Caveat
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/license/mit/)
[![Discord](https://img.shields.io/badge/Discord-Join%20us-5865F2?logo=discord&logoColor=white)](https://discord.gg/8Jm4v89VAu)
[![Telegram](https://img.shields.io/badge/Telegram--T.svg?style=social&logo=telegram)](https://t.me/genlayer)
[![Twitter](https://img.shields.io/twitter/url/https/twitter.com/yeagerai.svg?style=social&label=Follow%20%40GenLayer)](https://x.com/GenLayer)

## About
Caveat is a generic **dispute-escalation primitive** - register a
deterministic verdict, give anyone a short window to contest it, and
escalate to AI judgment only when a genuine dispute is actually filed.

The name is borrowed from probate and patent law, where a caveat is a
formal notice that suspends a pending grant until the objection it raises
is resolved - exactly the shape of this contract's own lifecycle.

This same three-step pattern - settle deterministically, open a
time-boxed challenge window, escalate to `gl.nondet.exec_prompt` only on a
real dispute, and treat only the uphold/overturn verdict as
consensus-critical - was independently reimplemented inline, three
separate times, across this account's [Waypoint](https://github.com/2TheMoom/waypoint)
(deliverable verification), [Tote](https://github.com/2TheMoom/tote)
(prediction-market resolution), and
[Salvage Arbiter](https://github.com/2TheMoom/salvage-arbiter) (fund-recovery
adjudication). Caveat extracts it into one reusable building block: any
other GenLayer contract registers whatever outcome it already computed,
and lets Caveat own the challenge window and dispute escalation instead of
rebuilding the pattern from scratch.

`register_verdict(verdict_id, outcome, context_url, context_note)` is
deliberately unopinionated about how `outcome` was reached - Caveat
doesn't recompute it, it only protects it. `context_url` is whatever a
validator can re-fetch to judge a dispute against (a receipt, a report, a
rendered page); `context_note` is the caller's own explanation of why
`outcome` was reached, given to the LLM as background, not evidence.

`challenge(verdict_id, reason)` - permissionless, callable by anyone
within the 10-minute window - freezes the verdict and records a reason.
`resolve_challenge(verdict_id)` re-fetches `context_url` and asks an LLM
to weigh the challenge reason against the original outcome and context;
validators independently recompute the identical prompt and must agree on
the uphold/overturn verdict before consensus is reached - the reasoning
text is informational, only the verdict itself is consensus-critical.
Both outcomes are terminal: a challenge is one shot, not a loop, so a
caller integrating this doesn't have to reason about repeated
re-litigation.

`finalize(verdict_id)` - callable once the window closes with no
challenge - marks the verdict settled with no LLM involved at all. Any
other contract can gate its own logic on `is_valid(verdict_id)`: true once
a verdict is final or upheld, false if overturned or still pending. No
value ever moves through this contract.

## Deployment
Deployed on **GenLayer Bradbury Testnet** (chain ID 4221):
- **Contract:** [`0x5A1565836a254D16091325F23F3a848D663B515C`](https://explorer-bradbury.genlayer.com/address/0x5A1565836a254D16091325F23F3a848D663B515C)
- Verified via 22 passing direct-mode tests (`python -m pytest tests/direct/`),
  covering verdict registration and its validation (duplicate id, empty
  outcome, non-`https://` context url), challenging within and after the
  window, a verdict that's already challenged or unknown, both
  `resolve_challenge` outcomes (upheld and overturned) and their effect on
  `is_valid`, resolving an open (not-yet-challenged) or already-resolved
  verdict, `finalize` before/after/exactly-at the window boundary and on a
  challenged verdict, and independent verdicts tracked separately.
- **Live-verified with real GEN**, not just direct-mode tests: registered
  a verdict citing a genuinely checkable public fact (the official
  [GenLayer project boilerplate](https://github.com/genlayerlabs/genlayer-project-boilerplate)'s
  README, which describes its example contract as a football-bets game),
  then filed a deliberately **false** challenge claiming the example is
  actually a chess game. `resolve_challenge()` reached full validator
  consensus (4/5 - one validator timeout, still ACCEPTED/AGREE) and
  correctly **upheld** the true original outcome after re-fetching the
  real README and weighing it against the bogus challenge - `status:
  "upheld"`, `is_valid: true`. A second verdict was registered with no
  challenge and independently confirmed to `finalize()` cleanly once its
  window passed. Both txs reached 5/5 or 4/5 validator agreement.

## What's included
- `contracts/caveat.py` — the Caveat Intelligent Contract
- `tests/direct/test_caveat.py` — direct-mode tests (in-memory, mocked web/LLM, time-warped)
- **Contract linting** — static analysis to catch common contract issues before deployment
- **CI pipeline** — GitHub Actions workflow for linting and direct tests
- Configuration file template and a deployment script

This is a contract-only primitive, deliberately without a frontend - the
point is to be called by other contracts and integrators, not to be a
product on its own.

## Requirements
- Python >= 3.12
- [GenLayer CLI](https://github.com/genlayerlabs/genlayer-cli) globally installed: `npm install -g genlayer`
- GenLayer Studio (for integration tests and deployment): Install from [Docs](https://docs.genlayer.com/developers/intelligent-contracts/tooling-setup#using-the-genlayer-studio) or use the hosted [GenLayer Studio](https://studio.genlayer.com/)

## Project Structure

```
contracts/              # Python intelligent contracts
  caveat.py                # Caveat
tests/
  direct/                # Fast in-memory tests (no Studio required)
    test_caveat.py
deploy/                  # TypeScript deployment scripts
gltest.config.yaml       # Test runner network configuration
pyproject.toml           # Python/pytest configuration
.github/workflows/       # CI pipeline
```

## Quick Start

### 1. Set up Python environment

```shell
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Lint the contract

```shell
genvm-lint check contracts/caveat.py
```

### 3. Run direct mode tests

```shell
python -m pytest tests/direct/ -v
```

Use `python -m pytest`, not bare `pytest` - depending on your installed
pytest version, running the bare command can fail to put the project
root on `sys.path`, breaking test discovery with
`ModuleNotFoundError: No module named 'tests'`.

### 4. Deploy the contract

1. Choose your network: `genlayer network`
2. Deploy: `genlayer deploy` (runs the script in `/deploy/deployScript.ts`)

## How Caveat Works

1. **`register_verdict(verdict_id, outcome, context_url, context_note)`**
   — records an outcome your own contract already computed. Reverts if
   the id already exists, `outcome` is empty, or `context_url` doesn't
   start with `https://`.
2. **`challenge(verdict_id, reason)`** — permissionless, only within the
   10-minute window after registration, only on a still-`open` verdict.
3. **`resolve_challenge(verdict_id)`** — only on a `challenged` verdict.
   Re-fetches `context_url`, asks an LLM to weigh `reason` against the
   recorded `outcome` and `context_note`, and moves the verdict to a
   terminal `upheld` or `overturned` state.
4. **`finalize(verdict_id)`** — only on a still-`open` verdict once the
   window has passed with no challenge. Moves it to `final`.
5. **`get_verdict(verdict_id)`** / **`is_valid(verdict_id)`** — read back
   full state, or just the yes/no a downstream contract actually needs:
   true once `final` or `upheld`, false if `overturned` or still pending.

### Example: gating a downstream release

```python
# In some other contract, or from a script:
caveat.register_verdict("payout-1", "approved", "https://receipts.example/1", "deterministic check passed")
# ... 10 minutes pass with no challenge ...
caveat.finalize("payout-1")
if caveat.is_valid("payout-1"):
    release_funds()  # only reachable once Caveat says the verdict stands
```

## Testing Strategy

| Test Type | Command | Speed | Requires Studio |
|-----------|---------|-------|-----------------|
| **Lint** | `genvm-lint check contracts/caveat.py` | ~250ms | No |
| **Direct** | `python -m pytest tests/direct/ -v` | ~ms/test | No |

## Community
- **[Discord](https://discord.gg/8Jm4v89VAu)**: Discussions, support, and announcements
- **[Telegram](https://t.me/genlayer)**: Informal chats and quick updates

## Documentation
For detailed information, see our [documentation](https://docs.genlayer.com/).

## License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
