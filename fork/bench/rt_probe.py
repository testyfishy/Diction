"""Probe GUFO's /v1/realtime: send a WAV at real-time pace, log event types and timing.
Stdlib-only WebSocket client. Prints event types, timing and word counts, never the words.

    python3 rt_probe.py URL WAV [commit_every_s]
"""
import base64, json, os, socket, struct, sys, threading, time, wave
from urllib.parse import urlparse

url, path = sys.argv[1], sys.argv[2]
commit_every = float(sys.argv[3]) if len(sys.argv) > 3 else 0
u = urlparse(url)
s = socket.create_connection((u.hostname, u.port or 80), timeout=30)
key = base64.b64encode(os.urandom(16)).decode()
s.sendall((f"GET {u.path}?{u.query} HTTP/1.1\r\nHost: {u.hostname}\r\nUpgrade: websocket\r\n"
           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
hdr = b""
while b"\r\n\r\n" not in hdr:
    hdr += s.recv(1)
print("handshake:", hdr.split(b"\r\n")[0].decode())
lock = threading.Lock()


def send(obj):
    data = json.dumps(obj).encode()
    mask = os.urandom(4)
    n = len(data)
    head = bytes([0x81]) + (bytes([0x80 | n]) if n < 126 else
                            bytes([0x80 | 126]) + struct.pack(">H", n) if n < 65536 else
                            bytes([0x80 | 127]) + struct.pack(">Q", n))
    with lock:
        s.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))


def recv_exact(n):
    b = b""
    while len(b) < n:
        c = s.recv(n - len(b))
        if not c:
            raise EOFError
        b += c
    return b


t0 = time.time()
audio_sent = [0.0]


def reader():
    try:
        while True:
            h = recv_exact(2)
            n = h[1] & 0x7F
            if n == 126:
                n = struct.unpack(">H", recv_exact(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", recv_exact(8))[0]
            payload = recv_exact(n)
            if h[0] & 0x0F == 8:
                print(f"{time.time() - t0:6.2f}s close"); return
            try:
                ev = json.loads(payload)
            except ValueError:
                continue
            words = {k: len(str(v).split()) for k, v in ev.items() if k in ("delta", "transcript", "text")}
            other = {k: v for k, v in ev.items() if k not in ("delta", "transcript", "text", "type", "event_id", "item_id")}
            print(f"{time.time() - t0:6.2f}s (audio {audio_sent[0]:5.2f}s) {ev.get('type')} words={words} "
                  f"{json.dumps(other)[:200]}")
    except (EOFError, OSError):
        pass


threading.Thread(target=reader, daemon=True).start()
w = wave.open(path)
rate = w.getframerate()
send({"type": "session.update", "session": {"input_audio_format": "pcm16", "input_audio_transcription": {"model": "qwen3-asr-1.7b"}}})
time.sleep(0.5)
chunk = int(rate * 0.1)
last_commit = 0.0
while True:
    frames = w.readframes(chunk)
    if not frames:
        break
    send({"type": "input_audio_buffer.append", "audio": base64.b64encode(frames).decode()})
    audio_sent[0] += len(frames) / 2 / rate
    if commit_every and audio_sent[0] - last_commit >= commit_every:
        send({"type": "input_audio_buffer.commit"}); last_commit = audio_sent[0]
    time.sleep(0.1)
print(f"{time.time() - t0:6.2f}s audio done ({audio_sent[0]:.1f}s), commit")
send({"type": "input_audio_buffer.commit"})
time.sleep(8)
