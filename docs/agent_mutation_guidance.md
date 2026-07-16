# Agent Mutation Guidance

This document provides essential guidelines for agents performing live torrent-state mutation tasks. Adhering to these rules is critical to prevent unintended data modifications and ensure the integrity of the torrent ecosystem.

## Explicit Hash Scope for Mutation Tasks

Any task brief that involves live torrent-state mutation (e.g., repointing torrents, modifying categories/tags, deleting torrents) **MUST** explicitly define the scope of allowed operations using hash filters.

-   **Allowed Hashes:** Always specify the exact torrent hashes that are permitted targets for mutation. Use the `--hash <TORRENT_HASH_PREFIX>` option (repeatable) or `--hash-file <PATH_TO_HASH_FILE>` to provide a newline-delimited list of hash prefixes.
    -   **Example CLI Usage:** `hashall orphan repoint --execute --hash <PREFIX1> --hash <PREFIX2>`
    -   **Example CLI Usage (from file):** `hashall orphan repoint --execute --hash-file /path/to/allowed_hashes.txt`

## Forbidding Opportunistic Mutation

**Agents must NOT scan visible, stopped, or out-of-scope torrents and mutate them opportunistically.**

-   When executing a mutation command with `--execute` (or equivalent), the command *requires* explicit hash filtering. If no hash filters are provided, the operation will be blocked to prevent accidental wide-ranging mutations.
-   Always verify that your task brief includes clear instructions and explicit hash lists for any mutation action.

## Verification

Before and after any mutation operation, ensure you have verified the intended scope and the actual changes.
