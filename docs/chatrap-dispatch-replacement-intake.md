# Replace retired Chatrap dispatch instructions

## Problem

Current `prompts/system/lead-onboarding.md` still instructs CLI leads to use `chatrap dispatch`, including direct-dispatch and model-override forms. Chatrap is on the accepted deprecate-then-remove path and Airo now owns the cross-client `pr-agent` launcher.

Leaving these instructions live would make Hashall direct agents toward a command that Chatrap is preparing to remove.

## Required work

Rehydrate current Hashall workflow semantics and current Airo `pr-agent` contract, then replace only the obsolete `chatrap dispatch` assumptions with the correct destination-owned execution surface or an explicitly preserved Hashall-specific mechanism where current evidence requires it.

Do not perform a blind string substitution: the existing text also encodes task-log, brief, model-selection, lead-commit, and polling assumptions that may not map one-for-one to `pr-agent`.

## Boundaries

Preserve Hashall-owned job/workflow semantics unless current evidence proves they are obsolete. Do not recreate Chatrap dispatch, copy Airo launcher logic, or promote Airo's non-normative concept work into authority.

This file is coordination intake only. Substantive implementation requires a fresh session bound to the resulting Hashall PR.
