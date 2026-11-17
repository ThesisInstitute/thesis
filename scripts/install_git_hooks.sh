#!/bin/sh
# Install, check, or remove this clone's pre-push dispatcher.
#
#   sh scripts/install_git_hooks.sh              install or update, then check
#   sh scripts/install_git_hooks.sh --check      report only; exit 1 unless
#                                                every worktree's push runs
#                                                that worktree's own guard
#   sh scripts/install_git_hooks.sh --uninstall  remove the dispatcher and put
#                                                back core.hooksPath=.githooks
#
# The invariant: the dispatcher (scripts/pre_push_dispatch.sh) sits in the
# clone's shared hooks directory, $(git rev-parse --git-common-dir)/hooks,
# and core.hooksPath is unset at every scope in every worktree, so git runs
# the dispatcher for every push and the dispatcher runs the pushing
# checkout's own .githooks/pre-push.
#
# Why not `git config core.hooksPath .githooks`: the Claude desktop app
# copies the base repo's core.hooksPath into every worktree it creates or
# reuses, resolved to an absolute path (the main checkout's .githooks,
# from whatever branch the main checkout has out), and `git worktree add`
# copies a worktree's config.worktree into the worktree it creates. With
# nothing set there is nothing to copy, and the app clears a worktree's
# core.hooksPath instead, because the shared hooks directory holds a real
# hook. See AGENTS.md, "The records-path guard".
set -u
set -f
MARKER=thesis-pre-push-dispatcher
NL='
'
OIFS=$IFS

die() { echo "install_git_hooks: $*" >&2; exit 2; }

top=$(git rev-parse --show-toplevel 2>/dev/null) || die "not in a git work tree"
cd "$top" || die "cannot cd to $top"
common=$(cd "$(git rev-parse --git-common-dir)" 2>/dev/null && pwd -P)
[ -n "$common" ] || die "no git common dir"
shared="$common/hooks"
src="$top/scripts/pre_push_dispatch.sh"

worktrees() { git worktree list --porcelain | sed -n 's/^worktree //p'; }

# setting <worktree>: every core.hooksPath git would apply there, with scope
setting() { git -C "$1" config --show-scope --get-all core.hooksPath 2>/dev/null |
    tr '\t' ' '; }

check() {
    bad=0
    for scope in global system local; do
        v=$(git config "--$scope" --get-all core.hooksPath 2>/dev/null)
        if [ -n "$v" ]; then
            echo "FAIL  $scope core.hooksPath=$v (must be unset)"
            bad=1
        fi
    done
    if ! grep -q "$MARKER" "$shared/pre-push" 2>/dev/null; then
        echo "FAIL  $shared/pre-push is not the dispatcher; run the installer"
        bad=1
    elif [ ! -x "$shared/pre-push" ]; then
        echo "FAIL  $shared/pre-push is not executable"
        bad=1
    elif [ -f "$src" ] && ! cmp -s "$src" "$shared/pre-push"; then
        echo "note  installed dispatcher differs from $src;"
        echo "      rerun the installer from a current checkout"
    fi
    IFS=$NL
    for wt in $(worktrees); do
        IFS=$OIFS
        if [ ! -d "$wt" ]; then
            echo "skip  $wt (directory missing; git worktree prune)"
            continue
        fi
        # global/system/local values were reported once, above
        s=$(setting "$wt" | grep '^worktree ')
        if [ -n "$s" ]; then
            echo "FAIL  $wt: core.hooksPath set ($s);"
            echo "      its pushes bypass the dispatcher (the installer removes it)"
            bad=1
        elif [ ! -f "$wt/.githooks/pre-push" ]; then
            echo "note  $wt has no .githooks/pre-push; its pushes are refused"
        fi
    done
    IFS=$OIFS
    [ "$bad" = 0 ] && echo "ok    every worktree of $common runs its own guard"
    return "$bad"
}

install() {
    [ -f "$src" ] || die "$src missing (run this from a current checkout)"
    for scope in global system; do
        v=$(git config "--$scope" --get-all core.hooksPath 2>/dev/null)
        [ -z "$v" ] || die "$scope core.hooksPath=$v overrides every clone's \
hooks directory, so the dispatcher would never run; remove it first"
    done
    if [ -e "$shared/pre-push" ] && ! grep -q "$MARKER" "$shared/pre-push"; then
        die "$shared/pre-push exists and is not the dispatcher; not replacing it"
    fi
    local_v=$(git config --local --get-all core.hooksPath 2>/dev/null | sort -u)
    case $local_v in
    *"$NL"*) die "several core.hooksPath values in $common/config; not guessing" ;;
    "" | .githooks | */.githooks) ;;
    *) die "core.hooksPath=$local_v is not this repo's setting; not touching it" ;;
    esac

    # 1. The dispatcher first. It is inert while core.hooksPath is set, so
    #    there is no moment in which a worktree runs no guard at all.
    mkdir -p "$shared" || die "cannot create $shared"
    tmp="$shared/.pre-push.tmp.$$"
    if ! { cp "$src" "$tmp" && chmod 755 "$tmp" &&
        mv -f "$tmp" "$shared/pre-push"; }; then
        rm -f "$tmp"
        die "cannot write $shared/pre-push"
    fi
    echo "installed $shared/pre-push"

    # 2. The repo-scope value, which the desktop app absolutizes and copies.
    if [ -n "$local_v" ]; then
        git config --local --unset-all core.hooksPath ||
            die "cannot unset core.hooksPath in $common/config (locked? rerun)"
        echo "removed core.hooksPath=$local_v from $common/config"
        echo "      undo: git config core.hooksPath '$local_v'"
    fi

    # 3. Worktree-scope values: what the app wrote, what git copied, and
    #    any hand-set ones. All are removed; the dispatcher replaces them.
    IFS=$NL
    for wt in $(worktrees); do
        IFS=$OIFS
        [ -d "$wt" ] || continue
        # --show-scope lists every scope, one per line; only a worktree-scope
        # line means this worktree carries its own value.
        setting "$wt" | grep -q '^worktree ' || continue
        v=$(git -C "$wt" config --worktree --get-all core.hooksPath)
        if git -C "$wt" config --worktree --unset-all core.hooksPath; then
            IFS=$NL
            for one in $v; do
                IFS=$OIFS
                echo "removed core.hooksPath=$one from $wt"
                echo "      undo: git -C '$wt' config --worktree --add core.hooksPath '$one'"
            done
            IFS=$OIFS
        else
            echo "could not unset core.hooksPath in $wt (locked? rerun)" >&2
        fi
    done
    IFS=$OIFS
    echo "Claude desktop caches the base repo's old core.hooksPath for up to"
    echo "10 minutes and may write it into a worktree it creates or reuses in"
    echo "that window; rerun this installer (or --check) after that."
    echo
    check
}

uninstall() {
    if grep -q "$MARKER" "$shared/pre-push" 2>/dev/null; then
        rm -f "$shared/pre-push" && echo "removed $shared/pre-push"
    fi
    git config --local core.hooksPath .githooks &&
        echo "set core.hooksPath=.githooks (the pre-dispatcher convention)"
}

case ${1:-install} in
install) install ;;
--check) check ;;
--uninstall) uninstall ;;
*) die "usage: sh scripts/install_git_hooks.sh [--check|--uninstall]" ;;
esac
