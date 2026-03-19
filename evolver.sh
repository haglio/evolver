#!/usr/bin/env bash
set -Eeuo pipefail

###############################################################################
# evolver.sh
#
# New behavior (efficient / idempotent):
#   Stage 1) Move videos from "0_inbox/<source>/" -> "1_sorted/<source>/<orientation>/"
#   Stage 2) Upscale videos from "1_sorted/<source>/<orientation>/" into:
#              "2_outbox/upscaled_by_orientation/{landscape,portrait}/<source>/"
#           Apply Apollo frame interpolation to 60 fps and Gaia CG 4x upscale.
#           Skip if output already exists in:
#              - outbox/upscaled_by_orientation/landscape/<source>/
#              - outbox/upscaled_by_orientation/portrait/<source>/
#              - outbox/kinda_weird/   <-- your extra "do not reconvert" folder
###############################################################################

### ===================== CONFIG =====================

BASE_DIR="/c/path/to/suite-root"
PROJECT_DIR="$BASE_DIR/projects/evolver"
AI_DIR="$BASE_DIR/videos/videos/2D/AI"

INBOX_DIR="$AI_DIR/0_inbox"
SORTED_DIR="$AI_DIR/1_sorted"
OUTBOX_DIR="$AI_DIR/2_outbox"

OUT_UPSCALED_DIR="$OUTBOX_DIR/upscaled_by_orientation"
WEIRD_DIR="$OUTBOX_DIR/kinda_weird"   # extra folder to check for existing *_topaz.mp4

SOURCES=(provider provider2 provider3)

FFMPEG="/c/Program Files/Topaz Labs LLC/Topaz Video/ffmpeg.exe"

export TVAI_MODEL_DIR='C:\ProgramData\Topaz Labs LLC\Topaz Video\models'
export TVAI_MODEL_DATA_DIR='C:\ProgramData\Topaz Labs LLC\Topaz Video\models'

VIDEO_FIND_EXPR=( -iname '*.mp4' -o -iname '*.mkv' -o -iname '*.mov' -o -iname '*.avi' -o -iname '*.wmv' -o -iname '*.webm' -o -iname '*.m4v' )

# Optional hygiene: remove empty dirs left behind inside 0_inbox/<source> after moves
CLEAN_EMPTY_INBOX_DIRS=1

### =================== END CONFIG ===================

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
die() { log "ERROR: $*"; exit 1; }
LOG_FILE="$PROJECT_DIR/evolver.log"
exec >>"$LOG_FILE" 2>&1

command -v ffprobe >/dev/null 2>&1 || die "ffprobe not found in PATH. Install ffmpeg (which includes ffprobe)."
[[ -x "$FFMPEG" ]] || die "Topaz ffmpeg not found/executable at: $FFMPEG"

mkdir -p "$SORTED_DIR" "$OUT_UPSCALED_DIR"/{landscape,portrait} "$WEIRD_DIR"

# Ensure per-source outbox dirs exist too
for s in "${SOURCES[@]}"; do
  mkdir -p "$OUT_UPSCALED_DIR/landscape/$s" "$OUT_UPSCALED_DIR/portrait/$s"
done

# Move without overwriting: if dest exists, DELETE src (per your preference)
move_unique() {
  local src="$1"
  local dest="$2"

  if [[ ! -e "$dest" ]]; then
    mv -- "$src" "$dest"
    printf '%s\n' "$dest"
    return
  fi

  log "COLLISION (deleting inbox file): $src  ->  $dest"
  rm -f -- "$src"
  printf '%s\n' ""
}

# Determine orientation from first video stream, with rotation handling
get_orientation() {
  local file="$1"
  local w h rot

  w="$(ffprobe -v error -select_streams v:0 -show_entries stream=width  -of csv=p=0 "$file" 2>/dev/null || true)"
  h="$(ffprobe -v error -select_streams v:0 -show_entries stream=height -of csv=p=0 "$file" 2>/dev/null || true)"
  rot="$(ffprobe -v error -select_streams v:0 -show_entries stream_tags=rotate -of csv=p=0 "$file" 2>/dev/null || true)"

  if [[ -z "${w}" || -z "${h}" ]]; then
    echo "unknown"
    return
  fi

  if [[ "${rot:-}" =~ ^-?[0-9]+$ ]] && (( (rot % 180) != 0 )); then
    local tmp="$w"; w="$h"; h="$tmp"
  fi

  if (( w > h )); then
    echo "landscape"
  elif (( h > w )); then
    echo "portrait"
  else
    echo "landscape"
  fi
}

# Temp output MUST end with .mp4 so ffmpeg can choose muxer by extension
tmp_for_output_mp4() {
  local out="$1"         # final output ends with .mp4
  local stem="${out%.*}"
  local tmp="${stem}.partial.$$.$RANDOM.mp4"
  local n=1
  while [[ -e "$tmp" ]]; do
    tmp="${stem}.partial.$$.$RANDOM.$n.mp4"
    n=$((n+1))
  done
  echo "$tmp"
}

# Check if *_topaz.mp4 already exists in any “already processed” location
# NOTE: now checks inside per-source outbox dirs.
already_processed() {
  local source="$1"
  local fname="$2"  # like: <stem>_topaz.mp4

  [[ -s "$OUT_UPSCALED_DIR/landscape/$source/$fname" ]] && return 0
  [[ -s "$OUT_UPSCALED_DIR/portrait/$source/$fname" ]] && return 0
  [[ -s "$WEIRD_DIR/$fname" ]] && return 0

  return 1
}

###############################################################################
# Stage 1: 0_inbox -> 1_sorted
###############################################################################
log "=== Stage 1: 0_inbox -> 1_sorted (move) ==="
log "INBOX:  $INBOX_DIR"
log "SORTED: $SORTED_DIR"

moved_count=0
deleted_dups=0
skipped_unknown=0

for source in "${SOURCES[@]}"; do
  src_root="$INBOX_DIR/$source"
  [[ -d "$src_root" ]] || { log "Source missing (skipping): $src_root"; continue; }

  log "--- Sorting source: $source ---"

  while IFS= read -r -d '' rel; do
    rel="${rel#./}"
    src="$src_root/$rel"

    orient="$(get_orientation "$src")"
    case "$orient" in
      portrait|landscape) ;;
      *)
        log "UNKNOWN (leaving in inbox): $src"
        skipped_unknown=$((skipped_unknown+1))
        continue
        ;;
    esac

    dest="$SORTED_DIR/$source/$orient/$rel"
    mkdir -p "$(dirname -- "$dest")"

    log "MOVE  [$source/$orient] $rel"
    final_dest="$(move_unique "$src" "$dest")"

    if [[ -n "${final_dest:-}" ]]; then
      moved_count=$((moved_count+1))
    else
      deleted_dups=$((deleted_dups+1))
    fi

  done < <(cd "$src_root" && find . -type f \( "${VIDEO_FIND_EXPR[@]}" \) -print0)

  if (( CLEAN_EMPTY_INBOX_DIRS )); then
    find "$src_root" -mindepth 1 -type d -empty -delete 2>/dev/null || true
  fi
done

log "Stage 1 done. Moved: $moved_count, Deleted collisions: $deleted_dups, Unknown skipped: $skipped_unknown"
log

# Short-circuit: if nothing new was moved into sorted, don't scan/upscale sorted
if (( moved_count == 0 )); then
  log "No new videos moved from inbox. Skipping Stage 2."
  exit 0
fi

###############################################################################
# Stage 2: upscale from 1_sorted
###############################################################################
log "=== Stage 2: upscale from 1_sorted ==="
log "OUT: $OUT_UPSCALED_DIR/{landscape,portrait}/<source>/"
log "Also skip if exists in: $WEIRD_DIR"

processed=0
already_done=0
failed=0

for source in "${SOURCES[@]}"; do
  for orient in landscape portrait; do
    in_root="$SORTED_DIR/$source/$orient"
    [[ -d "$in_root" ]] || continue

    log "--- Upscaling: $source / $orient ---"

    while IFS= read -r -d '' in; do
      base="$(basename -- "$in")"
      stem="${base%.*}"
      out_name="${stem}_topaz.mp4"

      if already_processed "$source" "$out_name"; then
        log "Skip (already processed somewhere): $source/$out_name"
        already_done=$((already_done+1))
        continue
      fi

      out="$OUT_UPSCALED_DIR/$orient/$source/$out_name"
      mkdir -p "$(dirname -- "$out")"
      tmp="$(tmp_for_output_mp4 "$out")"

      log "Process: $(basename -- "$in") -> $out_name  [$orient/$source]"

      if "$FFMPEG" -hide_banner -nostdin -y -strict 2 -hwaccel cuda \
          -i "$in" \
          -sws_flags spline+accurate_rnd+full_chroma_int \
          -filter_complex "tvai_fi=model=apo-8:slowmo=1:fps=60:rdt=0.01:device=0:vram=1:instances=1,tvai_up=model=gcg-5:scale=4:device=0:vram=1:instances=1" \
          -c:v hevc_nvenc \
          -profile:v main \
          -pix_fmt yuv420p \
          -b_ref_mode disabled \
          -tag:v hvc1 \
          -g 30 \
          -preset p7 \
          -tune hq \
          -rc constqp \
          -qp 17 \
          -rc-lookahead 20 \
          -spatial_aq 1 \
          -aq-strength 15 \
          -b:v 0 \
          -an \
          -map_metadata 0 \
          -map_metadata:s:v 0:s:v \
          -fps_mode:v cfr \
          -movflags frag_keyframe+empty_moov+delay_moov+use_metadata_tags+write_colr \
          -bf 0 \
          -metadata "videoai=Processed using apo-8 for 60 fps interpolation and gcg-5 for 4x upscale" \
          -f mp4 \
          "$tmp"
      then
        if [[ -s "$tmp" ]]; then
          mv -f -- "$tmp" "$out"
          processed=$((processed+1))
          log "Wrote: $out"
        else
          rm -f -- "$tmp" || true
          failed=$((failed+1))
          log "FAILED (empty output): $in"
        fi
      else
        rm -f -- "$tmp" || true
        failed=$((failed+1))
        log "FAILED (ffmpeg error): $in"
      fi

    done < <(find "$in_root" -type f \( "${VIDEO_FIND_EXPR[@]}" \) -print0)
  done
done

log
log "Done."
log "Upscaled: $processed"
log "Skipped (already processed): $already_done"
log "Failed: $failed"

(( failed == 0 )) || exit 1
