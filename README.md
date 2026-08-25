# Evolver

Evolver is a video collection maintenance pipeline that runs as a system tray application and:

1. Sorts videos from `0_inbox/<source>/` into `1_sorted/<source>/<orientation>/`
2. Purges `kinda_weird/` outputs from the active outbox set — normally `2_outbox`, and both `2_outbox` plus `3_new_outbox` while regeneration mode is enabled. It also deletes each weird file's corresponding source from `1_sorted/`. A Windows error dialog pops up if any source file cannot be found.
3. Rehomes `.funscript` files under `videos/scripts/scripts` so they mirror the matched video path under `videos/videos`. A script only moves when there is exactly one basename match in the same library lane; scripts under `2D/AI` only consider `2D/AI` videos, and scripts under `2D/non_AI` only consider `2D/non_AI` videos. A script whose video is gone from the library but present in the `retired_root` archive (see "Non-AI library upscaling" below) follows it out and comes to sit beside it; a left-behind duplicate of a script the archive already holds is discarded once the two compare byte-identical. Names that match no video at all, or more than one, are logged and left alone. After that, Evolver also copies missing funscripts across matching processed/original video variants, including `1_sorted` <-> `2_outbox` / `3_new_outbox` `_topaz` pairs and matching `processed` <-> non-processed variants within the same source bucket.
4. Prunes stale rows from `fun_time/favs.csv` when the `local_file` or `file` column points at a missing local file — but only after step 8 has already repointed every favorite whose video merely moved, so a row is dropped only when its video is genuinely gone. The remaining `web_url` values are then synced into a `Fun Time Favs` folder on the Chrome bookmarks bar for the Chrome profile whose visible name is `Blair`.
5. Scrapes prompt metadata for AI videos in `1_sorted` into `videos/metadata`, mirroring the active outbox tree. The scan is idempotent — videos that already have a metadata JSON are skipped, and a video whose scrape fails is marked so it is not retried every run. Currently supports Provider prompt extraction with the video prompt plus optional source-image prompt keys.
6. Upscales/interpolates sorted videos using Topaz Video AI ffmpeg. Work is now capped per scheduler run, newly sorted inbox files are processed first, and any remaining batch slots can be used for regeneration backlog.
7. Gradually upscales the `2D/non_AI` library too, with the recipe its already-processed clips carry in their `videoai` tags (see "Non-AI library upscaling" below). Off by default — a one-time opt-in from the tray menu, after which Evolver runs at most one detached encode while you're idle (AI queue drained) and suspends it the moment you return to the machine.
8. Repoints the suite's saved video paths at videos that have since moved, so a Clipper session or a Fun Time favorite survives the library being rearranged (see "Following videos that moved" below).
9. Scans `1_sorted` for likely accidental duplicates: video files with the same exact filesize but different filenames, with a Windows error dialog if any are found
10. Runs a final 1-to-1 correspondence check between `1_sorted` and the active outbox set, where each sorted file must have an outbox counterpart named `<sorted_stem>_topaz<ext>`, with a Windows error dialog if mismatches remain
11. Delivers the Genau lane — Origenerator's looping single-stroke clips, which arrive under their own `0_inbox` source folder (`config.GENAU_SOURCE`, named by the content overlay) — out of the outbox into `videos/genau/clips/`, the one folder Genau plays from, retiring the `1_sorted` copy along with it. Those clips come through the pipeline only to be upscaled: a loop straight out of the graph is visibly softer than the clips already in that folder, which came from upscaled library video. Both halves have to leave together — the upscale stage decides what still needs doing by looking for the output beside its source, and step 10 requires each sorted video to have a `_topaz` counterpart.

12. Records what kind every video in the library is — `genau_clip`, `excerpt`, `short` or `full_length` — on its metadata sidecar, as `video.type`. One field, written here and read by Fun Time, Nau and Warm Gun in place of the several tests each of them used to run (a running time against a threshold each picked separately, the folder the Genau loops are delivered to, the presence of a `clip` record, and "everything else"). The stage walks the whole library every run, so it backfills a library that has never been asked and keeps up with the ones arriving, out of the same code and with no one-off script to remember. What it asks depends on what the answer costs: where a video sits and whether its sidecar says something carved it out of a longer video are free to read, so those two kinds are re-derived every run and the record corrects itself — declare a folder of excerpts in the overlay, or split a video and write it a `clip` record, and the next run fixes what it wrote before it knew. A running time costs an ffprobe, so that answer is remembered once; a run measures at most `VIDEO_TYPE_BATCH_LIMIT` videos, so the first passes over a big library spread over a few runs instead of holding one up, and a video ffprobe cannot read is left for the next run rather than guessed at. Excerpts — scenes carved out of longer videos — are known by the `clip` record on their sidecar; for the batches split before anything wrote one, by the company they keep, since a batch whose librarian filed its cuts into a folder of their own put nothing else in there; and failing both, by the folders `excerpt_folders` names in the content overlay.

`<source>` is discovered dynamically from directory names. Any new subdirectory under `0_inbox` is treated as a source automatically, and matching output directories are created on demand.

## Current architecture

- **Tray app**: `pythonw.exe tray_app.py` — system tray icon with GUI, configurable timer (default 10 min), manual run trigger, run history, and live progress bars
- **CLI mode**: `python evolver.py` — headless single run, returns exit code
- Pipeline entry point: `evolver.py`
- Modules:
  - `config.py` - paths and settings
  - `tasks/sort.py` - Stage 1 inbox sorting
  - `tasks/purge_weird.py` - Stage 2 kinda_weird cleanup
  - `tasks/scripts_sync.py` - Stage 3 funscript/video tree alignment and processed/original variant copying
  - `tasks/bookmarks_sync.py` - Stage 3.5 favorites -> Chrome bookmarks sync
  - `tasks/prompt_scrape.py` - Stage 4 prompt scraping into mirrored JSON files
  - `tasks/upscale.py` - Stage 5 Topaz processing
  - `tasks/genau_deliver.py` - the Genau lane's last step: an upscaled loop leaves for Genau's clips folder
  - `tasks/nonai_upscale.py` - the non-AI library's detached Topaz encodes, one at a time
  - `tasks/reference_sync.py` - repointing the suite's saved video paths at videos that moved
  - `util/reference_stores.py` - which files across the suite record a video path, and how to rewrite one
  - `util/favs_csv.py` - Fun Time's favorites CSV: its rows, and the local path each cell links to
  - `util/video_locator.py` - where a video a reference has lost track of now lives
  - `check_duplicate_sizes.py` - Stage 6 duplicate-size scan for likely source duplicates
  - `check_correspondence.py` - Stage 7 integrity verification and one-time manual check
  - `util/ffprobe.py` - orientation probing
  - `util/media_files.py` - shared helpers for finalized-vs-partial video detection and stale partial cleanup
  - `util/sidecar.py` - where a video's metadata JSON lives, and what the upscale stage names its output
  - `util/video_type.py` - the four kinds a video can be, and which one a video is
  - `tasks/video_types.py` - recording that kind on every library video's sidecar
  - `util/topaz.py` - the Topaz ffmpeg invocation both upscale stages share
  - `util/variants.py` - the `_apo8`/`_iris2`-style suffixes that pair originals with processed variants
  - `util/processes.py` - liveness, identity, and termination of detached encodes
  - `backfill_app.py` - voice-driven metadata backfill tool (see below), launched from the tray
  - `backfill/vocabulary.py` - the spoken phrases, and the `video.action` each one records
  - `backfill/queue.py` - the clips still missing an action, shuffled
  - `backfill/decisions.py` - writing a clip's action or discarding it as weird, and taking either back
  - `backfill/session.py` - what a heard phrase does to the queue, and the history "undo" walks back through
  - `backfill/work.py` - the single thread the file work runs on, in the order it was spoken
  - `backfill/voice.py` - offline vosk recognition over the tool's grammar
  - `backfill/window.py` - the looping player, the remaining count, and the last decision
  - `gui/app.py` - tray application wiring
  - `gui/single_instance.py` - who owns the one instance, and where a second launch goes
  - `util/crash_log.py` - what the tray app records about the way it died
  - `gui/tray.py` - system tray icon and context menu
  - `gui/main_window.py` - run history list and detail/progress panel
  - `gui/progress.py` - live per-stage progress widget
  - `gui/worker.py` - background QThread pipeline runner
  - `gui/scheduler.py` - timer-based scheduling with run-guard
  - `gui/run_record.py` - JSON run record persistence
  - `gui/settings.py` - settings dataclass and persistence
  - `gui/startup.py` - Windows Startup folder shortcut management

## Requirements

- Windows
- Python 3.14+
- `ffprobe` available in `PATH`
- Topaz ffmpeg at `C:\Program Files\Topaz Labs LLC\Topaz Video\ffmpeg.exe`
- Topaz model directory at `C:\ProgramData\Topaz Labs LLC\Topaz Video\models`
- PyQt6 (`pip install PyQt6`)
- `vosk` and `sounddevice`, for the backfill tool's voice commands (`pip install vosk sounddevice`). The speech model is downloaded and cached on first use.

## Run as tray app (recommended)

```bash
pythonw.exe tray_app.py
```

This starts a system tray icon. Right-click for the context menu (Run Now, Pause/Resume, Settings, Stats, Backfill Metadata, Quit) or double-click to open the main window with run history and live progress. Configure the run interval and Windows startup registration from Settings.

Run history is stored as JSON files in `runs/` (gitignored). Settings are persisted to `gui_settings.json` (gitignored).

### Launching it again

Only one Evolver ever runs — two schedulers would mean two pipelines and stacked Topaz encodes. But its window lives in the tray, so *launching* Evolver while it is already running is how you ask to see it: the shortcut, the Start menu entry, and the taskbar pin (whose relaunch command Windows re-runs verbatim) all start a second process whose real job is to open the first one's window. That process hands the request over a named pipe and exits.

A launch never ends without telling you why. If the running instance holds the mutex but does not answer the pipe, or if startup fails before there is any window to report into — a missing dependency, say, which under `pythonw.exe` has neither a console nor stderr — you get a Windows dialog naming the cause and pointing at `tray_crash.log`, instead of a launcher that appeared to do nothing.

## Metadata backfill tool

Most sources publish nothing about what a clip actually shows. Provider exposes an action on its site and Origenerator has its gallery database, so Stage 5 fills those in on its own; a clip from Provider2, Provider3, Candy, ComfyUI or Provider4 arrives with no `video.action` at all, and Fun Time cannot group or filter it.

**Backfill Metadata...** in the tray menu opens a separate window that plays every such clip — looping and muted, in the stable order it found them so a reopened session resumes where the last left off — until you say what it is. The clip changes the instant you speak, and the sidecar is written behind it.

Clips whose act was **rejected** jump that order and are asked about first. Fun Time's "wrong action" command empties a mislabeled clip's `video.action` and leaves `video.wrong_action` holding what it said, which is how this tool tells a clip someone just looked at and corrected from one nobody ever labeled — and why a rejection also overrides the scraped-source skip above, since re-scraping would only assert the wrong act again. Naming the act retires the marker along with the question it stands for.

Say an act, always prefixed with a camera word — `side`, or `POV` said as its three letters ("pee oh vee"). Every clip is tagged Side or POV; no act has a bare, camera-less form:

| Say (act) | Act recorded |
| --- | --- |
| `alpha form` / `alpha` | `Alpha` |
| `beta` | `Beta` |
| `gamma` | `Gamma` |
| `delta` | `Delta` |
| `epsilon` | `Epsilon` |
| `eta` | `Eta` |
| `zeta` | `Zeta` |
| `dance` / `dancing` | `Dancing` |
| `other` | `Other` |

So "side beta" records `Side Beta`, and "P-O-V zeta" records `POV Zeta` — matching the `POV Gamma` form the prompt scraper writes, so one Fun Time filter query reaches both. Even `dance` and `other` take a camera word: "side dance" records `Side Dancing`. The recognizer listens for the initialism spelled out (`p o v ...`), because the vosk lexicon prices each letter as its name; it also accepts a one-word "pov", whichever way you happen to say it.

Four more phrases:

- `same` — record the last act again on the clip now on screen, for a run that all share one act. It reaches past any intervening `skip` to the last act actually spoken, and says "nothing to repeat" if you have not named one yet
- `skip` — not now; the clip goes to the back of the queue and comes round again
- `weird` / `trash` — move the clip to `kinda_weird/`, exactly as Fun Time's "mark as weird" does. No metadata is written; Stage 2 later deletes it along with its `1_sorted` source
- `undo` — take the last decision back, and keep saying it to walk back through the whole run

Undo restores the clip to the screen and reverses what the decision did on disk: a sidecar it wrote is deleted (or, if the clip arrived carrying prompts, only the act is removed), and a clip sent to `kinda_weird/` is reclaimed from where it landed. Undoing every decision rewinds the queue to the order it had. It works after the last clip too, so a mislabelled final clip is still recoverable.

Three lines sit beneath the video: what is on screen now and how many clips are left; what the recognizer is hearing this moment; and what your last phrase did — the last naming its own clip, which by then is not the one you are watching. The middle "hearing" line fills in as it recognizes on-script words and stays blank when what you said is not a command, so a phrase that never lands shows as a visible nothing rather than a silent one — the way to tell listening-but-unmatched from not-listening. `Esc` closes the window; whatever you have labelled is already on disk, and reopening picks up where you left off.

A panel on the right lists every command as a clickable tile, laid out the way the vocabulary is: every act as a grid of `Side` / `POV` columns, then the controls. It is both the on-screen reference — no need to remember what the phrases are — and a fallback that never depends on the microphone: clicking a tile drives the exact same path a spoken phrase would, so a mishearing mic or a quiet room never leaves you unable to label. Each tile shows the action it records, names its spoken phrase on hover, and carries an example frame so the grid reads as a gallery you recognize at a glance. Most tiles take that frame from the first clip the library already labels with the act — a compound tag like `Pov Gamma, Alpha` counts for either part — while the acts the library never tags in a camera-scoped form (a side beta, a POV delta) are pinned to a hand-picked clip in `CURATED_EXAMPLES`. Frames are sampled a little way into the clip (past the intro, with the act actually in view), extracted once, and cached under `config.BACKFILL_THUMBNAIL_DIR`, then composited onto a fixed square so they keep their aspect ratio instead of stretching to fit. The window loads only those ready files — nothing extracts on open — and opens maximized so the whole grid fits.

Acts are voiced in plain-English words because the vosk lexicon has none of the compounds — the same trick Fun Time uses. Audio is muted while you label, since the microphone is open the whole time. The window runs as its own process, so it can never take the tray down with it. The recognizer does not open the system default input — Windows often makes a dead virtual mic the default (a VR headset the Pimax update repointed to), which feeds vosk silence — so it briefly probes the real inputs and listens on the liveliest, logging which device it settled on. Set `config.VOICE_DEVICE_NAME` to a substring of your mic's name (from `python -m sounddevice`) to pin a specific one instead.

## Non-AI library upscaling

The `2D/non_AI` buckets (`larkin`, `other`, …) hold full-length real-footage scenes that were being enhanced by hand in the Topaz GUI. Evolver now works through that backlog on its own, using the recipe the already-processed clips record in their `videoai` metadata tags: **apo-8** 60 fps interpolation, then an **iris-2** upscale in auto mode with recover-original-detail at 100, aimed at a 4K frame (Topaz caps small sources at the model's 4x). Real videos keep their soundtrack (re-encoded to AAC), unlike the silent AI clips. The encode runs at half the AI stage's Topaz memory budget (`vram=0.5`, no extra model instance) — slower, but a background job never gets to push the box toward memory exhaustion.

It follows the bucket conventions already in use:

- Candidates come from the triage folders whose names start with `0` or `1`, plus the sub-stages those split into whose names start with `2` or `3` (`2_originals_good_trimwise_but_need_upscaling`, `3_trimmed_from_originals_but_still_need_upscaling`) — trimming is settled there and only the encode is left. Sub-stage `1_originals_needing_trimming` is skipped: it stages manual pre-work that should happen first.
- The output lands in the bucket's `3*/processed/` folder as `<stem>_apo8_iris2.mp4`, and the original is then retired. By default that means the bucket's `2*` ("do not need work") folder, the convention the user set by hand. Set `retired_root` in the content overlay and the original instead leaves the library altogether for that archive, at its library-relative path — those `2*` folders sit on the drive the encodes write to, and every finished encode parked roughly another gigabyte of source nobody watches on it. An archived original takes its metadata sidecar and its funscript with it and they sit *beside* it, since the mirrored trees cover only the library and a video outside it has to describe itself. The scripts stage sends a funscript after a video that left the library without it, so hand-archiving a folder does not strand its scripts.
- **The upscale is handed the original's sidecar before the original is retired.** An upscale is the same footage, so what the sidecar says about the footage — the `clip` object naming which compilation the video was carved out of, and the recorded `video.action` — describes it just as well. Those lived only on the original, and retirement takes its sidecar out of the library, so without this copy promoting an upscale is what loses them: the grouping stage would carry a `clip` across from an in-library original, but it runs later in the same pass and by then there is none. The `version` block is deliberately left behind — it describes the file rather than the footage (the original is not a processed variant and the upscale is), and grouping stamps the upscale's own on the same pass. Funscripts are not carried here; the scripts stage already copies an original's script onto its processed variants.
- **Upscales promoted before that copy existed are repaired from the archive.** Every pipeline pass looks for a processed video whose sidecar has no `clip` object, finds its retired original by name under `retired_root`, and carries the record across now — the originals were archived whole, so nothing was ever destroyed, only moved out of reach. It runs ahead of the clip-scripts stage, which needs the record restored before it can cut a clip its own funscript. Idempotent, and it never overwrites a record that is already there, so a hand-corrected sidecar stands. Two archived originals of one name repair neither: nothing can say which the upscale came from, and guessing would write one clip's provenance onto another's footage. The tick log's `repaired=` field counts what it put back.
- A video is skipped when any processed variant of it already exists in the bucket (`_iris2`, `_apo8_prob4`, and friends — see `util/variants.py`), or when it already carries a `videoai` tag itself. Pinning it (below) overrides the first of those, which is how you ask for a redo under a newer recipe.
- `actually_AI_but_funscripted/` is left alone; its contents are AI-pipeline outputs.

**Order**: pinned videos go first, in the order they are listed in `.nonai-upscale-next.txt` (repo root, gitignored, same `path<TAB>note` format as the skip list — the counterpart to it: "encode this one next" rather than "never encode this"). A pin outranks every heuristic below it and also re-queues a video the bucket already holds an older processed variant of. Then an explicit `1 could use work` flag; then Fun Time watch score, descending — read straight from `fun_time/state/watch_stats.json` with the same `completions + 3×locks − skips` arithmetic its playlist breeding uses, so once Fun Time starts tracking primary (Nau/Hybrid) plays, the most-watched videos move to the front on their own; funscript ownership breaks ties among the unwatched (a fair proxy, since Nau drives the OSR2 with them); then everything else alphabetically.

**Off by default — a one-time opt-in.** One of these encodes monopolizes the GPU for hours and can make the desktop crawl, so the stage starts nothing until **Upscale Non-AI When Idle** is checked in the tray menu. Checking it is not a "run now" — it hands the whole thing to Evolver, which from then on manages the encode by your presence, no more flipping required. It starts or resumes an encode only once you've been idle past `NONAI_USER_IDLE_THRESHOLD_SECONDS` (5 min), and the instant you touch the keyboard or mouse it *suspends* the detached ffmpeg — frozen in place at zero CPU/GPU, no work lost — then resumes it exactly where it left off when you idle out again. A fast GUI poll (`NONAI_PRESENCE_POLL_SECONDS`, 20s) parks and thaws it between the slow pipeline ticks, so returning to the machine takes effect within seconds. Over a day of on-and-off use the encode ekes out progress in the gaps instead of restarting from scratch. *Unchecking* the toggle is not the same as stepping back: it kills the in-flight ffmpeg outright and the video keeps its place in the queue — no retry penalty; an encode that already finished is still promoted. Headless CLI runs (`python evolver.py`) have no toggle and neither start, suspend, nor stop encodes; they only promote finished ones.

**Gradually** means: one video at a time — and more broadly, **one Topaz process on the machine, ever**. The stage refuses to start while *any* Topaz ffmpeg is running (its own, an orphan, or a manual GUI export), and the AI upscale stage likewise waits (`skip_reason: topaz_busy`) while a non-AI encode is in flight, because stacked Topaz encodes are what exhausted memory and crashed the machine. These encodes take hours, and the tray watchdog kills a pipeline run at eleven minutes, so the stage never waits on ffmpeg: it launches a single detached, below-normal-priority Topaz process and returns; each later scheduler tick checks on it. A finished encode (output duration ≥ 98% of the source's) is promoted and its original retired; an interrupted or failed one is retried once and then parked in `.nonai-upscale-skip.txt` (repo root, gitignored, one `path<TAB>reason` per line — delete a line to retry it). An encode still *actively* running after 24 hours is killed, but only after confirming the pid still belongs to Topaz ffmpeg — time spent suspended for user presence is banked in the job and subtracted, so a heavily-paused encode is never mistaken for a stuck one.

A new encode starts only when *all* of these hold: the toggle is on, the user has been idle past the presence threshold, the AI upscale queue is drained, no Topaz ffmpeg is already running, CPU is below the busy threshold, at least `NONAI_MIN_AVAILABLE_RAM_GB` (8) of RAM is free, free disk is above the safety floor, and at least `NONAI_COOLDOWN_MINUTES` (30) have passed since the previous encode ended — so an unattended night alternates encode / breather instead of running the GPU flat out end to end. The tick log's `deferred=` field says which gate held a start back (`user_present`, `topaz_busy`, `low_ram`, `cooldown`). The disk floor is also enforced *during* an encode: if free space crosses it mid-write, the encode is stopped (no retry penalty) instead of running toward a full disk.

**Watching it**: every tick appends one line to `evolver.log` — `Non-AI upscale: started=... in_flight=... promoted=... stopped=... failed=... pending=...` — so a `grep "Non-AI"` over the log is the quickest status. While an encode runs, `in_flight` carries its progress, e.g. `in_flight=other/0 unsorted/clip.mp4 (37% encoded)`, measured by probing the duration written to the growing partial so far (the first minute or two may show no percentage while the file's header lands); a frozen encode reads `… [suspended: user present]`. What's encoding right now (source, output, pid, start time, and how long it has spent suspended) sits in `nonai_upscale_job.json`, and the encode's own stderr streams to `nonai_upscale_ffmpeg.log`. The same per-tick summary — including `in_flight_percent` — lands in each run's record, visible in the main window's run history under the **Upscale non-AI** stage row.

In-flight state lives in `%LOCALAPPDATA%\Evolver\` (`nonai_upscale_job.json`, `nonai_upscale_attempts.json`, `nonai_upscale_cooldown.json`, plus the encode's `nonai_upscale_ffmpeg.log`) — deliberately *outside* the project tree, because the file sync service covering it kept renaming the in-flight job file to `nonai_upscale_job [conflicted N].json` mid-run, which orphaned live encodes and let new ones stack on top. As a backstop, if the job file is ever lost while a lone Topaz encode of ours is still running, the stage re-identifies it from the process's own command line and adopts it back under supervision instead of starting another. Quitting the tray app does not kill the encode; the next session picks it back up from the state file.

## Following videos that moved

Moving a video is Evolver's whole job, and every move silently breaks whatever else in the suite had written that video's path down. Clipper stores a session's `video_path` absolutely, so a scene you clipped last month stops opening — "Could not open video" — the moment its folder is rearranged. Evolver owns that breakage, so it owns repairing it.

Each run, after every stage that could have moved something, Evolver walks the suite's saved references and follows the moves:

| Store | What it holds |
| --- | --- |
| `clipper/sessions/*.json` | a session's `video_path` — the clip bounds you set by hand |
| `scripture/sessions/*.scripture` | a project's `video_path` — its splits, tracking and ground truth |
| `fun_time/favs.csv` | the `local_file` hyperlink on every favorite, URL and label alike |
| `fun_time/state/watch_stats.json` | the completions/skips/locks keyed by video path, re-keyed in Fun Time's own lowercased form |

Those four are the stores that hold something you cannot get back: clip bounds and splits made by hand, a curated favorites list, and watch counts accumulated over months. Playlists, HUD state, duration caches and thumbnail caches are all regenerated from the library on demand, so a stale entry in one costs a rebuild rather than the data, and Evolver leaves them alone.

The stage runs *before* the bookmarks sync on purpose: that stage drops favorites whose file is missing, so a favorite whose video merely moved has to be repointed first or it gets deleted on the very run that could have saved it.

A reference whose file is missing is matched against the library by **exact filename**, case-insensitively, across everything under `videos/` — wider than the library proper, so a video parked in a sibling folder like `_larkin_compilations_archive/` is still found. Matching on the full filename rather than the stem is deliberate: `clip.mp4` and `clip_apo8_iris2.mp4` are the same scene but not the same footage, and a Clipper session's frame numbers only mean anything against the exact file they were set on.

Nothing is ever dropped. A reference is rewritten only when exactly one file in the tree carries that name; when none does, or several do, it is left untouched and logged as `UNRESOLVED`. Videos sitting in `kinda_weird/` are excluded from the search — the purge stage is about to delete them, so pointing anything at one would only re-break it.

**When the name itself is gone.** A rename leaves nothing to match on, so there is one fallback, and only for the stores that can support it: a Clipper session and a Scripture project each record the `fps` and `total_frames` of the footage they were cut against, which is a usable fingerprint for the video itself. If the filename resolves to nothing, Evolver probes the videos in the one folder the reference named — a renamed file usually stays put, and probing the whole library on the off chance would cost minutes — and repoints only when exactly one of them reports that same frame rate and frame count. An inexact match is not a match: two cuts of the same scene have different frame counts, and a session's clip bounds are frame indices that mean nothing against the wrong one.

`grep "REPOINT\|UNRESOLVED" evolver.log` is the quickest way to see what moved and what still needs a human.

## Run manually (CLI)

From repo root:

```bash
powershell.exe -File evolver.ps1
```

Alternative (direct Python command):

```bash
python evolver.py
```

## One-time correspondence check

If you want to run the same integrity check manually, verify that `1_sorted` and `2_outbox` are in 1-to-1 correspondence (same file count, every sorted file has an outbox file with `_topaz` appended before extension, and every outbox file matches that pattern):

```bash
python check_correspondence.py
```

Output reports any mismatches — orphaned outbox files, orphaned sorted files, count differences, or duplicate outbox basenames. The scheduled flow now runs this same check automatically after the kinda-weird cleanup, after any needed upscale work is finished, and after the duplicate-size scan.

## Logs

- Log file: `evolver.log`
- Each run logs sort, purge, scripts-sync, bookmark-sync, prompt-scrape, upscale, duplicate-scan, and correspondence summary counts

## Regeneration mode

When `config.REGEN_ENABLED = True`, Evolver writes new outputs to `3_new_outbox` instead of `2_outbox`.

- Correspondence checks treat `2_outbox` and `3_new_outbox` as one combined active output set.
- Existing `2_outbox` files remain valid until their regenerated `3_new_outbox` replacement succeeds.
- After a successful regenerated write, Evolver can delete the matching legacy `2_outbox` file immediately to save disk space.
- When correspondence is clean and the legacy `2_outbox` payload has been fully drained, Evolver can notify you, remove the emptied legacy tree, and rename `3_new_outbox` back to `2_outbox` automatically.
- A completion marker is written to `config.REGEN_COMPLETE_MARKER` so later scheduler ticks stay in normal mode after cutover instead of starting a second regeneration by accident.
- This makes it possible to regenerate the library incrementally while keeping the old outbox available until cutover.

### Regen skip manifest

During regeneration mode, Evolver may write `.regen-skip.txt` in the repo root.

- This is a generated runtime manifest, not source code.
- Each line is a `1_sorted`-relative video path that should be skipped on future regen retries.
- Evolver records an entry when regen work fails but the matching legacy `2_outbox` counterpart still exists, so the same item does not get retried every scheduler run.
- If you want Evolver to retry one of those items, remove that line from `.regen-skip.txt` after dealing with the underlying issue.
- The file is intentionally gitignored.

## Test suite

The suite runs under `pytest` (configured in `pyproject.toml`) and is enforced in
CI: the **merge gate (full suite)** workflow runs every test on windows-latest for
each pull request and is a required check on the merge queue, so a red tree cannot
land on `main`.

Install the dev extras once, then run from repo root:

```bash
pip install -e ".[dev]"
python -m pytest -q
```

The tests are `unittest.TestCase`-based, so `run-tests.ps1` (a `unittest discover`
wrapper) still works for a quick local run without pytest.

What is covered:

- Orientation detection logic (`util/ffprobe.py`) via mocked `ffprobe` output
- Sort-stage collision behavior and empty-dir cleanup (`tasks/sort.py`)
- Kinda-weird cleanup and missing-source popup behavior (`tasks/purge_weird.py`)
- Duplicate-size scan for likely same-content source videos (`check_duplicate_sizes.py`)
- Funscript alignment so `videos/scripts/scripts` mirrors `videos/videos` when basename matches are unique within the same `AI` or `non_AI` lane, plus variant-copy support for processed/original counterparts (`tasks/scripts_sync.py`)
- Correspondence rules for `<sorted_stem>_topaz<ext>` matching (`check_correspondence.py`)
- Scheduler flow behavior, including always-running purge and pending-work-based Stage 3 decisions (`evolver.py`)
- Already-processed detection (`tasks/upscale.py`)
- Partial-file handling across upscale cleanup and downstream scanners (`tasks/upscale.py`, `check_correspondence.py`, `tasks/prompt_scrape.py`, `tasks/sort.py`)
- Non-AI candidate discovery, priority order, and the detached-encode lifecycle: launch, in-flight, promote, retry, skip-manifest, and stuck-job kill (`tasks/nonai_upscale.py`)
- Single-instance ownership and the duplicate-launch handoff, both halves of it: that a second launch opens the running instance's window, and that the running instance is listening for one (`gui/single_instance.py`, `gui/app.py`)
- That no launch ends without saying why, whether it fails the handoff or crashes before there is a window (`gui/app.py`, `tray_app.py`)

## Output temp-file contract

Stage 5 writes Topaz output to a temporary filename before promoting it to the final `_topaz` path.

- Temp files use the pattern `*.partial.<uuid>.mp4`
- Temp files are not considered valid library videos
- Shared filtering and cleanup lives in `util/media_files.py`
- On each Stage 5 run, stale partial outputs under the active upscale target are deleted before new work starts

For a concise maintainer-oriented summary, see `docs/maintenance_notes.md`.

## Notes

- Stage 2 (purge_weird) always runs, regardless of Stage 1 activity.
- Stage 3 always runs after purge. It first moves a script when its basename matches exactly one video in the same `AI` or `non_AI` lane within `videos/videos`, then fills in missing counterpart funscripts for matching processed/original video variants when it can do so unambiguously.
- Stage 4 always runs after scripts sync. It first normalizes any accidental `3_new_outbox` references in `favs.csv` back to `2_outbox`, then removes rows whose local favorite file no longer exists in either `2_outbox` or `3_new_outbox`, and finally resolves the Chrome profile named `Blair` from Chrome `Local State` and rewrites the `Fun Time Favs` folder on that profile's bookmarks bar from the remaining CSV `web_url` values.
- Stage 5 scans `1_sorted` and writes prompt JSON files under `videos/metadata/<2_outbox or 3_new_outbox>/.../<video-name>_topaz.json`, skipping any video that already has a JSON. A video whose scrape fails (for example, its source page was deleted) gets a sibling `<video-name>_topaz.json.failed` marker so it is not retried every run; delete the marker to force a retry. The current scraper only extracts Provider prompts.
- Stage 6 runs whenever pending work exists, even if nothing new arrived in `0_inbox` during that scheduler tick.
- Stage 6 is conservative by default: it processes at most `config.UPSCALE_BATCH_LIMIT` videos per run.
- If CPU usage is already above `config.CPU_BUSY_SKIP_THRESHOLD_PCT`, Evolver skips Stage 6 for that scheduler tick instead of competing with other work.
- If free disk space drops below `config.LOW_DISK_WARNING_GB`, Evolver stops Stage 6 early and warns instead of continuing toward a full disk.
- Stage 7 (non-AI upscale) always runs so it can check on its detached encode — suspending or resuming it to match the user's presence — but only launches a new one when the AI queue is drained, the user is away, and the box is otherwise quiet.
- Stage 8 always runs before the final correspondence check and flags likely duplicates in `1_sorted` by exact filesize.
- Stage 9 always runs as the final integrity check, and any mismatch popup points you to `evolver.log` for the full details.
- Errors are shown via Windows message box.
- Existing output checks prevent duplicate processing.
