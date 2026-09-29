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
version, they must also name the same artifact hashes. The check runs in four
places:

- `resolve_pending.py`, right after it reads the ledger branch head and before
  any capture work. The step "Resolve pending cells against official prints"
  exits 4 with `RECEIPT PIN REFUSED: <reason>`, the run summary shows it as an
  error annotation, and the "Resolution loop failed" issue quotes it.
- Again at the staged base, just before Chronicle's generator runs (in the
  catalog preflight and in the proposal itself). No caller can run the
  generator unchecked.
- `receipt-pin-drift.yml`, every three hours and on pull requests that change
  `pyproject.toml` or `uv.lock`. It opens an issue titled "Receipt pin drift:
  thesis and Chronicle's ledger branch lock different receipts" while the locks
  differ, and closes it once they agree.
- The CI job `resolver-runtime`. It runs the resolver's install on the runner's
  own `python3` and imports what the resolution run imports.

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
`.github/actions/install-resolver-python`, which runs `uv export --locked` and
then `uv pip install --require-hashes`. So an artifact that differs from the
lock's hash, or a dependency the lock does not pin, fails the install.

## Why thesis's lock decides

The resolver could instead install whatever receipt Chronicle's lock names. That
would give Chronicle's ledger branch no new power: its head's code already runs
in the resolver's step, as the same user, with that step's environment
(`GH_TOKEN` included). But thesis's own code in the same process imports
`receipt.sign` too (`resolve_pending.py` → `witnessed_timeline.py` →
`verify_record_chain.py`). If Chronicle's lock chose the receipt, that code
would run under a version thesis's suite never ran, chosen outside thesis's
review, and a run's installed code could no longer be recovered from a thesis
commit. So thesis's lock chooses, and a disagreement stops the run rather than
changing what it executes.
