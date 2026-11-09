#!/bin/sh
# Copy the Diction trial's numbers out of the user journal before it rotates.
# Keeps only metric lines (timings, lengths, piece counts) and lookup-table swaps;
# never transcript text, the pairing QR or the stream query.
set -eu
dir="$HOME/diction-trial"
mkdir -p "$dir"; chmod 700 "$dir"
umask 077
out="$dir/trial-$(date +%Y-%m).log"
journalctl --user -u diction-gateway -u speech-gateway --cursor-file="$dir/.cursor" \
    -o short-iso --no-pager 2>/dev/null |
  grep -E 'ws debug: (open|done|negotiated)|live: (cut|segment|final|decode)|ws proxy:|fuzzy:|Started diction-gateway' |
  sed -E 's/(ws debug: open) query=.*(offered_opus=)/\1 \2/' >> "$out" || true
