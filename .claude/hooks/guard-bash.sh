#!/usr/bin/env bash
# PreToolUse guard for Bash — the two rules CLAUDE.md states as prose, enforced.
#   1. Nothing may read or edit secrets.toml (permissions.deny covers Read, not `cat`).
#   2. `git push` may not target main, and may not be forced.
# Exit 2 blocks the call; stderr is shown to Claude as the reason.
cmd=$(jq -r '.tool_input.command // empty' 2>/dev/null)
[ -z "$cmd" ] && exit 0

# The file as a PATH TOKEN (start of command, after whitespace, a quote, `=`,
# a redirect or a paren) — not as a word in prose. Writing docs that mention
# the file in backticks must stay possible; opening it must not.
if printf '%s' "$cmd" | grep -Eq '(^|[[:space:]"'"'"'=<>(])(\./)?(\.streamlit/)?secrets\.toml'; then
  echo "blocked by .claude/hooks/guard-bash.sh: the command opens the Streamlit secrets file. Secrets live only in Streamlit Secrets; never read, print or edit them here." >&2
  exit 2
fi

# Only an INVOCATION counts: `git push` followed by whitespace or the end of
# the line, and only the arguments on that line are inspected. A commit
# message or a doc line that merely says "`git push` to main" (backtick after
# push) is prose, and must still be commit-able from here.
pushargs=$(printf '%s' "$cmd" | grep -Eo 'git([[:space:]]+-C[[:space:]]+[^[:space:]]+)?[[:space:]]+push([[:space:]][^;&|]*|$)')
if [ -n "$pushargs" ]; then
  if printf '%s' "$pushargs" | grep -Eq '(^|[[:space:]:/])main([[:space:]]|$)'; then
    echo "blocked by .claude/hooks/guard-bash.sh: main is not a deploy branch here — all work goes to claude/mishmer-generator-setup-h5gxqx." >&2
    exit 2
  fi
  if printf '%s' "$pushargs" | grep -Eq -- '--force([[:space:]]|$)|(^|[[:space:]])-f([[:space:]]|$)'; then
    echo "blocked by .claude/hooks/guard-bash.sh: no force pushes. Use --force-with-lease only for the merged-PR restart case, and say so." >&2
    exit 2
  fi
fi
exit 0
