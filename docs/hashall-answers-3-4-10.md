3. “Any sibling payloads stay on stash” │
   This is the biggest remaining ambiguity. │
   What exactly counts as a sibling payload here? │
   - same payload hash │
   - same torrent content across trackers │
   - same release/tree shape │
   - same logical media item/family │
     I need the exact grouping rule, because this affects dedupe and placement decisions. │

Answer: you may need to hydrate on the hashall repo concepts and terminology; We have payloads, and payload groups of sibling payloads... siblings are basically non-duplicate payloads where the majority of files share inodes on the same filesystem -- or could share inodes if rehomed to the same filesystem.

4. Hardlink anchor rule │
   For deciding stash vs pool, is the rule: │
   - if any file in the payload has a hardlink into /stash/media libraries, keep the whole payload on │
     stash │
   - otherwise move the whole payload family to pool │
     If yes, say that explicitly. │

Yes, that is the working rule -

If any file in a payload has a hardlink into /stash/media libraries, keep the whole payload on stash; 
otherwise rehome the whole payload group of siublings to pool.

5. First execution priority
   Which top-level lane do you want first?

- normalize names on stash and pool
- drain /pool/data
- orphan consolidation
- duplicate review between stash and pool  
  They interact, so I want the priority explicit.

Answer any needed follow up questions to clarify abiguities.  The we can firm up a plan.