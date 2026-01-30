sorting:
implement cla sorting options

top level group options
 - hash then device subgroups
 - device then hash subgroups

sort subgroups by inode 


🚀 Next Steps Toward v0.2 Final
Priority	Feature	Status
🟢 High	✅ Refined group layout with icons, device/inode subgroups	✅ Done
🟡 Medium	🔠 Sorting CLI option (--sort-by)	⏳ Planned
🟡 Medium	🔎 Show only actionable groups (--only-hardlinkable)	⏳ Planned
🟡 Medium	⚖️ File size filters (--min-size, --max-size)	⏳ Planned
🔵 Optional	📤 Export to JSON/CSV (--export)	⏳ Planned
🔵 Optional	🧪 Test coverage, dry run of cleanup logic	🔲 Later
🟢 Misc	🎨 Color-coded file info & simplified display	✅ Done

✅ v0.2.2 Patch Highlights
1. Bugfix: Use correct default DB if $HOME/.filehash.db is missing or empty.
2. Improvement: Fallback warning with suggestion if DB is invalid.
3. Polish: Cleaner group and subgroup output when no matching files are found.


🪵 Optional TODO for polish

Add to your roadmap:

Add CLI filter: --min-dupes, --only-hardlinkable

Optional JSON/CSV export

Color themes

Group sorting: size, reclaimable, path, etc.

🪄 Polish Next
Feature	Status	Notes
Color headers (group, dev, inode)	✅ Done	
Human-readable mtime (local TZ)	✅ Done	
Device subgroup header: include total file size	✅ Done	
Group header includes file count, total size, reclaimable size	✅ Done	
Inode subgroup displayed only when multiple inodes	✅ Done	
Info block [mtime, uid, gid] shown only in verbose	✅ Done	
Chain icon only when same inode & same dev	✅ Done	
📌 TODO for 0.2.x

Potential matches: add files with matching partial hashes but no full hash (sha1 IS NULL). Include with ❔ icon.

Add CLI filters:

    --only-hardlinkable

    --min-dupes N

    --min-size MB

Optional sorting:

    Group output by size, device, file count, etc.

Summary stats block at the end (e.g. total groups, reclaimable bytes, etc.)

Export support: CSV, JSON (for automation / cleanup)

    Optional CLI flag to hide perfect hardlink groups (e.g. no ♻️ or ❔)

Would you like to go ahead and:

    ✅ Commit version 0.2.2 now,

    🚧 Start the patch for ❔ potential matches,

    Or start working on filters/sorting?

 Coming Next (0.2.4+)

    Color-coded headers (differentiating device, inode, reclaimable, etc.)

    Filters:

        --min-dupes

        --only-hardlinkable

        --max-size, --min-size

    Summary stats block

    JSON/CSV export mode

Let me know when you're ready to commit and tag!

✨ Opportunities for Improvement

    🧵 Inline summary per group (optional CLI flag)
    Summary block with:

        Total size

        Reclaimable bytes

        Devices involved

        Linkable candidates

        Potential partial matches (for future)

    📂 Sort order options (on the todo list):

        By dev ID

        By inode

        By file size

        By path (A-Z)

    🧠 CLI filters:

        --only-reclaimable

        --min-dupes N

        --min-reclaim SIZE
        