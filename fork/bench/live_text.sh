#!/bin/sh
# Live-text check: one throwaway gateway (pieces + live text, auth off) plays every clip
# twice per pass, once as a client that does not ask for live text and once as one that
# does, taking turns so both see the same backend load. Requests never overlap.
#
#   BACKEND_URL=http://127.0.0.1:PORT BACKEND_MODEL=MODEL [BACKEND_AUTH="Bearer x"] \
#     live_text.sh IMAGE CLIPS_DIR OUT.jsonl [PASSES]
#
# Optional: PREVIEW_URL / PREVIEW_MODEL (separate backend for drafts), INTERVAL_MS
# (DICTION_PREVIEW_INTERVAL_MS, default 250), FIRST_MIN_MS (default 15000), PORT (8091).
# Then: python3 live_text_report.py OUT.jsonl CLIPS_DIR
set -eu
IMAGE=$1 CLIPS=$2 OUT=$3 PASSES=${4:-2}
: "${BACKEND_URL:?set BACKEND_URL}" "${BACKEND_MODEL:?set BACKEND_MODEL}"
CLIENT=${CLIENT:-$(dirname "$0")/../streamclient/streamclient}
PORT=${PORT:-8091}
NAME=dg-live-text

podman rm -f "$NAME" >/dev/null 2>&1 || true
# shellcheck disable=SC2086
podman run -d --name "$NAME" --network host -e GATEWAY_PORT="$PORT" \
	-e CUSTOM_BACKEND_URL="$BACKEND_URL" -e CUSTOM_BACKEND_MODEL="$BACKEND_MODEL" \
	-e CUSTOM_BACKEND_AUTH="${BACKEND_AUTH:-}" -e DICTION_GATEWAY_AUTH=off \
	-e DICTION_SEGMENTED_FINAL=true -e DICTION_SEGMENT_FIRST_MIN_MS="${FIRST_MIN_MS:-15000}" \
	-e DICTION_PREVIEW=chunked -e DICTION_PREVIEW_INTERVAL_MS="${INTERVAL_MS:-250}" \
	-e DICTION_DEBUG_STREAM=true \
	${PREVIEW_URL:+-e DICTION_PREVIEW_URL=$PREVIEW_URL} ${PREVIEW_MODEL:+-e DICTION_PREVIEW_MODEL=$PREVIEW_MODEL} \
	"$IMAGE" >/dev/null
for _ in $(seq 1 30); do curl -sf -m 2 "127.0.0.1:$PORT/health" >/dev/null && break; sleep 1; done
sleep 3 # first backend health probe

# What a client sees before it decides to ask for live text.
echo "health: $(curl -s -m 5 "127.0.0.1:$PORT/health")"
echo "capabilities: $(curl -s -m 5 "127.0.0.1:$PORT/v1/models" | sed -n 's/.*"capabilities":\({[^}]*}\).*/\1/p')"

run() { # label file [client flags]
	label=$1 file=$2; shift 2
	"$CLIENT" -url "ws://127.0.0.1:$PORT/v1/audio/stream" -file "$file" "$@" 2>/dev/null |
		sed "s/^{/{\"label\":\"$label\",/" >>"$OUT" || true
	sleep 2
}

: >"$OUT"
n=0
for _ in $(seq 1 "$PASSES"); do
	for c in "$CLIPS"/*.ogg; do
		n=$((n + 1))
		if [ $((n % 2)) = 0 ]; then
			run off "$c"; run drafts "$c" -preview
		else
			run drafts "$c" -preview; run off "$c"
		fi
	done
done
# Timings and counts only: the debug log never holds audio, text or keys.
podman logs "$NAME" 2>&1 | grep -E "live: |ws debug: (negotiated|done_to_text)" | sed -E 's/^[0-9/]+ [0-9:]+ //' >"$OUT.log"
podman rm -f "$NAME" >/dev/null 2>&1
echo "wrote $OUT and $OUT.log"
