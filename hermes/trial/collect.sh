#!/bin/sh
# Copy the Diction trial's numbers out of the user journal before it rotates.
# Keeps metric lines only (timings, lengths, piece counts). Lookup-table swaps and
# backend errors are kept as bare markers without their words. Never transcript
# text, the pairing QR or the stream query.
set -eu
dir="$HOME/diction-trial"
mkdir -p "$dir"; chmod 700 "$dir"
umask 077
out="$dir/trial-$(date +%Y-%m).log"
journalctl --user -u diction-gateway -u speech-gateway --cursor-file="$dir/.cursor" \
    -o short-iso --no-pager 2>/dev/null |
  grep -E 'ws debug: (open|done|negotiated)|live: (cut|segment|final|decode)|ws proxy:|fuzzy:|Started diction-gateway' |
  sed -E -e 's/(ws debug: open) query=.*(offered_opus=)/\1 \2/' \
         -e 's/(fuzzy:).*/\1 swap/' \
         -e 's/(ws proxy:).*/\1 error/' \
         -e 's/(live: segment failed after [0-9]+ms):.*/\1/' >> "$out" || true
