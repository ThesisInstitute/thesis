# Receipt pin

Every witnessed append proposal runs Chronicle's own code. `resolve_pending.py`
stages Chronicle's ledger branch and runs that branch's
`scripts/build_series_catalog.py` with the resolver's own interpreter. The
generator imports `check_thesis_facts_append.py` and `receipt_pins.py`, and
both import the `receipt` package. Chronicle tests that code only under the
receipt its `uv.lock` names. The resolver runs it under the receipt thesis's
`uv.lock` names. So the two locks must name the same receipt.

Chronicle bumps receipt on its own schedule. On 2026-09-28
[PolicyEngine/chronicle#299](https://github.com/PolicyEngine/chronicle/pull/299)
locked receipt 0.6.2, whose `receipt.release_chain.PinnedSigner` 0.6.1 lacks.
Thesis still installed 0.6.1, so resolver run
[36503673388](https://github.com/ThesisInstitute/thesis/actions/runs/36503673388)
fetched every print and then failed while proposing the append:

```
cannot import name 'PinnedSigner' from 'receipt.release_chain'
```

## How it presents now

`scripts/chronicle_receipt_pin.py` compares three versions: the receipt
installed for the resolver's interpreter, the one thesis's `uv.lock` names, and
the one Chronicle's `uv.lock` names at one commit. When the locks name the same
version, they must also name the same artifact hashes. A lock it cannot parse, a
lock with no receipt, one with two receipt entries, and one whose version or
hashes are not well formed (a hash must be a full SHA-256, SHA-384 or SHA-512
hex digest) are all refused. The check never raises. Its printed lines carry no
line break and neither Actions command marker (`::`, `##[`), and a parser
error is reported by type and position only, never by the text it quotes.

It runs in four places:

- `resolve_pending.py`, right after it reads the ledger branch head and before
  any capture work. It prints one line, `RECEIPT PIN REFUSED: <reason>`, and an
  error annotation on the run's summary page, and exits 4. The workflow treats
  4 like 3 (refused rows): the ledger may have moved upstream, so the pin,
  witness and deploy steps still publish it, and then "Fail the run on refused
  rows" fails the job. The failure issue is titled "Resolution stopped on a
  receipt pin mismatch <date>" and quotes the reason
  (`scripts/resolution_alert.py`). On the resolution-status page each overdue
  cell the resolver routes says `RECEIPT_PIN_STOP`: the run stopped before it
  fetched any figure.
- Again at the staged base, just before Chronicle's generator runs (in the
  catalog preflight and in the proposal itself). No caller can run the
  generator unchecked. These refusals raise with the same prefix.
- `receipt-pin-drift.yml`, every three hours and on pull requests that change
  `pyproject.toml` or `uv.lock`. It opens an issue titled "Receipt pin drift:
  thesis and Chronicle's ledger branch lock different receipts" while the
  resolver would refuse (exit 1, which includes a fetched lock it cannot parse),
  and closes it once they agree. Exit 2 (Chronicle's lock could not be fetched,
  or the comparison itself crashed) fails the run without an issue: it says
  nothing about drift.
- The CI job `resolver-runtime`. It runs the resolver's install on the runner's
  own `python3` and imports every script the resolution run starts.

To run the comparison locally:

```sh
python3 scripts/chronicle_receipt_pin.py                    # thesis lock vs Chronicle's branch head
python3 scripts/chronicle_receipt_pin.py --check-installed  # also this interpreter
python3 scripts/chronicle_receipt_pin.py --installed-only   # this interpreter vs thesis's lock, no network
```

## Bump thesis to Chronicle's receipt

When Chronicle moves first:

1. Pin the `custody` extra in `pyproject.toml` to `receipt==X; python_version >= '3.11'`.
2. Run `uv lock --upgrade-package receipt`. The diff should touch only
   receipt's entry and the `brier` custody specifier.
3. Update the version in the skip message in `tests/test_producer_signing.py`
   and in the checklist in `docs/producer-signing-ceremony.md`.
4. Run the full suite at the new pin. Thesis's own record-chain code
   (`verify_record_chain.py`) imports `receipt.sign`, so read receipt's diff for
   changes there.

[ThesisInstitute/thesis#302](https://github.com/ThesisInstitute/thesis/pull/302)
is the last such bump. The resolver workflow has no version to edit. It
installs `uv.lock`'s `resolver` and `custody` extras through
`.github/actions/install-resolver-python`. That action pins uv, turns off
setup-uv's cache, runs `uv export --locked`, and then
`uv pip install --require-hashes --no-cache --no-build`. So every artifact is
downloaded and hashed in the run, an artifact that differs from the lock's hash
or a dependency the lock does not pin fails the install, and nothing is built
from source with unhashed build tools.

## Why thesis's lock decides

The resolver could instead install whatever receipt Chronicle's lock names. That
would give Chronicle's ledger branch no new power. Its head's code already runs
in the resolver's step, as the same user. Until
[ThesisInstitute/thesis#337](https://github.com/ThesisInstitute/thesis/pull/337)
lands it inherits the step's environment, `GH_TOKEN` included, and
[#338](https://github.com/ThesisInstitute/thesis/issues/338) tracks how the
step's secrets, the producer signing key among them, stay readable to it
through `/proc` even after that.

But thesis's own code in the same process imports `receipt.sign` too
(`resolve_pending.py` → `witnessed_timeline.py` → `verify_record_chain.py`). If
Chronicle's lock chose the receipt, that code would run under a version thesis's
suite never ran, chosen outside thesis's review. A run's installed code could
also no longer be recovered from a thesis commit. So thesis's lock chooses, and
a disagreement stops the run rather than changing what it executes.

## Limits

- Only receipt is compared. The generator also runs under thesis's
  `cryptography` (which receipt imports, and which `ledger_release_chain.py`
  imports directly), `cffi`, `pycparser` and Python version. Those can differ
  from what Chronicle's CI uses. A mismatch there is not refused.
- The check proves the locks agree, not that Chronicle's generator works under
  them. The append gate in Chronicle still judges every proposal.
