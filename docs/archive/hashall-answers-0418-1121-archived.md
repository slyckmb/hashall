  1. What is the intended top-level target layout under each tree?
     For example, should both /stash/media/torrents and /pool/media/torrents end up with exactly:
     seeding/cross-seed, seeding/orphans, and no cross-seed-link or orphaned_data?
     Or are there other canonical subtrees that should exist in both places?


Answer: yes, this is to simplify and standardize the layout for easy tree compare.  tools may identiofy orphans in each dataset and keep the move atomic and local to the dataset; eventually orphans are rehomed to pool or spare6tb and kep as long as space allows



     
  2. What is the rule for which active seeding payloads stay on /stash/media/torrents/seeding versus move to /pool/media/torrents/seeding?
     Right now the goals say:
      - no duplicates between trees
      - /pool/media is primary for non-media-consumer data
      - /stash/media/torrents/seeding should hold content hardlinked into /stash/media libraries
        I need the exact selection rule for “belongs on stash” vs “belongs on pool.”

Answer:  Foa ACTIVE seeds, if the have hardlinks in media consumer libraries on /stash, they stay on /stash; otherwise, the goal is to rehome them to /pool.  The is because they would take up space on stash becuase they do not have supported hardlinks.  the goal is to keep stash only seeding "hot" media content, and when it loses media hardlinks, the data goes to cole storage on /pool and kept as long as space allows.  /pool is basically a place to offload data and continue to see as long as possible.


  3. When a payload exists in both trees today, which side wins by default?
     Should the winner be chosen by:
      - linked-to-library presence
      - current client save path
      - completeness/hash truth
      - tracker/category
      - newest/canonical path
      - manual review per conflict

Answer: The final location depends on if it's hardlinked in to stash media libraries AND 
if the payload has been verified 100% accurate payload.  These should be handled carefully and need manual review per conflict. You would gather all of the relevant facts about both payloads and present evidence for a human decision.


  4. For (a) merge cross-seed-link into cross-seed, do you want: - pure path normalization only, 
      where the payload stays on the same filesystem and just moves from cross-seed-link/... to 
      cross-seed/... - or also duplicate collapse if the same release exists in both subtrees

Answer:  payloads that merge conflict should be evaluated.  Determine if they are truely duplicate content at the bit level, then one can be deleted.  if there is same filenames but different hash, its potential data corruptions -- these should be handled carefully and need manual review per conflict.  Hopefully jdupes has already hardlinked what can be hardlinke, so data corruption should stand out.

  5. For (b) rename orphaned_data to orphans, should this be: - a literal rename only - or also a 
      cleanup pass that consolidates all orphan content under the new canonical 
      .../seeding/orphans/... layout and removes duplicate orphan copies

Answer: Yes, ideally we would do a cleanup pass that consolidates all orphan content under the new canonical .../seeding/orphans/... layout and removes duplicate orphan copies.

  6. You said “update affected item savepaths in both rt & qb clients.”
     Do you want both clients updated for every live affected torrent, even if one client is not currently owning that payload, or only where that client actually has a corresponding torrent entry?

Answer:  We want qb online with all items synced with rt. and all qb items paused/stopped.  So qb is a silent mirror supporting the qb -> rt transition.  It's metadata is valuable. So if we make a change to savepath data in one client, we keep the other client in sync with the change.

  7. Is qB still authoritative for rehome apply and payload materialization in your live environment, or are we now allowed to treat RT as equal authority for move/followup operations?
     This changes which toolchain is safe to use.

At this point, we are moving to RT be authrative, and qb is a silent back, but kept in sync.  Tolling that uses RT is newly changes and may have undiscovered bugs, so be on the watch for errors and improvements.

  8. Should /pool/media/torrents/orphans live directly under /pool/media/torrents/orphans, or under /pool/media/torrents/seeding/orphans?
     Your earlier wording and the new wording differ.

Answer:  I may have made a type mistake.  By definition, orphans are not seeding, so they should be located in the torrents folder, and not in torrents/seeding.



  9. Do you want /stash/media/torrents/seeding/orphans to exist too, for symmetry, or should all orphans be centralized only under /pool/media/torrents/orphans?

*/torrents/orophans folders need to be on stash and pool to keep data moves from seeding -> orphans atomic.  Other tools will rehome orphans from stash to pool as space allows.



  10. For /pool/data, should every torrent-related payload leave that tree eventually, with zero live seeding content remaining there?
     Or are there any intentional exceptions?

Answer:  Yes, every torrent-related payload should leave /pool/data eventually, with zero live seeding content remaining there.

  11. When you say “no duplicates between trees,” does that mean:

  - no duplicate payload hashes across /stash/media/torrents and /pool/media/torrents
  - or no duplicate file trees by path/content, even if client state differs
  - or no duplicate live-owned payloads, while orphan duplicates may temporarily exist during staged cleanup


Answer:  We don't want duplicate payloads (same tree naming and same file hashes) on both stash and pool.  This is a waste of space.  If the payload is on stash and has hardlinks in media libraries; it stays on stash -- AND any sibling payloads stay on stash.  

If there is not hardlink hot media anchor on stash, the payload siblings migrate to pool.


  12. Do you want this organized in phases?
     My current read is:

  - Phase 1: normalize names (cross-seed-link -> cross-seed, orphaned_data -> orphans)
  - Phase 2: decide stash-vs-pool ownership rules
  - Phase 3: migrate /pool/data residue into canonical homes
  - Phase 4: reconcile client savepaths and verify
    If that ordering is wrong, say so.

Break up this into logical phases that are easy to error check and fix if somerthing breaks.



  The biggest ambiguity is the stash-vs-pool placement rule. Once that is explicit, the rest becomes much safer to automate.


Review my answers and ask follow-ups for anything else that is ambiguous.
