#!/bin/sh
# A/B bench: old image vs new image as throwaway containers with auth off, run one at a
# time (a single-GPU backend serves one request at a time, so overlap would skew latency).
#
#   BACKEND_URL=http://127.0.0.1:PORT BACKEND_MODEL=MODEL [BACKEND_AUTH="Bearer x"] \
#     bench.sh OLD_IMAGE NEW_IMAGE CLIPS_DIR OUT.jsonl [REPS]
#
# OLD_IMAGE may be "-" to skip it. NEW_ENV adds env to the new container, e.g.
#   NEW_ENV="-e DICTION_SEGMENT_MIN_MS=8000"; PREVIEW=0 skips the live-text runs;
# PREVIEW_URL/PREVIEW_MODEL send partials to a separate backend.
set -eu
OLD=$1 NEW=$2 CLIPS=$3 OUT=$4 REPS=${5:-3}
: "${BACKEND_URL:?set BACKEND_URL}" "${BACKEND_MODEL:?set BACKEND_MODEL}"
CLIENT=${CLIENT:-$(dirname "$0")/../streamclient/streamclient}
LABEL=${LABEL:-new-seg}
WORK=$(mktemp -d)

start() { # name image port extra podman args...
	name=$1 img=$2 port=$3; shift 3
	mkdir -p "$WORK/$name"
	podman run -d --rm --name "$name" --network host \
		-e CUSTOM_BACKEND_URL="$BACKEND_URL" -e CUSTOM_BACKEND_MODEL="$BACKEND_MODEL" \
		-e CUSTOM_BACKEND_AUTH="${BACKEND_AUTH:-}" -e DICTION_GATEWAY_AUTH=off \
		-e GATEWAY_PORT="$port" -v "$WORK/$name:/data:Z" "$@" "$img" >/dev/null
	for _ in $(seq 1 30); do curl -sf "127.0.0.1:$port/health" >/dev/null && break; sleep 1; done
	sleep 3 # first backend health probe
}
stop() { podman stop -t 2 "$1" >/dev/null 2>&1 || true; }

run() { # label port file [client flags]
	label=$1 port=$2 file=$3; shift 3
	"$CLIENT" -url "ws://127.0.0.1:$port/v1/audio/stream" -file "$file" "$@" | sed "s/^{/{\"label\":\"$label\",/" >>"$OUT" || true
}

: >"$OUT"
# shellcheck disable=SC2086
start dg-new "$NEW" 8081 -e DICTION_SEGMENTED_FINAL=true -e DICTION_DEBUG_STREAM=true -e DICTION_PREVIEW=chunked \
	${PREVIEW_URL:+-e DICTION_PREVIEW_URL=$PREVIEW_URL} ${PREVIEW_MODEL:+-e DICTION_PREVIEW_MODEL=$PREVIEW_MODEL} ${NEW_ENV:-}
[ "$OLD" != "-" ] && start dg-old "$OLD" 8082
# Interleaved: old and new take turns on each clip, so anything else loading the GPU
# during the bench slows both alike. Requests still never overlap.
for i in $(seq 1 "$REPS"); do
	for c in "$CLIPS"/*.ogg; do
		[ "$OLD" != "-" ] && run old 8082 "$c"
		run "$LABEL" 8081 "$c"
	done
done
[ "$OLD" != "-" ] && stop dg-old
if [ "${PREVIEW:-1}" = 1 ]; then
	# Live text, as the coming app build would ask for it (Opus; PREVIEW_PCM=1 adds PCM).
	for i in $(seq 1 "$REPS"); do for c in "$CLIPS"/*.ogg; do run new-preview 8081 "$c" -preview; done; done
	if [ "${PREVIEW_PCM:-0}" = 1 ]; then
		for i in $(seq 1 "$REPS"); do for c in "$CLIPS"/*.wav; do run new-preview-pcm 8081 "$c" -preview; done; done
	fi
fi
podman logs dg-new >"$OUT.new.log" 2>&1
stop dg-new
rm -rf "$WORK"
