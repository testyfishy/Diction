#!/bin/sh
# Reproduces the capped-stderr bug (FORK-CHANGELOG.md, v15.0-fork.2) and checks the fix.
# A wrapper named ffmpeg, earlier on PATH, prints about 200 bytes a second to stderr and runs
# the real ffmpeg, like a decoder that warns throughout a session. Each image plays one clip
# of 25 s or more; the affected one logs "live: decode incomplete" and falls back to the
# whole recording, the fixed one finishes from pieces.
#
#   BACKEND_URL=http://127.0.0.1:PORT BACKEND_MODEL=MODEL noisy_decoder.sh CLIP.ogg IMAGE [IMAGE...]
set -eu
CLIP=$1; shift
: "${BACKEND_URL:?set BACKEND_URL}" "${BACKEND_MODEL:?set BACKEND_MODEL}"
CLIENT=${CLIENT:-$(dirname "$0")/../streamclient/streamclient}
WORK=$(mktemp -d)
cat >"$WORK/ffmpeg" <<'EOF'
#!/bin/sh
( while :; do printf 'warning: %0190d\n' 0 >&2; sleep 1; done ) &
n=$!
/usr/bin/ffmpeg "$@"
rc=$?
kill $n 2>/dev/null
exit $rc
EOF
chmod +x "$WORK/ffmpeg"
for img in "$@"; do
	podman rm -f dg-noisy >/dev/null 2>&1 || true
	# One container at a time: a :Z mount belongs to the last container that took it.
	podman run -d --name dg-noisy --network host -e GATEWAY_PORT=8093 \
		-e CUSTOM_BACKEND_URL="$BACKEND_URL" -e CUSTOM_BACKEND_MODEL="$BACKEND_MODEL" \
		-e CUSTOM_BACKEND_AUTH="${BACKEND_AUTH:-}" -e DICTION_GATEWAY_AUTH=off \
		-e DICTION_SEGMENTED_FINAL=true -e DICTION_DEBUG_STREAM=true \
		-v "$WORK/ffmpeg:/usr/local/bin/ffmpeg:ro,Z" "$img" >/dev/null
	for _ in $(seq 1 30); do curl -sf -m 2 127.0.0.1:8093/health >/dev/null && break; sleep 1; done
	sleep 3
	"$CLIENT" -url ws://127.0.0.1:8093/v1/audio/stream -file "$CLIP" >/dev/null 2>&1 || true
	echo "== $img"
	podman logs dg-noisy 2>&1 | grep -E "live: (final|decode incomplete)" | sed -E 's/^[0-9/]+ [0-9:]+ //' | cut -c1-140
	podman rm -f dg-noisy >/dev/null 2>&1
done
rm -rf "$WORK"
