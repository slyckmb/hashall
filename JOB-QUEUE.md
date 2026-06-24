# Job Queue — {{PHASE_KEY}}

run_order: "{{RUN_ORDER}}"
closeout_task: "{{CLOSEOUT_TASK}}"
job_key="{{PHASE_KEY}}"
job_id="{{PHASE_ID}}"
track_key="{{TRACK_KEY}}"
doc_type="job-queue"
queue_status="active"
branch="{{BRANCH}}"
worktree="{{WORKTREE}}"
created_at="{{CREATED_AT}}"

---

{{TASKS}}

---

## Queue State Notes

```text
The track_key and phase_key fields are backward-compatibility aliases.
All new code should reference job_key/job_id.
TRACK-QUEUE.md is a symlink to this file for legacy tooling.
```
