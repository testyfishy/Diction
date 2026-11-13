#!/bin/sh
# Before/after: the upstream gateway image against a fork image with pieces and live text,
# as two throwaway containers (auth off) taking turns on every clip, so both see the same
# backend load. The upstream client does not ask for live text; the fork client does.
#
#   BACKEND_URL=http://127.0.0.1:PORT BACKEND_MODEL=MODEL [BACKEND_AUTH="Bearer x"] \
#     ab_upstream.sh UPSTREAM_IMAGE FORK_IMAGE CLIPS_DIR OUT.jsonl [PASSES]
#
# Optional: PREVIEW_URL / PREVIEW_MODEL, INTERVAL_MS (default 250), FIRST_MIN_MS (15000).
# Then: python3 ab_report.py OUT.jsonl CLIPS_DIR
set -eu
UP=$1 FORK=$2 CLIPS=$3 OUT=$4 PASSES=${5:-2}
: "${BACKEND_URL:?set BACKEND_URL}" "${BACKEND_MODEL:?set BACKEND_MODEL}"
CLIENT=${CLIENT:-$(dirname "$0")/../streamclient/streamclient}

start() { # name image port extra podman args...
	name=$1 img=$2 port=$3; shift 3
	podman rm -f "$name" >/dev/null 2>&1 || true
	podman run -d --name "$name" --network host -e GATEWAY_PORT="$port" \
		-e CUSTOM_BACKEND_URL="$BACKEND_URL" -e CUSTOM_BACKEND_MODEL="$BACKEND_MODEL" \
		-e CUSTOM_BACKEND_AUTH="${BACKEND_AUTH:-}" -e DICTION_GATEWAY_AUTH=off "$@" "$img" >/dev/null
	for _ in $(seq 1 30); do curl -sf -m 2 "127.0.0.1:$port/health" >/dev/null && break; sleep 1; done
	echo "$name: $(curl -s -m 5 "127.0.0.1:$port/health")"
}
run() { # label port file [client flags]
	label=$1 port=$2 file=$3; shift 3
	"$CLIENT" -url "ws://127.0.0.1:$port/v1/audio/stream" -file "$file" "$@" 2>/dev/null |
		sed "s/^{/{\"label\":\"$label\",/" >>"$OUT" || true
	sleep 2
}

start dg-ab-upstream "$UP" 8094
# shellcheck disable=SC2086
start dg-ab-fork "$FORK" 8095 -e DICTION_SEGMENTED_FINAL=true \
	-e DICTION_SEGMENT_FIRST_MIN_MS="${FIRST_MIN_MS:-15000}" -e DICTION_PREVIEW=chunked \
	-e DICTION_PREVIEW_INTERVAL_MS="${INTERVAL_MS:-250}" -e DICTION_DEBUG_STREAM=true \
	${PREVIEW_URL:+-e DICTION_PREVIEW_URL=$PREVIEW_URL} ${PREVIEW_MODEL:+-e DICTION_PREVIEW_MODEL=$PREVIEW_MODEL}
sleep 3 # first backend health probe

: >"$OUT"
n=0
for _ in $(seq 1 "$PASSES"); do
	for c in "$CLIPS"/*.ogg; do
		n=$((n + 1))
		if [ $((n % 2)) = 0 ]; then
			run upstream 8094 "$c"; run fork 8095 "$c" -preview
		else
			run fork 8095 "$c" -preview; run upstream 8094 "$c"
		fi
	done
done
podman logs dg-ab-fork 2>&1 | grep -E "live: " | sed -E 's/^[0-9/]+ [0-9:]+ //' >"$OUT.log"
podman rm -f dg-ab-upstream dg-ab-fork >/dev/null 2>&1
echo "wrote $OUT and $OUT.log"
