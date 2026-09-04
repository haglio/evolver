# evolver — Project-Specific Instructions

Shared rules are in the global `~/.claude/CLAUDE.md`. This file contains only evolver-specific overrides.

## ⏳ On the Windows machine: read the log, then delete `repair_retired_metadata` (2026-08-30)

**Do this the first time you work in this repo on the machine that holds the real library.** It needs
no run and no waiting — the answer is already in `evolver.log` — and it is the last open piece of
backlog item 27. Delete this section once it is done.

`repair_retired_metadata` (`tasks/nonai_upscale.py`) is a one-shot historical backfill wired into
every scheduler tick: it hands back metadata that upscales promoted before `_carry_metadata` existed
lost. `_carry_metadata` runs at promotion time now, so nothing new can be stranded and the pass is
purely retrospective — a permanent recursive walk of every non-AI bucket, a sidecar read per
processed video, and an `rglob` of the archive per candidate, on every tick forever.

It runs on **every** tick (the non-AI stage is called unconditionally at `evolver.py`'s
`_run_stage("upscale_non_ai", ...)` — it always runs so it can check on a detached encode) and writes
its count into the stage's closing line every time. `evolver.log` is a plain appending `FileHandler`
with no rotation, so the whole history is there:

```bash
grep -c 'repaired=0 sidecar(s)' evolver.log; grep -n 'repaired=[1-9]' evolver.log | tail -5; grep -c 'Ambiguous archived original' evolver.log
```

**It is safe to delete when** the most recent `repaired=` in the log is `0` *and* no `Ambiguous
archived original` warning stands after the last non-zero repair. Two things make a `0` mean less
than it looks, so check both: the pass returns at its first line when `content.local.json` has no
`retired_root` (or the folder is missing), and `_archived_original` declines to guess — logging
`Ambiguous archived original` — when two archived originals share a stem, leaving that sidecar
unrepaired while still reporting 0. If `retired_root` is unset, the pass has never done anything on
this machine and the deletion is safe outright. If ambiguity warnings stand, resolve those stems by
hand first; the next tick re-runs the pass on its own.

**Then delete:** `repair_retired_metadata`, its call in `run()`, `_archived_original`, the
`repaired_sidecars` field and its comment, the `repaired=%d sidecar(s)` fragment of the closing log
line, and `TestRepairRetiredMetadata` in `tests/test_nonai_upscale.py` — scaffolding for a completed
migration, not regression guards. **Keep `_carry_metadata`**, which is the promotion-time half that
makes the repair unnecessary. Roughly −75 production lines. `git revert` restores the pass in seconds
if it is ever wanted again. Full write-up: `audit/CHANGELOG.md`, the 2026-08-30 item 27 entry.

## Judging a branch before it lands

Every worktree carries `launch_preview_branch.vbs` (tracked). Double-clicking it
opens THAT worktree's Evolver window on what the branch reports about the real
library — the run-detail table, off the branch's code, with the live app left
running. It never runs the pipeline: Evolver's job is moving files in the one
library and its non-AI stage supervises a detached encode by a pid in a file, so
a second instance would move the same files and adopt the same encode. What each
preview reports is one function per stage in `preview_branch.py`; add one there
when a change makes a stage's report worth judging.

The first launch after a change spends a couple of minutes measuring running
times the library has not recorded yet, and later ones are immediate. The
launcher re-copies the primary's `content.local.json` every time — a stale copy
resolves a library that has moved and the preview comes up empty.

**The preview is part of delivering a user-facing change, not an extra, and it
comes BEFORE the pull request** — opening one here lands the change hands-off
within about twenty minutes, so a preview handed over beside an open PR is a
notice, not a review. Push the branch and open it with `gh pr create --fill
--draft` if it should be visible first, then `gh pr ready` once he says it is
good. **Never launch the preview yourself** — a window over his work gets closed
in irritation and takes whatever else he was running with it. The windowless
pre-handoff check is `python -m pytest tests/test_launch_smoke.py`, which
replays the launch's whole import phase.

## Repo-specific gotchas

(None yet — add entries here when they materially affect launches, tests, or architectural decisions.)

## Test fixtures must be fabricated, never copied from the real library

Every fixture value that stands in for library data — a video title, a filename,
a performer or studio name, prompt text — must be **invented**. Never paste a
real one out of the media library to make a test feel realistic.

This is not a style note. It is the single thing that has actually leaked private
data into these repos: an agent writing a test reached for a real filename or
performer name because it was handy, and it rode into a public commit. Nothing in
the app's *design* pulls library text into source — the library lives outside
every repo, read at runtime through the git-ignored overlays — so this habit is
the only remaining path for a real name to get committed, and the only thing
stopping it is you following this rule.

Do not lean on the sanitize guard to catch it. `app_support.sanitize` fails
the suite when a **known** blocked term appears in the tracked tree, but a brand-
new performer name it has never seen passes every check and lands. The guard is a
backstop for names already known; it cannot see the next one.

So fabricate fully. Use `Jane Doe`, `Example Studio`, `scene one`, the
`alpha`/`beta`/`gamma` act placeholders the committed `content.example.json`
already uses. The near miss that still counts: taking a real filename and
changing a character or two — it is still that clip, still that performer. Make
it up from scratch, don't lightly edit a real one.

## Landing — GitHub merge queue, not local ff-merge

This repo is public at `github.com/haglio/evolver` with a merge-queue ruleset on
`main`, so the global "ff-merge into the primary checkout under
`.git/agent-merge.lock`" flow does NOT apply here:

- **Land through a pull request.** From your worktree: commit, `git fetch origin
  && git rebase origin/main`, `git push -u origin <branch>`, then
  `gh pr create --fill`. Auto-merge arms itself; the queue rebases your PR onto
  `main`, runs the required check, and merges it when green. Don't ff-merge into
  the primary checkout, don't push `main` directly, and never force-push `main`.
- **The `.git/agent-merge.lock` is retired here** — the GitHub queue serializes.
- **Pull the primary checkout once your PR merges — that is the last step of
  landing, not an optional extra.** `main` advances only on origin (via the
  queue), so the primary checkout and worktrees update with
  `git pull --ff-only origin main`. Nothing does this for you: the merge gate
  runs on a GitHub-hosted runner that cannot reach this machine, and the app
  does NOT self-update — this file used to claim it did, and no such code has
  ever existed. The primary is only ever fast-forwarded — never reset or
  merged-into.
- **Then say the app needs restarting.** Evolver is a long-running tray process
  holding the modules it imported at startup, so a pull alone changes nothing
  it executes. The user restarts it from **Restart** in the tray menu or the
  main window's toolbar.
- **A red required check** (`.github/workflows/merge-gate.yml`) can't land.

Everything else in the global CLAUDE.md — work in a worktree, green tests before
you push, clean handoff — still applies.
