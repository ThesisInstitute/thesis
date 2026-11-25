#!/bin/sh
# thesis-pre-push-dispatcher v1 -- installed by scripts/install_git_hooks.sh
#
# This file is not the records guard. It is installed once per clone into
# the clone's SHARED hooks directory, $(git rev-parse --git-common-dir)/hooks,
# which every worktree of the clone uses when core.hooksPath is unset, so
# git runs this one file for every push from every worktree. It hands the
# push, unchanged (same arguments, same stdin ref lines, same environment),
# to the guard checked out in the worktree doing the push:
#
#     <that worktree>/.githooks/pre-push
#
# It judges nothing itself and never lets a push through unguarded: a
# checkout with no guard on disk is refused. Why a dispatcher instead of
# `git config core.hooksPath .githooks`: see AGENTS.md, "The records-path
# guard".

# A loop (this file installed where the guard should be) would otherwise
# exec itself forever.
if [ "${THESIS_PRE_PUSH_DISPATCHED:-}" = "1" ]; then
    echo "BLOCKED: pre-push dispatcher re-entered (hook loop); see AGENTS.md." >&2
    exit 1
fi
# </dev/null: nothing before the guard may consume the ref lines on stdin.
top=$(git rev-parse --show-toplevel </dev/null 2>/dev/null) || top=""
guard="$top/.githooks/pre-push"
if [ -z "$top" ] || [ ! -f "$guard" ]; then
    echo "" >&2
    echo "BLOCKED: no records guard at ${top:-<no work tree>}/.githooks/pre-push." >&2
    echo "This checkout predates the guard, or a sparse checkout leaves out" >&2
    echo ".githooks/. Merge or rebase onto current main (or add .githooks/ to" >&2
    echo "the sparse checkout) and push again." >&2
    echo "" >&2
    exit 1
fi
THESIS_PRE_PUSH_DISPATCHED=1
export THESIS_PRE_PUSH_DISPATCHED
exec sh "$guard" "$@"
