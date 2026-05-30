I need to define payload -- to me, a payload is the full folder/path/filename tree structure needed to support the item; each item should have a unique payload.  The purpose
  of this is to be able to delete an item and it's data witout affecting any other item.  If two payloads consist of files that are bit-for-bit duplicates on the samefilesystem,
  it is desirable for those files to share an inode but retain their unique folder/path/filename trees in support of their items -- i.e. they should be hardlinked to save
  space.   The 2nd issue is how to make a folder/path/filename unique??  What guidelines do we follow??  This was grown out of how my system originally used qb categories and
  labels.  The arr's look for qb categories as a trigger for them to process a payload -- i used sonarr, radarr, readarr, speakarr, lidar, etc as the trigger category; the ars
  changed the category after import.  I used the media type -- movie, tv, ebook, audiobook, etc.  Now, because I had ATM (Automatic Torrent Management) enabled in qb, qb would
  place items in their category like this: <save-path>/<category>/<item-payload>; this would result in items moving from <save-path>/<arrs-app>/<item-payload> to
  <save-path>/<media-type>/<item-payload> ; later I started using qbit_manage, and configured it to add a category to all uncategorized items based on a tracker-key to
  tracker-url map that i provided in the config.  This resulted in some items being moved from <save-path>/<item-payload> to <save-path>/<category>/<item-payload>.  The next
  iteration was integrating the cross-seed tool, which allows assignment of a qb category to items, and i choose <category>=cross-seed -- the cross-seed appends the tracker name
  defined in Prowlarr as a folder in the path and stores the full save path in the category which qb uses for that item and results in somethig like this:
  <save-path>/cross-seed/<prowlarr-tracker-name>/<item-payload>; what does this mean for rtorrent?  rtorrent doesn't have category support, but does use labels.  It also deosn't
  have qbit_manage -- but does have cross seed.  I have configured the new item default pathss for rt to mimic the qb paradigm and is seems to be working.   you will see there
  are numerous items now have paths that are not aligned to this.  This is because early hashall rehome code was weak and buggy and messed up the pathing on throusands of items.
  I have spend months getting this functioning again and had to trasnition to rt during that cleanup due to persisten qb OOM crashes...   the long term goal is to get every
  item on it's canonical unique path per the spec above, and make sure that qb and rt both use the same canonical path.  <--- Take this context and save it and write it where it
  needs to go for the next agent.  Clarify anything that is fuzzy.  Find controlling documents that confilict with, or do not address these guidelines and update/improve/harden
  them.  Then run a full code inspect and look for non-compliant code and pland to fix it.  Does this reolve your current question? 

  Clarifying questions (3 genuine fuzzies)                                                                                                                                         
                                                                                                                                                                                    
   Q1 — "majority hardlinkable" threshold:                                                                                                                                          
   The existing code uses arr=linked_to_arr = any single hardlink to an ARR library path → stash. Is "any hardlink present" the correct threshold, or did you intend something like 
   "majority of files in the payload are hardlinked"? For a 20-file season pack where 1 episode failed import, does that 1 hardlink keep the whole payload on stash?

    1. Hardlink threshold for stash placement: Is any ARR hardlink sufficient to mandate stash, or must a majority of payload files be hardlinked?

Q1-Answer:  Does a payyload have any file that shares an inode with a file in media library?  The media library is generally polulated by the arrs via hardlink, and consumers are plex, jellyfin, audobookshelf, etc.
qbit_manage has code that tags these items with ~noHL.  I suggest we look at their logic and use it.  The reason this is done is to rehome items not supported by media to cold storage -- or even deletion.
The human story is, if it's in plex -- I can have 1000 cross-seed hardline copies for free!  (drive space wise).  Once the media copy goes away, it's costing space and needs to go to cold storage (pool) or recyclebin.



                                                                                                                                                                                    
   Q2 — canonical tracker name for cross-seed paths:                                                                                                                                
   Cross-seed creates paths as cross-seed/<prowlarr-tracker-name>/. Is the Prowlarr tracker display name (e.g., darkpeers, FearNoPeer) always the authoritative category key? Or in 
   ambiguous cases (tracker renamed in Prowlarr, or announce URL doesn't match the display name) should the announce URL domain be the fallback?                                    

2. Prowlarr tracker name authority: When a torrent's announce URL and the Prowlarr display name disagree, which is the canonical category key?                                   

Q2-Answer:  <tracker-key> was originally defined in the qbit_manage config url vs key map.  I have created my own tracker registry in the traktor repo.  Hydrate on that and you will see we tie together tracker urls, key, and prowlarr-name.  Use it.  

   Q3 — qB passive/stopped role — is this permanent or transitional?                                                                                                                
   You described qB as "passive, quiet, paused, stopped, backup mirror." Is this a permanent architectural role (qB items should always be stopped/paused), or is it the current    
   operational mode during the RT transition while qB is crash-prone? This affects whether the code should enforce qB-stopped as an invariant or just treat it as current policy. 

     3. qB passive role — permanent or transitional? Should the code enforce qB-stopped as an invariant, or is it current operational posture only?
     
    Q3-Answer:  qB is not active and never will be again unless i decide to go back to it.  The goal is to convert over to rt and shutdown qb.  But during all of the rehome turmoil, the qb tage/category/path data is good to have so I'm keeping it alive on life support.  :)

## Target State (defined 2026-05-29)

### rTorrent

All items should be actively seeding. The only acceptable non-seeding states
are 4 stalledDL items that genuinely have zero seeds for their tiny payload
files (typically season-pack extras like .nfo or sample clips).

Acceptable RT states: stoppedUP, stalledUP, uploading.
Unacceptable RT states: stoppedDL, pausedDL, stalledDL (except the 4 known),
checkingDL (transient, should converge to stoppedUP), downloading (transient).

### qBittorrent

qB is a passive, silent mirror of RT. It never actively seeds. Every hash in
RT must also exist in qB with matching progress. All qB items must be in a
stopped/paused state at all times — after add, during recheck, and after
recheck. The qB client is kept alive on life support for its tag/category/path
data, which is the authoritative source for canonical path resolution.

Acceptable qB states: stoppedUP, stoppedDL (only when RT is also incomplete),
pausedDL (only when RT is also incomplete).
Unacceptable qB states: error, downloading, pausedUP, anything not stopped/paused.

### Path Unification

Every item must have the same canonical save path in both qB and RT. The
canonical path formula is:

    <seeding-root>/<tracker-key>/<payload-name>

Where <seeding-root> is /data/media/torrents/seeding (stash) or
/pool/media/torrents/seeding (pool), and <tracker-key> is determined by the
item origin (cross-seed tracker, arr app, qbit_manage assignent).