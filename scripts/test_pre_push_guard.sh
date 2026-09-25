#!/bin/bash
# Regression suite for .githooks/pre-push (records-path guard).
#
# Self-contained: builds throwaway repos under mktemp and drives the hook
# both directly (crafted stdin lines) and through real `git push` runs via
# core.hooksPath. The hook is always invoked with `sh`, so on Debian-family
# CI runners this doubles as a dash/POSIX check. Covers the rebase
# false-positive fix, commit-level walk semantics (add-then-delete),
# main-endpoint discrimination, break-glass, fail-closed unverifiable
# paths, the audit's in-scope-parent and content-closure rules, and the
# 2026-07-31 adversarial-review attacks (forged/stale comparator,
# origin/main ref shadowing, refspec-less fetch, fork-to-upstream
# introduction, missing-tree walk errors, replacement refs, grafts,
# shallow clones, and equivalent fetch/push URL spellings).
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOK="$ROOT/.githooks/pre-push"
S="$(mktemp -d "${TMPDIR:-/tmp}/prepush-guard-test.XXXXXX")" || {
    echo "mktemp failed; no fixtures, no result" >&2
    exit 2
}
trap 'rm -rf "$S"' EXIT
ZERO40=0000000000000000000000000000000000000000
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
export GIT_AUTHOR_NAME=T GIT_AUTHOR_EMAIL=t@t
export GIT_COMMITTER_NAME=T GIT_COMMITTER_EMAIL=t@t
unset THESIS_ALLOW_RECORDS_PUSH

pass=0; fail=0
check() { # check <name> <expected_rc> <actual_rc> [stderr_file must_contain]
    local name=$1 want=$2 got=$3
    if [ "$got" = "$want" ]; then
        if [ $# -ge 5 ] && ! grep -q "$5" "$4"; then
            echo "FAIL $name (rc ok, missing output: $5)"; fail=$((fail+1)); return
        fi
        echo "PASS $name"; pass=$((pass+1))
    else
        echo "FAIL $name (want rc=$want got rc=$got)"; sed 's/^/    /' "${4:-/dev/null}"
        fail=$((fail+1))
    fi
}
hook() { # hook <clone_dir> <remote_name> <line...> -> rc in $rc, stderr in $S/err
    # $2 of a pre-push hook is the push destination URL; the guard pins its
    # comparator by fetching main from exactly that destination.
    local d=$1 rn=$2; shift 2
    local url
    url=$(git -C "$d" remote get-url "$rn" 2>/dev/null || echo "other-url")
    printf '%s\n' "$@" | (cd "$d" && sh "$HOOK" "$rn" "$url" 2>"$S/err")
    rc=$?
}
hook_url() { # hook_url <clone_dir> <remote_name> <url> <line...>
    local d=$1 rn=$2 u=$3; shift 3
    printf '%s\n' "$@" | (cd "$d" && sh "$HOOK" "$rn" "$u" 2>"$S/err")
    rc=$?
}
walked() { # walked <dir> <base> <tip> <commit>: is <commit> in the guard's walk?
    git -C "$1" -c log.follow=false -c diff.ignoreSubmodules=none log \
        --full-history --format=%H "$2..$3" -- records/ | grep -qx "$4"
}
fresh_origin() { # fresh_origin <name>: bare origin + clone $S/<name> with an epoch
    git init -q --bare "$S/$1.git"
    git -C "$S/$1.git" symbolic-ref HEAD refs/heads/main
    git clone -q "$S/$1.git" "$S/$1" 2>/dev/null
    commit_file "$S/$1" src/seed.txt s "seed $1"
    commit_file "$S/$1" scripts/verify_records_attestations.py "# stub" "epoch $1"
}
commit_file() { # commit_file <dir> <path> <content> <msg>
    mkdir -p "$1/$(dirname "$2")"
    echo "$3" > "$1/$2"
    git -C "$1" add -A
    git -C "$1" commit -qm "$4"
}

# ---- setup: origin whose main gains an attested-style recorder commit
git init -q --bare "$S/origin.git"
git -C "$S/origin.git" symbolic-ref HEAD refs/heads/main
git clone -q "$S/origin.git" "$S/seed" 2>/dev/null
commit_file "$S/seed" records/seed.txt r0 "init records"
commit_file "$S/seed" src/a.txt a "init src"
# the enforcement epoch is self-anchoring: the commit introducing the
# verifier. Seeding it here keeps the in-scope-parent rule under test.
commit_file "$S/seed" scripts/verify_records_attestations.py "# stub" \
    "introduce the records verifier (epoch)"
git -C "$S/seed" push -q origin HEAD:main
INIT=$(git -C "$S/seed" rev-parse HEAD)

git clone -q "$S/origin.git" "$S/dev" 2>/dev/null
git -C "$S/dev" checkout -qb feat
commit_file "$S/dev" src/b.txt b "feat: src change"
git -C "$S/dev" push -q origin feat
OLD_REMOTE=$(git -C "$S/dev" rev-parse feat)

commit_file "$S/seed" records/r1.txt r1 "Record forecast surfaces"
git -C "$S/seed" push -q origin main
git -C "$S/dev" fetch -q origin
git -C "$S/dev" rebase -q origin/main feat
LOCAL=$(git -C "$S/dev" rev-parse feat)
TIP=$(git -C "$S/dev" rev-parse origin/main)

# ---- 1: the motivating false positive — rebased branch, no own records
hook "$S/dev" origin "refs/heads/feat $LOCAL refs/heads/feat $OLD_REMOTE"
check "01 rebased branch over recorder commits allowed" 0 $rc

# ---- 2-4: a branch's own records commit blocks; break-glass overrides
commit_file "$S/dev" records/evil.txt evil "touch records"
LOCAL2=$(git -C "$S/dev" rev-parse feat)
hook "$S/dev" origin "refs/heads/feat $LOCAL2 refs/heads/feat $OLD_REMOTE"
check "02 own records commit blocks (existing ref)" 1 $rc "$S/err" "records/evil.txt"
hook "$S/dev" origin "refs/heads/feat $LOCAL2 refs/heads/feat $ZERO40"
check "03 own records commit blocks (new ref)" 1 $rc "$S/err" "records/evil.txt"
printf '%s\n' "refs/heads/feat $LOCAL2 refs/heads/feat $OLD_REMOTE" \
    | (cd "$S/dev" && THESIS_ALLOW_RECORDS_PUSH=1 sh "$HOOK" origin x 2>"$S/err")
check "04 break-glass overrides with notice" 0 $? "$S/err" "THESIS_ALLOW_RECORDS_PUSH=1"
git -C "$S/dev" reset -q --hard "$LOCAL"

# ---- 5-8: pushes to main are judged on every published commit
git -C "$S/dev" checkout -q main
git -C "$S/dev" merge -q --ff-only origin/main
commit_file "$S/dev" records/r2.txt r2 "local records on main"
hook "$S/dev" origin "refs/heads/main $(git -C "$S/dev" rev-parse main) refs/heads/main $TIP"
check "05 main push publishing a records commit blocks" 1 $rc "$S/err" "records/r2.txt"
git -C "$S/dev" reset -q --hard "$TIP"
commit_file "$S/dev" src/d.txt d "src on main"
hook "$S/dev" origin "refs/heads/main $(git -C "$S/dev" rev-parse main) refs/heads/main $TIP"
check "06 main push with src-only commit allowed" 0 $rc
# propagating current main to a remote that lacks the recorder commits
# must still block — a branch-contribution check would see nothing here
hook "$S/dev" origin "refs/heads/main $TIP refs/heads/main $INIT"
check "07 main to stale remote still blocks (endpoint range kept)" 1 $rc "$S/err" "records/r1.txt"
# add-then-delete on a main push: endpoint trees match, commits still red
git -C "$S/dev" reset -q --hard "$TIP"
commit_file "$S/dev" records/hidden.txt h "add hidden record"
git -C "$S/dev" rm -q records/hidden.txt
git -C "$S/dev" commit -qm "remove hidden record"
hook "$S/dev" origin "refs/heads/main $(git -C "$S/dev" rev-parse main) refs/heads/main $TIP"
check "08 add-then-delete on main blocks (commit-level walk)" 1 $rc "$S/err" "records/hidden.txt"
git -C "$S/dev" reset -q --hard "$TIP"

# ---- 9: new branch off an older base while main gained recorder commits
git -C "$S/dev" checkout -qb newb "$INIT"
commit_file "$S/dev" src/c.txt c "src on newb"
hook "$S/dev" origin "refs/heads/newb $(git -C "$S/dev" rev-parse newb) refs/heads/newb $ZERO40"
check "09 new branch off old base allowed (own contribution only)" 0 $rc

# ---- 10: deletion pushes are skipped
hook "$S/dev" origin "refs/heads/feat $ZERO40 refs/heads/feat $OLD_REMOTE"
check "10 branch deletion allowed" 0 $rc

# ---- 11: add-then-delete records commits on a branch (three-dot-blind)
git -C "$S/dev" checkout -q feat
commit_file "$S/dev" records/smuggle.txt s "add smuggled record"
git -C "$S/dev" rm -q records/smuggle.txt
git -C "$S/dev" commit -qm "remove smuggled record"
hook "$S/dev" origin "refs/heads/feat $(git -C "$S/dev" rev-parse feat) refs/heads/feat $OLD_REMOTE"
check "11 add-then-delete on branch blocks" 1 $rc "$S/err" "records/smuggle.txt"
git -C "$S/dev" reset -q --hard "$LOCAL"

# ---- 12-14: failed refresh — endpoint fallback and fail-closed new refs
git clone -q "$S/origin.git" "$S/dev2" 2>/dev/null
git -C "$S/dev2" checkout -qb fb
commit_file "$S/dev2" records/topo.txt t "records on fb"
T=$(git -C "$S/dev2" rev-parse fb)
git -C "$S/dev2" update-ref refs/remotes/origin/main "$T"      # forge/stale
git -C "$S/dev2" remote set-url origin "$S/does-not-exist.git" # fetch fails
hook "$S/dev2" origin "refs/heads/fb $T refs/heads/fb $TIP"
check "12 failed refresh: existing ref falls back to endpoint, blocks" 1 $rc "$S/err" "records/topo.txt"
hook "$S/dev2" origin "refs/heads/fb $T refs/heads/fb $ZERO40"
check "13 failed refresh: new ref refuses as unverifiable" 1 $rc "$S/err" "cannot verify"
printf '%s\n' "refs/heads/fb $T refs/heads/fb $ZERO40" \
    | (cd "$S/dev2" && THESIS_ALLOW_RECORDS_PUSH=1 sh "$HOOK" origin x 2>"$S/err")
check "14 unverifiable + break-glass allows with notice" 0 $? "$S/err" "THESIS_ALLOW_RECORDS_PUSH=1"

# ---- 15-16: disjoint (orphan) history under the commit walk
git -C "$S/dev" checkout -q --orphan orph
git -C "$S/dev" rm -rq --cached .
rm -rf "$S/dev/src" "$S/dev/records"
commit_file "$S/dev" records/orphan.txt o "orphan with records"
hook "$S/dev" origin "refs/heads/orph $(git -C "$S/dev" rev-parse orph) refs/heads/orph $ZERO40"
check "15 orphan branch with records commit blocks" 1 $rc "$S/err" "records/orphan.txt"
git -C "$S/dev" checkout -q --orphan orph2
git -C "$S/dev" rm -rq --cached .
rm -rf "$S/dev/records" "$S/dev/only-src.txt"
commit_file "$S/dev" only-src.txt s "orphan without records"
hook "$S/dev" origin "refs/heads/orph2 $(git -C "$S/dev" rev-parse orph2) refs/heads/orph2 $ZERO40"
check "16 records-free orphan allowed (contributes no records commits)" 0 $rc

# ---- 17-18: a local branch literally named origin/main cannot shadow
git clone -q "$S/origin.git" "$S/dev4" 2>/dev/null
git -C "$S/dev4" checkout -qb evil
commit_file "$S/dev4" records/amb.txt x "records on evil"
E=$(git -C "$S/dev4" rev-parse evil)
git -C "$S/dev4" branch origin/main "$E"    # refs/heads/origin/main shadow
hook "$S/dev4" origin "refs/heads/evil $E refs/heads/evil $TIP"
check "17 refs/heads/origin-main shadow ignored, blocks" 1 $rc "$S/err" "records/amb.txt"
printf '%s\n' "refs/heads/evil $E refs/heads/evil $TIP" \
    | (cd "$S/dev4" && THESIS_ALLOW_RECORDS_PUSH=1 sh "$HOOK" origin x 2>"$S/err")
check "18 shadow + break-glass allows with notice" 0 $? "$S/err" "THESIS_ALLOW_RECORDS_PUSH=1"

# ---- 19: refspec-less remote — the explicit-refspec fetch must correct a
# forged tracking ref even when remote.origin.fetch is absent
git clone -q "$S/origin.git" "$S/dev5" 2>/dev/null
git -C "$S/dev5" config --unset-all remote.origin.fetch
git -C "$S/dev5" checkout -qb sneak
commit_file "$S/dev5" records/refspec.txt r "records on sneak"
SN=$(git -C "$S/dev5" rev-parse sneak)
git -C "$S/dev5" update-ref refs/remotes/origin/main "$SN"     # forge
hook "$S/dev5" origin "refs/heads/sneak $SN refs/heads/sneak $ZERO40"
check "19 refspec-less remote: fetch repins comparator, blocks" 1 $rc "$S/err" "records/refspec.txt"
# the comparator is fetched from the destination and resolved to an
# immutable id; the user's (here forged) tracking ref is neither trusted
# nor rewritten, and no guard ref is left behind
if [ "$(git -C "$S/dev5" rev-parse refs/remotes/origin/main)" = "$SN" ] &&
    [ -z "$(git -C "$S/dev5" for-each-ref --format='%(refname)' 'refs/prepush-guard/*')" ]; then
    echo "PASS 19b forged tracking ref neither trusted nor rewritten"
    pass=$((pass+1))
else
    echo "FAIL 19b tracking ref altered or guard ref left behind"; fail=$((fail+1))
fi

# ---- 20-21: fork topology — origin cannot vouch for another remote
git clone -q --bare "$S/origin.git" "$S/fork.git" 2>/dev/null
git clone -q "$S/fork.git" "$S/dev6" 2>/dev/null
commit_file "$S/dev6" records/from-fork.txt f "unattested fork-main record"
git -C "$S/dev6" push -q origin HEAD:main                      # fork main only
git -C "$S/dev6" fetch -q origin
git -C "$S/dev6" checkout -qb feat2 origin/main
commit_file "$S/dev6" src/e.txt e "src on feat2"
F2=$(git -C "$S/dev6" rev-parse feat2)
hook "$S/dev6" upstream "refs/heads/feat2 $F2 refs/heads/feat2 $TIP"
check "20 push to non-origin remote uses endpoint range, blocks" 1 $rc "$S/err" "records/from-fork.txt"
hook "$S/dev6" upstream "refs/heads/feat2 $F2 refs/heads/feat2 $ZERO40"
check "21 new ref on non-origin remote refuses as unverifiable" 1 $rc "$S/err" "cannot verify"

# ---- 22: an unreadable range fails closed, not open
git clone -q "$S/origin.git" "$S/dev7" 2>/dev/null
git -C "$S/dev7" checkout -qb broke
commit_file "$S/dev7" src/f.txt f "src on broke"
B7=$(git -C "$S/dev7" rev-parse broke)
MISSING=$(git -C "$S/dev7" rev-parse "$TIP^{tree}")
OBJ="$S/dev7/.git/objects/$(echo "$MISSING" | cut -c1-2)/$(echo "$MISSING" | cut -c3-)"
if [ -f "$OBJ" ]; then
    rm -f "$OBJ"
    hook "$S/dev7" origin "refs/heads/broke $B7 refs/heads/broke $TIP"
    check "22 unreadable history refuses as unverifiable" 1 $rc "$S/err" "cannot verify"
else
    echo "SKIP 22 (base tree object stored in a pack; corruption probe n/a)"
fi

# ---- 23: refs/replace cannot dress up a records commit
git clone -q "$S/origin.git" "$S/dev8" 2>/dev/null
git -C "$S/dev8" checkout -qb cloak
commit_file "$S/dev8" records/cloaked.txt c "records on cloak"
CK=$(git -C "$S/dev8" rev-parse cloak)
git -C "$S/dev8" checkout -q -b decoy "$TIP"
commit_file "$S/dev8" src/g.txt g "clean decoy"
git -C "$S/dev8" replace "$CK" "$(git -C "$S/dev8" rev-parse decoy)"
git -C "$S/dev8" checkout -q cloak
hook "$S/dev8" origin "refs/heads/cloak $CK refs/heads/cloak $TIP"
check "23 replacement ref ignored, records commit still blocks" 1 $rc "$S/err" "records/cloaked.txt"

# ---- 24: multi-ref pushes — one bad ref fails the push and is named
hook "$S/dev" origin \
    "refs/heads/feat $LOCAL refs/heads/feat $OLD_REMOTE" \
    "refs/heads/evilref $LOCAL2 refs/heads/evilref $OLD_REMOTE"
check "24 mixed multi-ref push blocks and names the records commit" 1 $rc "$S/err" "records/evil.txt"

# ---- 25-27: end-to-end through core.hooksPath with real pushes
mkdir -p "$S/hooks"; cp "$HOOK" "$S/hooks/pre-push"; chmod +x "$S/hooks/pre-push"
git -C "$S/dev" config core.hooksPath "$S/hooks"
git -C "$S/dev" checkout -q feat
(cd "$S/dev" && git push -q --force-with-lease origin feat) 2>"$S/err"
check "25 real push of rebased branch succeeds" 0 $?
commit_file "$S/dev" records/evil2.txt e2 "records again"
(cd "$S/dev" && git push -q origin feat) 2>"$S/err"
check "26 real push with records commit refused" 1 $? "$S/err" "BLOCKED"
if [ "$(git -C "$S/origin.git" rev-parse refs/heads/feat)" = "$LOCAL" ]; then
    echo "PASS 26b remote ref unmoved after refusal"; pass=$((pass+1))
else
    echo "FAIL 26b remote ref moved despite refusal"; fail=$((fail+1))
fi
(cd "$S/dev" && THESIS_ALLOW_RECORDS_PUSH=1 git push -q origin feat) 2>"$S/err"
check "27 real push with break-glass succeeds" 0 $? "$S/err" "THESIS_ALLOW_RECORDS_PUSH=1"

# ---- 28-29: merge commits — update-merges are records no-ops, evil
# merges that resolve to content matching no parent still block (the
# provenance audit's #73 exemption rule, mirrored)
git clone -q "$S/origin.git" "$S/dev9" 2>/dev/null
git -C "$S/dev9" checkout -qb um "$INIT"
commit_file "$S/dev9" src/h.txt h "src on um"
git -C "$S/dev9" merge -q --no-edit origin/main
hook "$S/dev9" origin "refs/heads/um $(git -C "$S/dev9" rev-parse um) refs/heads/um $ZERO40"
check "28 update-merge over recorder commits allowed (no-op merge)" 0 $rc
git -C "$S/dev9" checkout -qb em "$INIT"
commit_file "$S/dev9" src/i.txt i "src on em"
git -C "$S/dev9" merge --no-commit --no-edit -q origin/main >/dev/null 2>&1
mkdir -p "$S/dev9/records"
echo evil > "$S/dev9/records/evil-merge.txt"
git -C "$S/dev9" add -A
git -C "$S/dev9" commit -qm "evil merge writes records"
hook "$S/dev9" origin "refs/heads/em $(git -C "$S/dev9" rev-parse em) refs/heads/em $ZERO40"
check "29 evil merge resolving to new records content blocks" 1 $rc "$S/err" "records/evil-merge.txt"

# ---- 30-33: the merge exemption admits only already-published content
# (the audit's in-scope-parent rule; round-3 adversarial findings)
git clone -q "$S/origin.git" "$S/dev10" 2>/dev/null
MTIP=$(git -C "$S/dev10" rev-parse origin/main)
# stale-parent swap: a merge whose records tree matches a STALE local
# parent reverts main's records while looking TREESAME to a parent
git -C "$S/dev10" checkout -qb stale "$INIT"
commit_file "$S/dev10" src/j.txt j "src on stale base"
STALE=$(git -C "$S/dev10" rev-parse stale)
SWAP=$(git -C "$S/dev10" commit-tree "$STALE^{tree}" -p "$MTIP" -p "$STALE" \
    -m "fast-forward merge carrying the stale records tree")
hook "$S/dev10" origin "refs/heads/main $SWAP refs/heads/main $MTIP"
# blocked as a rollback before content closure is reached: the merge
# carries the stale parent's records over destination main, a published
# parent with different records, so no parent may vouch for it
check "30 stale-parent swap merge on main blocks (rollback)" 1 $rc "$S/err" "carrying the stale records tree"
# two exempt merges: both vouched by ALREADY-PUBLISHED parents, adding
# then removing a record so the endpoints agree (sol round-4 HIGH 1 — the
# earlier fixture used an unpublished carrier and never exercised this)
PUBPAY=$(git -C "$S/dev10" rev-parse "$MTIP")
hook "$S/dev10" origin "refs/heads/main $MTIP refs/heads/main $INIT"
ADD=$(git -C "$S/dev10" commit-tree "$PUBPAY^{tree}" -p "$INIT" -p "$PUBPAY" \
    -m "merge resurrecting a published records state")
DEL=$(git -C "$S/dev10" commit-tree "$INIT^{tree}" -p "$ADD" -p "$INIT" \
    -m "merge restoring the base records state")
hook "$S/dev10" origin "refs/heads/main $DEL refs/heads/main $INIT"
check "31 two merges vouched by a pre-epoch parent block (in-scope rule)" 1 $rc "$S/err" "restoring the base records state"
# the legitimate shape this exemption exists for still passes
git -C "$S/dev10" checkout -qb legit "$INIT"
commit_file "$S/dev10" src/k.txt k "src on legit"
git -C "$S/dev10" merge -q --no-edit origin/main
hook "$S/dev10" origin "refs/heads/legit $(git -C "$S/dev10" rev-parse legit) refs/heads/legit $ZERO40"
check "32 update-merge with main still exempt (published parent)" 0 $rc
# force-rewinding main to an ancestor changes records with an empty walk
git -C "$S/dev10" checkout -q -B rewind "$INIT"
hook "$S/dev10" origin "refs/heads/main $INIT refs/heads/main $MTIP"
check "33 force rewind of main blocks (content closure)" 1 $rc "$S/err" "cannot verify"

# ---- 34-35: a new main needs a comparator from its own destination
git init -q --bare "$S/empty.git"
git -C "$S/empty.git" symbolic-ref HEAD refs/heads/main
hook_url "$S/dev10" upstream "$S/empty.git" \
    "refs/heads/main $MTIP refs/heads/main $ZERO40"
check "34 new main on another remote refuses (no comparator there)" 1 $rc "$S/err" "cannot verify"
# origin's own main is a valid comparator for a new main only when the
# pinned fetch succeeds; a dead origin refuses rather than trusting it
git clone -q "$S/origin.git" "$S/dev11" 2>/dev/null
git -C "$S/dev11" remote set-url origin "$S/does-not-exist.git"
hook "$S/dev11" origin "refs/heads/main $MTIP refs/heads/main $ZERO40"
check "35 new main with unreachable origin refuses" 1 $rc "$S/err" "cannot verify"

# ---- 36: remote.origin.pushurl sends elsewhere — origin cannot vouch
git clone -q "$S/origin.git" "$S/dev12" 2>/dev/null
git -C "$S/dev12" checkout -qb pu
commit_file "$S/dev12" src/l.txt l "src on pu"
PU=$(git -C "$S/dev12" rev-parse pu)
hook_url "$S/dev12" origin "$S/victim.git" \
    "refs/heads/pu $PU refs/heads/pu $INIT"
check "36 differing push URL falls back to endpoint range, blocks" 1 $rc "$S/err" "records/r1.txt"

# ---- 37: a shallow clone can walk successfully with missing history
git clone -q --depth 1 "file://$S/origin.git" "$S/dev13" 2>/dev/null
if [ "$(git -C "$S/dev13" rev-parse --is-shallow-repository)" = "true" ]; then
    commit_file "$S/dev13" src/m.txt m "src on shallow"
    hook "$S/dev13" origin \
        "refs/heads/main $(git -C "$S/dev13" rev-parse HEAD) refs/heads/main $MTIP"
    check "37 shallow repository refuses as unverifiable" 1 $rc "$S/err" "shallow"
else
    echo "FAIL 37 could not create a shallow clone to test"; fail=$((fail+1))
fi

# ---- 38: a legacy graft must not rewrite the walk
git clone -q "$S/origin.git" "$S/dev14" 2>/dev/null
git -C "$S/dev14" checkout -qb graft
commit_file "$S/dev14" records/grafted.txt g "records via graft"
GR=$(git -C "$S/dev14" rev-parse graft)
mkdir -p "$S/dev14/.git/info"
echo "$GR $INIT" > "$S/dev14/.git/info/grafts"
hook "$S/dev14" origin "refs/heads/graft $GR refs/heads/graft $MTIP"
check "38 legacy graft ignored, records commit still blocks" 1 $rc "$S/err" "records/grafted.txt"

# ---- 39: every offending commit is named, not truncated away by paths
git clone -q "$S/origin.git" "$S/dev15" 2>/dev/null
git -C "$S/dev15" checkout -qb wide
commit_file "$S/dev15" records/older.txt o "older offender"
OLDER=$(git -C "$S/dev15" rev-parse --short wide)
mkdir -p "$S/dev15/records"
for i in 1 2 3 4 5 6 7 8 9 10; do echo "$i" > "$S/dev15/records/w$i.txt"; done
git -C "$S/dev15" add -A
git -C "$S/dev15" commit -qm "newest wide offender"
hook "$S/dev15" origin \
    "refs/heads/wide $(git -C "$S/dev15" rev-parse wide) refs/heads/wide $MTIP"
check "39 older offender still named beside a wide newest commit" 1 $rc "$S/err" "$OLDER"

# ---- 40-41: a pre-epoch parent cannot vouch, on main or on a branch
# (sol round-4 HIGH 1 / MEDIUM 2: "ancestor of the comparator" alone let a
# merge resurrect an ancient records state the audit would still demand)
git clone -q "$S/origin.git" "$S/dev16" 2>/dev/null
PRE=$(git -C "$S/dev16" rev-parse "$INIT")
ANCIENT=$(git -C "$S/dev16" commit-tree "$PRE^{tree}" -p "$MTIP" -p "$PRE" \
    -m "merge resurrecting the pre-epoch records state")
hook "$S/dev16" origin "refs/heads/main $ANCIENT refs/heads/main $MTIP"
check "40 pre-epoch parent cannot exempt a merge on main" 1 $rc "$S/err" "resurrecting the pre-epoch records state"
hook "$S/dev16" origin "refs/heads/topic $ANCIENT refs/heads/topic $ZERO40"
check "41 pre-epoch parent cannot exempt a merge on a branch" 1 $rc "$S/err" "resurrecting the pre-epoch records state"

# ---- 42-43: equivalent spellings of the same destination are not a
# false positive (sol round-4 MEDIUM 3 — the comparator is fetched from
# the destination, so no URL string comparison is involved)
git clone -q "$S/origin.git" "$S/dev17" 2>/dev/null
git -C "$S/dev17" checkout -qb equiv
commit_file "$S/dev17" src/n.txt n "src on equiv"
EQ=$(git -C "$S/dev17" rev-parse equiv)
hook_url "$S/dev17" origin "file://$S/origin.git" \
    "refs/heads/equiv $EQ refs/heads/equiv $ZERO40"
check "42 file:// spelling of the same destination allowed" 0 $rc
commit_file "$S/dev17" records/eq.txt e "records on equiv"
hook_url "$S/dev17" origin "file://$S/origin.git" \
    "refs/heads/equiv $(git -C "$S/dev17" rev-parse equiv) refs/heads/equiv $ZERO40"
check "43 same destination still blocks a records commit" 1 $rc "$S/err" "records/eq.txt"

# ---- 44-45: a nested insteadOf must not redirect the comparator
# (sol round-5 HIGH 1: git already resolved the destination; feeding it
# back through fetch rewrites it a second time)
git init -q --bare "$S/decoy.git"
git -C "$S/decoy.git" symbolic-ref HEAD refs/heads/main
git clone -q "$S/origin.git" "$S/seed2" 2>/dev/null
commit_file "$S/seed2" records/decoy.txt d "decoy main carries the record"
git -C "$S/seed2" push -q "$S/decoy.git" HEAD:main
git clone -q "$S/origin.git" "$S/dev18" 2>/dev/null
git -C "$S/dev18" checkout -qb rewrite
commit_file "$S/dev18" records/decoy.txt d "same record, pushed from here"
RW=$(git -C "$S/dev18" rev-parse rewrite)
# without a rewrite rule the destination's own main is the comparator
hook_url "$S/dev18" origin "$S/origin.git" \
    "refs/heads/rewrite $RW refs/heads/rewrite $TIP"
check "44 records commit blocks against the real destination" 1 $rc "$S/err" "records/decoy.txt"
# with one, fetching the destination string would land on the decoy whose
# main already holds the record: the comparator must be refused
git -C "$S/dev18" config "url.$S/decoy.git.insteadOf" "$S/origin.git"
hook_url "$S/dev18" origin "$S/origin.git" \
    "refs/heads/rewrite $RW refs/heads/rewrite $TIP"
check "45 nested insteadOf cannot vouch, falls back to endpoint" 1 $rc "$S/err" "records/decoy.txt"
git -C "$S/dev18" config --unset "url.$S/decoy.git.insteadOf"

# ---- 46: the epoch comes from the pushed graph, not ambient HEAD
# (sol round-5 HIGH 2: a checkout predating the verifier disabled the
# in-scope test for every ref pushed from it)
git clone -q "$S/origin.git" "$S/dev19" 2>/dev/null
PRE2=$(git -C "$S/dev19" rev-parse "$INIT")
ANC2=$(git -C "$S/dev19" commit-tree "$PRE2^{tree}" -p "$MTIP" -p "$PRE2" \
    -m "pre-epoch resurrection pushed from an ancient checkout")
git -C "$S/dev19" checkout -q --detach "$PRE2^" 2>/dev/null ||
    git -C "$S/dev19" checkout -q --detach "$PRE2"
hook "$S/dev19" origin "refs/heads/main $ANC2 refs/heads/main $MTIP"
check "46 epoch read from the pushed ref, not the checkout" 1 $rc "$S/err" "pre-epoch resurrection"

# ---- 47: the comparator is an immutable id, not a shared mutable ref
# (sol round-5 HIGH 3: concurrent pushes shared one ref name)
git clone -q "$S/origin.git" "$S/dev20" 2>/dev/null
git -C "$S/dev20" checkout -qb conc
commit_file "$S/dev20" records/conc.txt c "records on conc"
CC=$(git -C "$S/dev20" rev-parse conc)
# the old shared comparator ref name, pre-pointed at the records commit:
# a concurrent invocation's ref must never be consulted
git -C "$S/dev20" update-ref refs/prepush-guard/destination-main "$CC"
hook "$S/dev20" origin "refs/heads/conc $CC refs/heads/conc $ZERO40"
check "47 a pre-existing shared guard ref cannot vouch" 1 $rc "$S/err" "records/conc.txt"
if [ -z "$(git -C "$S/dev20" for-each-ref --format='%(refname)' 'refs/prepush-guard/tmp-*')" ]; then
    echo "PASS 47b per-invocation comparator ref cleaned up"; pass=$((pass+1))
else
    echo "FAIL 47b comparator ref left behind"; fail=$((fail+1))
fi

# ---- 48-51: a branch that merged main forward, then merged a side branch
# lagging main's records: the second merge's records tree is main's, but
# its same-tree parent is a branch commit main does not contain. Hit
# 2026-09-22 (thesis#270 merging #269). The content is published, through
# the commit that last set it, so the merge is exempt; a tree that merely
# EQUALS main's, set by an unpublished commit, still is not.
git clone -q "$S/origin.git" "$S/dev21" 2>/dev/null
git -C "$S/dev21" checkout -qb fwd "$INIT"
commit_file "$S/dev21" src/o.txt o "src on fwd"
git -C "$S/dev21" merge -q --no-edit origin/main            # forward merge
FWD=$(git -C "$S/dev21" rev-parse fwd)
git -C "$S/dev21" checkout -qb lag "$INIT"
commit_file "$S/dev21" src/p.txt p "src on lag (records lag main)"
git -C "$S/dev21" checkout -q fwd
git -C "$S/dev21" merge -q --no-edit lag                    # side merge
FWD2=$(git -C "$S/dev21" rev-parse fwd)
if [ "$(git -C "$S/dev21" rev-parse "$FWD2:records")" != \
    "$(git -C "$S/dev21" rev-parse "$MTIP:records")" ]; then
    echo "FAIL 48 fixture: side merge did not keep main's records tree"; fail=$((fail+1))
fi
hook "$S/dev21" origin "refs/heads/fwd $FWD2 refs/heads/fwd $FWD"
check "48 side merge after a forward merge allowed (existing ref)" 0 $rc
hook "$S/dev21" origin "refs/heads/fwd $FWD2 refs/heads/fwd $ZERO40"
check "49 side merge after a forward merge allowed (new ref)" 0 $rc
# the same shape with the branch's OWN records commit underneath: the
# side merge is TREESAME to that parent, whose content was never published
git -C "$S/dev21" checkout -qb own "$FWD"
commit_file "$S/dev21" records/own.txt own "records on own"
git -C "$S/dev21" merge -q --no-edit -m "side merge over own records" lag
hook "$S/dev21" origin "refs/heads/own $(git -C "$S/dev21" rev-parse own) refs/heads/own $ZERO40"
check "50 side merge over an unpublished records commit blocks" 1 $rc "$S/err" "records/own.txt"
check "50b the side merge itself is named, not only the records commit" 1 $rc "$S/err" "side merge over own records"
# a records tree that merely equals main's, set by an unpublished commit
git -C "$S/dev21" checkout -qb replica "$INIT"
git -C "$S/dev21" checkout -q "$MTIP" -- records
git -C "$S/dev21" commit -qm "re-create main's records by hand"
REPLICA=$(git -C "$S/dev21" rev-parse replica)
if [ "$(git -C "$S/dev21" rev-parse "$REPLICA:records")" != \
    "$(git -C "$S/dev21" rev-parse "$MTIP:records")" ]; then
    echo "FAIL 51 fixture: replica does not match main's records tree"; fail=$((fail+1))
fi
git -C "$S/dev21" merge -q --no-edit -m "side merge over the hand-made copy" lag
hook "$S/dev21" origin "refs/heads/replica $(git -C "$S/dev21" rev-parse replica) refs/heads/replica $ZERO40"
check "51 merge over a hand-made copy of main's records blocks" 1 $rc "$S/err" "re-create main's records by hand"
check "51b that merge is named too (its parent's setter is unpublished)" 1 $rc "$S/err" "side merge over the hand-made copy"

# ---- 52-53: a rollback of a PUBLISHED records state on a branch push.
# Main has two post-epoch records states; a branch off the older one
# carries it over the newer main (`git merge -s ours main`, or a literal
# stale parent). Content closure never sees a branch push, and the GitHub
# merge button would then delete the newer records from main. The
# published-setter relaxation must not admit the first shape, and the
# second was a pre-existing hole (the old hook exempted it).
commit_file "$S/seed" records/r3.txt r3 "attested record 3"
git -C "$S/seed" push -q origin main
MTIP2=$(git -C "$S/seed" rev-parse HEAD)
git clone -q "$S/origin.git" "$S/dev22" 2>/dev/null
git -C "$S/dev22" checkout -qb roll "$MTIP"                  # older post-epoch state
commit_file "$S/dev22" src/q.txt q "src on roll"
ROLL=$(git -C "$S/dev22" rev-parse roll)
OURS=$(git -C "$S/dev22" commit-tree "$ROLL^{tree}" -p "$ROLL" -p "$MTIP2" \
    -m "merge main, discarding records/r3.txt")
hook "$S/dev22" origin "refs/heads/roll $OURS refs/heads/roll $ZERO40"
check "52 ours-style merge discarding main's newer records blocks" 1 $rc "$S/err" "discarding records/r3.txt"
LIT=$(git -C "$S/dev22" commit-tree "$MTIP^{tree}" -p "$MTIP2" -p "$MTIP" \
    -m "literal stale parent carried over main")
hook "$S/dev22" origin "refs/heads/roll $LIT refs/heads/roll $ZERO40"
check "53 literal stale published parent over main blocks" 1 $rc "$S/err" "literal stale parent carried over main"
# the same branch merging main forward properly is still a no-op
git -C "$S/dev22" merge -q --no-edit origin/main
hook "$S/dev22" origin "refs/heads/roll $(git -C "$S/dev22" rev-parse roll) refs/heads/roll $ZERO40"
check "54 an honest forward merge on the same branch still allowed" 0 $rc

# ---- 55-59: rollbacks reached through UNPUBLISHED parents, and honest
# merges that keep the NEWER of two published states (2026-09-22 review
# of #280, F1 and F2). A parent that is a src-only child of the newer main
# carries main's records without being published itself; keeping an older
# published state over it is the same rollback as 52/53 and must block,
# also as an octopus and under a later merge. A merge that keeps the newer
# state over a parent carrying an older published one is not a rollback,
# whether the older parent is a stale main commit or a lagging side branch
# main has since absorbed.
git clone -q "$S/origin.git" "$S/dev23" 2>/dev/null
git -C "$S/dev23" checkout -qb wrap "$MTIP"                  # older published state
commit_file "$S/dev23" src/r.txt r "src on wrap"
P=$(git -C "$S/dev23" rev-parse wrap)
git -C "$S/dev23" checkout -qb newer "$MTIP2"                # child of newer main
commit_file "$S/dev23" src/s.txt s "src on newer"
Q=$(git -C "$S/dev23" rev-parse newer)
git -C "$S/dev23" checkout -qb newer2 "$MTIP2"
commit_file "$S/dev23" src/t.txt t "src on newer2"
Q2=$(git -C "$S/dev23" rev-parse newer2)
git -C "$S/dev23" checkout -qb lag2 "$INIT"
commit_file "$S/dev23" src/u.txt u "src on lag2 (records lag main)"
L=$(git -C "$S/dev23" rev-parse lag2)
WRAP=$(git -C "$S/dev23" commit-tree "$P^{tree}" -p "$P" -p "$Q" \
    -m "wrapped rollback over an unpublished child of main")
hook "$S/dev23" origin "refs/heads/wrap $WRAP refs/heads/wrap $ZERO40"
check "55 rollback over an unpublished child of newer main blocks" 1 $rc "$S/err" "wrapped rollback"
walked "$S/dev23" "$MTIP2" "$WRAP" "$WRAP"
check "55w the wrapped rollback is in the walked range" 0 $?
OCTO=$(git -C "$S/dev23" commit-tree "$P^{tree}" -p "$P" -p "$Q" -p "$Q2" \
    -m "octopus rollback over two unpublished children of main")
hook "$S/dev23" origin "refs/heads/wrap $OCTO refs/heads/wrap $ZERO40"
check "56 octopus rollback over unpublished children blocks" 1 $rc "$S/err" "octopus rollback"
ABOVE=$(git -C "$S/dev23" commit-tree "$P^{tree}" -p "$WRAP" -p "$L" \
    -m "side merge above the wrapped rollback")
hook "$S/dev23" origin "refs/heads/wrap $ABOVE refs/heads/wrap $ZERO40"
check "57 a later merge does not launder the wrapped rollback" 1 $rc "$S/err" "wrapped rollback"
GOOD=$(git -C "$S/dev23" commit-tree "$MTIP2^{tree}" -p "$MTIP" -p "$MTIP2" \
    -m "honest no-ff merge of newer main from an older main commit")
hook "$S/dev23" origin "refs/heads/wrap $GOOD refs/heads/wrap $ZERO40"
check "58 keeping the newer published state over an older one allowed" 0 $rc
# a compatibility control only: git does not walk this merge at all
walked "$S/dev23" "$MTIP2" "$GOOD" "$GOOD"
check "58w that merge is outside the walked range" 1 $?
git -C "$S/dev23" checkout -qb side "$INIT"
commit_file "$S/dev23" src/v.txt v "src on side"
git -C "$S/dev23" merge -q --no-edit origin/main            # forward merge
git -C "$S/dev23" merge -q --no-edit lag2                   # side merge
SIDE=$(git -C "$S/dev23" rev-parse side)
if [ "$(git -C "$S/dev23" rev-parse "$SIDE:records")" != \
    "$(git -C "$S/dev23" rev-parse "$MTIP2:records")" ]; then
    echo "FAIL 59 fixture: side merge did not keep main's records tree"; fail=$((fail+1))
fi
hook "$S/dev23" origin "refs/heads/side $SIDE refs/heads/side $ZERO40"
check "59 side merge of a lagging branch allowed" 0 $rc
walked "$S/dev23" "$MTIP2" "$SIDE" "$SIDE"
check "59w that side merge is in the walked range" 0 $?
git -C "$S/dev23" checkout -q -B main origin/main
git -C "$S/dev23" merge -q --no-edit lag2                   # main absorbs the side branch
git -C "$S/dev23" push -q origin main
if [ "$(git -C "$S/dev23" rev-parse "origin/main:records")" != \
    "$(git -C "$S/dev23" rev-parse "$MTIP2:records")" ]; then
    echo "FAIL 59b fixture: absorbing the side branch changed main's records"; fail=$((fail+1))
fi
hook "$S/dev23" origin "refs/heads/side $SIDE refs/heads/side $ZERO40"
check "59b still allowed once main has absorbed the side branch" 0 $rc
walked "$S/dev23" "$(git -C "$S/dev23" rev-parse origin/main)" "$SIDE" "$SIDE"
check "59bw once absorbed, that side merge is outside the walked range" 1 $?

# ---- 60-62: the newest published state a merge contains decides, not
# which commit last set a parent's records (2026-09-23 review of #280,
# N1-N3). 60: main restores an earlier records state; a branch that took
# that restoration and then merges a child of the state main discarded
# keeps main's current records, an honest merge the walk does visit. 61:
# a published merge chose b over a; a branch re-selects a over it, with
# the two states' setters not ancestor-related. 62: a published merge
# deleted the records; a branch resurrects them over it.
fresh_origin o60
commit_file "$S/o60" records/a.txt a "records a"
A60=$(git -C "$S/o60" rev-parse HEAD)
commit_file "$S/o60" records/b.txt b "records a+b"
B60=$(git -C "$S/o60" rev-parse HEAD)
git -C "$S/o60" rm -q records/b.txt
git -C "$S/o60" commit -qm "restore records a"
C60=$(git -C "$S/o60" rev-parse HEAD)
git -C "$S/o60" push -q origin HEAD:main
git -C "$S/o60" checkout -qb p60 "$A60"
commit_file "$S/o60" src/p.txt p "src on p60"
git -C "$S/o60" merge -q --no-edit "$C60"
git -C "$S/o60" checkout -qb q60 "$B60"
commit_file "$S/o60" src/q.txt q "src on q60"
git -C "$S/o60" checkout -q p60
git -C "$S/o60" merge -q --no-edit -m "honest merge keeping main's restored records" q60
M60=$(git -C "$S/o60" rev-parse HEAD)
if [ "$(git -C "$S/o60" rev-parse "$M60:records")" != \
    "$(git -C "$S/o60" rev-parse "$C60:records")" ]; then
    echo "FAIL 60 fixture: the merge did not keep main's records"; fail=$((fail+1))
fi
walked "$S/o60" "$C60" "$M60" "$M60"
check "60w that merge is in the walked range" 0 $?
hook "$S/o60" origin "refs/heads/p60 $M60 refs/heads/p60 $ZERO40"
check "60 keeping main's restored records over an older state allowed" 0 $rc

fresh_origin o61
E61=$(git -C "$S/o61" rev-parse HEAD)
commit_file "$S/o61" records/a.txt a "records a"
A61=$(git -C "$S/o61" rev-parse HEAD)
git -C "$S/o61" checkout -qb b61 "$E61"
commit_file "$S/o61" records/b.txt b "records b"
B61=$(git -C "$S/o61" rev-parse HEAD)
K61=$(git -C "$S/o61" commit-tree "$B61^{tree}" -p "$A61" -p "$B61" \
    -m "published merge choosing b over a")
git -C "$S/o61" push -q origin "$K61:refs/heads/main"
git -C "$S/o61" checkout -qb p61 "$A61"
commit_file "$S/o61" src/p.txt p "src on p61"
P61=$(git -C "$S/o61" rev-parse HEAD)
M61=$(git -C "$S/o61" commit-tree "$P61^{tree}" -p "$P61" -p "$K61" \
    -m "re-selecting a over the published choice of b")
hook "$S/o61" origin "refs/heads/p61 $M61 refs/heads/p61 $ZERO40"
check "61 re-selecting a state a published merge discarded blocks" 1 $rc "$S/err" "re-selecting a over"

fresh_origin o62
E62=$(git -C "$S/o62" rev-parse HEAD)
commit_file "$S/o62" records/a.txt a "records a"
A62=$(git -C "$S/o62" rev-parse HEAD)
git -C "$S/o62" checkout -qb n62 "$E62"
commit_file "$S/o62" src/n.txt n "src on n62"
N62=$(git -C "$S/o62" rev-parse HEAD)
K62=$(git -C "$S/o62" commit-tree "$N62^{tree}" -p "$A62" -p "$N62" \
    -m "published merge deleting the records")
git -C "$S/o62" push -q origin "$K62:refs/heads/main"
git -C "$S/o62" checkout -qb p62 "$A62"
commit_file "$S/o62" src/p.txt p "src on p62"
P62=$(git -C "$S/o62" rev-parse HEAD)
git -C "$S/o62" checkout -qb q62 "$K62"
commit_file "$S/o62" src/q.txt q "src on q62"
Q62=$(git -C "$S/o62" rev-parse HEAD)
M62=$(git -C "$S/o62" commit-tree "$P62^{tree}" -p "$P62" -p "$Q62" \
    -m "resurrecting records a published merge deleted")
hook "$S/o62" origin "refs/heads/p62 $M62 refs/heads/p62 $ZERO40"
check "62 resurrecting records a published merge deleted blocks" 1 $rc "$S/err" "resurrecting records"

echo
echo "== $pass passed, $fail failed =="
exit $((fail > 0))
