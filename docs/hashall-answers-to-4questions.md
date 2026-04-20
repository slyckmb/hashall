1. What is the first execution lane?
   Pick one:
   - normalize names first
   - drain /pool/data first
   - consolidate orphans first
   - review stash/pool duplicates first

Propose the logical order with the least friction and churn when you make the plan.

2. What should be auto-stopped for manual review?
   My current guess is:
   - same path/name, different file hashes
   - both stash and pool copies are fully verified but placement signals disagree
   - unclear or mixed hardlink-anchor evidence
   - incomplete or partially verified payloads in a sibling group
     Confirm or adjust that list.

Confirmed. Be cautions by default and stop to adjust when unexpeted things opo up so we can adjust/clarify policy.

3. For cross-seed-link -> cross-seed, should phase 1 do only path normalization first, and defer duplicate collapse/conflict decisions to a later review phase?
   That is the safest default.

Propose the logical order with the least friction and churn when you make the plan.
I think so.

4. For orphans, should each dataset keep its own local torrents/orphans tree first, and only later rehome stash orphans to pool/spare as space allows?
   That is how I read your intent, but I want it explicit.

Yes.

Each dataset keeps its own local torrents/orphans tree for.  Later, rehome stash orphans to pool &/or spare as space allows.



