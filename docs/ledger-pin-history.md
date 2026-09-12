# Chronicle pin history

Thesis consumes the Chronicle observation journal at an immutable commit. Its
incremental pin refresh verifies every commit between the existing pin and the
requested journal head before writing the pin, row-availability index, or its
TypeScript mirror.

The September 4, 2026 refresh failed after Chronicle merged three parallel
gate, test and documentation branches. The GitHub compare endpoint returned
all 24 intervening commits. The old walker treated adjacent entries as a
single parent chain, so it rejected a valid branch whose parent was an earlier
common ancestor. All 24 commits held the same observation bytes after the
first commit appended five rows. The pin remained at 216 observations even
though Chronicle had 221.

The refresh now validates the commit graph and each state's actual parents:

- Every parent must be the existing pin or a commit included in the complete
  comparison. Missing parents, cycles, duplicate parents and entries outside
  the requested head's ancestry refuse. A branch from unknown history is not
  implicitly trusted.
- Single-parent states must extend their parent's observations. A merge on
  the journal head's first-parent path must retain its first parent's exact
  observation bytes. Other merges must retain the exact bytes of at least one
  parent, so updating a review branch can import a journal append from its
  second parent. No merge may truncate or rewrite any parent's observations
  or create a state absent from every parent. New journal rows therefore enter
  through single-parent append commits on the accepted first-parent path.
- Every intermediate release inventory must preserve each parent's witnessed
  artifacts and be an exact prefix-subset of the verified final inventory.
  Each chain-bearing state must match the observation bytes witnessed by its
  own release head. A rewrite followed by restoration cannot hide on a review
  branch.
- Registry declarations on any crossed branch still bind the final catalog.
  A temporary declaration or a later merge cannot launder a downgrade.
- New row acceptance is derived only from the journal's first-parent append
  history. A review branch's date does not become the row's acceptance date.
  Existing rows and their recorded acceptance metadata are preserved.

These checks retain the existing evidence limits: a Git commit date is recorded
acceptance provenance, and an RFC 3161 receipt witnesses submitted manifest
bytes. Neither substitutes for an agency's official publication time.

`tests/test_ledger_pin.py` includes the actual 24-commit topology and signed local
release chains with parallel review branches forked both before and after a
journal append. It also refuses hidden ledger, receipt and registry rewrites,
omitted/foreign parents, rows introduced by a first-parent merge, and a review
merge's state that matches neither parent. The topology fixture contains only
public commit identities and their parents; it does not modify or replace the
observation journal.
