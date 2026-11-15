"""
Phase 2 - Step 2: OFDM over a real light link
Author: Sanjay Balasundaram

Mac headphone jack -> BC547 LED driver -> white LED -> light ->
BPW34 photodiode -> LM358 buffer -> USB sound card mic input -> this program

The program:
  1. builds a DCO-style real OFDM signal in the audio band (1-8 kHz)
  2. plays it out of the Mac's headphone jack (drives the LED)
  3. records the USB sound card at the same time
  4. finds the packet, equalizes with a pilot symbol, decodes the text

Run:
  python ofdm_light.py            # send the message once through light
  python ofdm_light.py --list     # show audio devices
  python ofdm_light.py --selftest # test the whole chain in software only
  python ofdm_light.py --runs 10  # send 10 packets and count successes
"""
import os
import sys
import threading
import time
import numpy as np

FS      = 48000            # sample rate
N_FFT   = 256              # 187.5 Hz subcarrier spacing
N_CP    = 64
# 1.1 kHz .. 7.9 kHz, skipping 3 kHz and 6 kHz: the USB sound card puts
# electrical noise on multiples of 1 kHz (its 1 ms USB frame rate)
NOISY   = (16, 32)
DATA_SC = np.array([k for k in range(6, 43) if k not in NOISY])
MESSAGE = "Hello Li-Fi from Sanjay"
AMP     = 0.6              # output peak level (0..1)
REPEAT  = 24               # copies of the packet; averaged at the receiver
OUT     = "results"

rng_pilot = np.random.default_rng(7)
PILOT = np.exp(1j * (np.pi / 4 + np.pi / 2 * rng_pilot.integers(0, 4, len(DATA_SC))))


# ---------------- bits / QPSK ----------------
def text_to_bits(text):
    return np.unpackbits(np.frombuffer(text.encode(), dtype=np.uint8))

def bits_to_text(bits):
    bits = bits[: len(bits) // 8 * 8]
    raw = np.packbits(bits).tobytes().decode(errors="replace")
    return "".join(c if c.isprintable() else "?" for c in raw)

def qpsk_mod(bits):
    b = bits.reshape(-1, 2).astype(int)
    return ((1 - 2 * b[:, 0]) + 1j * (1 - 2 * b[:, 1])) / np.sqrt(2)

def qpsk_demod(sym):
    return np.column_stack([sym.real < 0, sym.imag < 0]).astype(np.uint8).ravel()


# ---------------- sync chirp ----------------
def chirp(dur=0.1, f0=1000, f1=8000):
    t = np.arange(int(dur * FS)) / FS
    k = (f1 - f0) / dur
    return np.sin(2 * np.pi * (f0 * t + 0.5 * k * t * t)) * np.hanning(len(t))

CHIRP = chirp()
GAP = int(0.02 * FS)


# ---------------- transmitter ----------------
def ofdm_symbols(blocks):
    X = np.zeros((len(blocks), N_FFT), dtype=complex)
    X[:, DATA_SC] = blocks
    X[:, N_FFT - DATA_SC] = np.conj(blocks)          # Hermitian -> real signal
    x = np.fft.ifft(X, axis=1).real
    x = np.hstack([x[:, -N_CP:], x])                 # cyclic prefix
    return x.ravel()

def build_packet(text=MESSAGE):
    bits = text_to_bits(text)
    per = 2 * len(DATA_SC)
    nbits = len(bits)
    bits = np.concatenate([bits, np.zeros((-nbits) % per, dtype=np.uint8)])
    data = qpsk_mod(bits).reshape(-1, len(DATA_SC))
    frame = np.vstack([PILOT, data])                 # one copy = pilot + data
    body = ofdm_symbols(np.vstack([frame] * REPEAT))
    body = body / np.max(np.abs(body))
    ch = CHIRP / np.max(np.abs(CHIRP))
    silence = np.zeros(int(0.3 * FS))
    sig = np.concatenate([silence, ch, np.zeros(GAP), body, silence]) * AMP
    return sig.astype(np.float32), nbits, len(data)


# ---------------- receiver ----------------
def xcorr(a, b):
    n = len(a) + len(b)
    nfft = 1 << (n - 1).bit_length()
    return np.fft.irfft(np.fft.rfft(a, nfft) * np.conj(np.fft.rfft(b, nfft)), nfft)[: len(a)]

def _med3(v):
    out = v.copy()
    for i in range(1, len(v) - 1):
        out[i] = np.median(v[i - 1:i + 2])
    return out

def _smooth(v, w=7):
    """median-of-3 (kills a single glitch) then a moving average (cuts noise)"""
    v = _med3(v)
    k = np.ones(w)
    return np.convolve(v, k, "same") / np.convolve(np.ones_like(v), k, "same")

PILOT_WAVE = None

def decode_tracking(rx, nbits, nsym):
    """Receiver with per-copy timing tracking.

    The Mac's headphone output and the USB card run on different clocks, and
    macOS can nudge the timing mid-recording.  So instead of assuming a
    straight-line drift, every copy's pilot is located on its own, the timing
    of each data symbol is interpolated between pilots, and the leftover
    fraction of a sample is removed as a phase ramp before averaging.
    """
    global PILOT_WAVE
    if PILOT_WAVE is None:
        w = ofdm_symbols(PILOT[None, :])
        PILOT_WAVE = w / np.linalg.norm(w)
    rx = rx - np.mean(rx)
    c = np.abs(xcorr(rx, CHIRP))
    start = int(np.argmax(c))
    peak_ratio = c[start] / (np.median(c) + 1e-12)
    L = N_FFT + N_CP
    per = nsym + 1
    s0 = start + len(CHIRP) + GAP
    k_idx = DATA_SC.astype(float)

    # 1) find each copy's pilot (integer + parabolic fraction)
    d = np.zeros(REPEAT)
    prev = 0
    for k in range(REPEAT):
        base = s0 + k * per * L
        lo, hi = prev - 30, prev + 31
        vals = np.array([abs(np.dot(rx[base + j: base + j + L], PILOT_WAVE))
                         if base + j >= 0 and base + j + L <= len(rx) else 0
                         for j in range(lo, hi)])
        i = int(np.argmax(vals))
        frac = 0.0
        if 0 < i < len(vals) - 1:
            y0, y1, y2 = vals[i - 1], vals[i], vals[i + 1]
            den = y0 - 2 * y1 + y2
            frac = 0.5 * (y0 - y2) / den if den != 0 else 0.0
        d[k] = lo + i + frac
        prev = int(round(d[k]))
    d = _smooth(d)

    def extract(dk):
        """FFT of every symbol, aligned to a common time reference."""
        g = np.arange(REPEAT * per)
        dg = np.interp(g, np.arange(REPEAT) * per, dk)       # timing of every symbol
        a = s0 + g * L + dg + N_CP                             # true start after CP
        n0 = np.round(a).astype(int) - 8                       # start 8 samples inside CP
        e = a - n0
        Y = np.empty((len(g), len(DATA_SC)), dtype=complex)
        for j in range(len(g)):
            seg = rx[n0[j]: n0[j] + N_FFT]
            if len(seg) < N_FFT:
                seg = np.pad(seg, (0, N_FFT - len(seg)))
            Y[j] = np.fft.fft(seg)[DATA_SC] * np.exp(2j * np.pi * k_idx * e[j] / N_FFT)
        return Y.reshape(REPEAT, per, len(DATA_SC))

    # 2) refine each copy's timing from the pilot phase slope (one pass)
    Y = extract(d)
    Hk = Y[:, 0, :] / PILOT
    Href = Hk.mean(axis=0)
    adj = np.diff(DATA_SC) == 1
    Q = Hk * np.conj(Href)
    slope = np.angle(np.sum((Q[:, 1:] * np.conj(Q[:, :-1]))[:, adj], axis=1))
    d = d + _smooth(slope * N_FFT / (2 * np.pi))                # slope -> samples
    Y = extract(d)

    # 3) common phase per copy, one clean channel estimate, equalize, average
    Hk = Y[:, 0, :] / PILOT
    Href = Hk.mean(axis=0)
    ph = np.angle(np.sum(Hk * np.conj(Href), axis=1))
    C = np.exp(-1j * ph)[:, None, None]
    Y = Y * C
    H = (Y[:, 0, :] / PILOT).mean(axis=0)
    eq_all = Y[:, 1:, :] / H
    # weight copies by how clean their pilot is (drops a glitched copy)
    perr = np.mean(np.abs(Y[:, 0, :] / PILOT - H) ** 2, axis=1) + 1e-12
    w = (1 / perr) / np.sum(1 / perr)
    eq = np.tensordot(w, eq_all, axes=1)
    ref = (np.sign(eq.real) + 1j * np.sign(eq.imag)) / np.sqrt(2)
    evm = np.mean(np.abs(eq / np.sqrt(np.mean(np.abs(eq) ** 2)) - ref) ** 2)
    single = qpsk_demod(eq_all[0].ravel())[:nbits]
    bits = qpsk_demod(eq.ravel())[:nbits]
    return bits, eq, H, peak_ratio, evm, single


def decode_linear(rx, nbits, nsym):
    rx = rx - np.mean(rx)
    c = np.abs(xcorr(rx, CHIRP))
    start = int(np.argmax(c))
    peak_ratio = c[start] / (np.median(c) + 1e-12)
    sym_len = N_FFT + N_CP
    per = nsym + 1
    total = per * REPEAT
    best = None
    # try a few timing offsets inside the cyclic prefix, keep the cleanest
    for off in range(-12, 13, 2):
        s0 = start + len(CHIRP) + GAP + off
        seg = rx[s0: s0 + total * sym_len]
        if len(seg) < total * sym_len:
            continue
        r = seg.reshape(-1, sym_len)[:, N_CP:]
        Y = np.fft.fft(r, axis=1)[:, DATA_SC].reshape(REPEAT, per, len(DATA_SC))
        Hk = Y[:, 0, :] / PILOT                       # channel from each copy's pilot
        # --- clock-drift correction ---
        # the two sound devices run on slightly different clocks, so each copy
        # arrives a tiny bit later than the last -> a phase slope across subcarriers.
        Q = Hk * np.conj(Hk.mean(axis=0))
        adj = np.diff(DATA_SC) == 1                   # neighbouring subcarriers only
        slope = np.angle(np.sum((Q[:, 1:] * np.conj(Q[:, :-1]))[:, adj], axis=1))
        kk = np.arange(REPEAT)
        slope = np.polyval(np.polyfit(kk, slope, 1), kk)          # drift is linear in time
        m = DATA_SC - DATA_SC[0]
        ph0 = np.angle(np.sum(Q * np.exp(-1j * slope[:, None] * m), axis=1))
        ph0 = np.polyval(np.polyfit(kk, np.unwrap(ph0), 1), kk)
        C = np.exp(-1j * (ph0[:, None] + slope[:, None] * m))     # undo the drift
        Hs = (Hk * C).mean(axis=0)                    # one clean channel estimate
        eq_all = Y[:, 1:, :] * C[:, None, :] / Hs     # equalize every copy
        eq = eq_all.mean(axis=0)                      # average the copies
        ref = (np.sign(eq.real) + 1j * np.sign(eq.imag)) / np.sqrt(2)
        evm = np.mean(np.abs(eq / np.sqrt(np.mean(np.abs(eq) ** 2)) - ref) ** 2)
        if best is None or evm < best[0]:
            best = (evm, eq, Hs, eq_all)
    evm, eq, H, eq_all = best
    single = qpsk_demod(eq_all[0].ravel())[:nbits]     # what ONE copy alone would give
    bits = qpsk_demod(eq.ravel())[:nbits]
    return bits, eq, H, peak_ratio, evm, single


def decode(rx, nbits, nsym):
    """Try both receivers and keep whichever gives the cleaner constellation.
    decode_linear   : assumes a steady clock drift (best for very noisy but stable links)
    decode_tracking : re-times every copy on its own (best when macOS nudges the clock)
    """
    a = decode_linear(rx, nbits, nsym)
    b = decode_tracking(rx, nbits, nsym)
    return a if a[4] <= b[4] else b


# ---------------- audio I/O ----------------
def find_device(sd, words, kind):
    for i, d in enumerate(sd.query_devices()):
        ok = d["max_input_channels"] > 0 if kind == "in" else d["max_output_channels"] > 0
        if ok and any(w.lower() in d["name"].lower() for w in words):
            return i, d["name"]
    return None, None

def play_and_record(sig):
    import sounddevice as sd
    in_id, in_name = find_device(sd, ["usb", "pnp", "audio device"], "in")
    out_id, out_name = find_device(sd, ["headphone", "external"], "out")
    if in_id is None:
        sys.exit("USB sound card input not found. Run with --list and check it is plugged in.")
    if out_id is None:
        sys.exit("Headphone output not found. Plug the AUX cable into the Mac's headphone jack.")
    print(f" Output : {out_name}")
    print(f" Input  : {in_name}")

    chunks = []
    stop = threading.Event()

    def rec_thread():
        with sd.InputStream(device=in_id, channels=1, samplerate=FS, dtype="float32") as st:
            while not stop.is_set():
                data, _ = st.read(1024)
                chunks.append(data[:, 0].copy())

    t = threading.Thread(target=rec_thread)
    t.start()
    time.sleep(0.3)
    stereo = np.column_stack([sig, sig])
    sd.play(stereo, FS, device=out_id, blocking=True)
    time.sleep(0.3)
    stop.set()
    t.join()
    return np.concatenate(chunks)


# ---------------- software-only test ----------------
def fake_channel(sig):
    rng = np.random.default_rng(3)
    x = np.concatenate([np.zeros(rng.integers(2000, 9000)), sig])
    # 40 ppm sample-clock mismatch between the two sound devices
    t = np.arange(0, len(x) - 1, 1 + 100e-6)
    x = np.interp(t, np.arange(len(x)), x)
    x = np.convolve(x, [0.6, 0.3, 0.1])               # LED / photodiode smoothing
    x = 0.05 * x + 0.3                                  # weak light + DC offset
    n = rng.normal(0, 0.012, len(x))
    n[::1700] += 0.03                                   # periodic electrical spikes
    return x + n


def report(rx, nbits, nsym, sent_bits):
    bits, eq, H, pr, evm, single = decode(rx, nbits, nsym)
    errs = int(np.sum(bits != sent_bits))
    errs1 = int(np.sum(single != sent_bits))
    print(f"\n One copy alone    : {errs1} / {nbits} bit errors")
    print(f" After averaging {REPEAT} copies:")
    snr = -10 * np.log10(evm + 1e-12)
    text = bits_to_text(bits)
    print(f" Sync peak strength : {pr:.0f}x (above ~20 is good)")
    print(f" Signal quality     : {snr:.1f} dB")
    print(f" Sent     : {MESSAGE}")
    print(f" Received : {text}")
    print(f" Bit errors: {errs} / {nbits}")
    print(" RESULT   :", "SUCCESS - text received through light!" if errs == 0 else "errors - see tips below")
    if errs:
        print("  Tips: point the LED straight at the photodiode, move them closer,")
        print("        raise Mac volume to max, raise input volume in Sound settings.")
    save_plot(rx, eq, H, text, errs, nbits)
    os.makedirs(OUT, exist_ok=True)
    np.save(os.path.join(OUT, "last_recording.npy"), rx.astype(np.float32))
    return errs


def save_plot(rx, eq, H, text, errs, nbits):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    os.makedirs(OUT, exist_ok=True)
    fig, ax = plt.subplots(1, 3, figsize=(14, 4.2))
    ax[0].plot(np.arange(len(rx)) / FS, rx, lw=0.5)
    ax[0].set_title("Recorded signal from photodiode")
    ax[0].set_xlabel("time (s)")
    ax[1].scatter(eq.real.ravel(), eq.imag.ravel(), s=10)
    ax[1].axhline(0, color="k", lw=0.5); ax[1].axvline(0, color="k", lw=0.5)
    lim = 1.5 * np.max(np.abs(eq)); ax[1].set_xlim(-lim, lim); ax[1].set_ylim(-lim, lim)
    ax[1].set_aspect("equal"); ax[1].set_title("Received QPSK constellation")
    f = DATA_SC * FS / N_FFT / 1000
    ax[2].plot(f, 20 * np.log10(np.abs(H) + 1e-12), "o-", ms=3)
    ax[2].set_title("Light channel response"); ax[2].set_xlabel("frequency (kHz)"); ax[2].set_ylabel("dB")
    fig.suptitle(f'OFDM over light  —  received: "{text}"  ({errs}/{nbits} bit errors)')
    fig.tight_layout()
    p = os.path.join(OUT, "ofdm_light.png")
    fig.savefig(p, dpi=120)
    print(f" Plot saved: {p}")


if __name__ == "__main__":
    if "--list" in sys.argv:
        import sounddevice as sd
        print(sd.query_devices())
        sys.exit()

    sig, nbits, nsym = build_packet()
    sent = text_to_bits(MESSAGE)
    print("=" * 52)
    print(" OFDM over light  |  LED -> photodiode -> sound card")
    print("=" * 52)
    print(f" {len(DATA_SC)} subcarriers, QPSK, {nsym} data symbols, {len(sig)/FS:.2f} s")

    runs = 1
    if "--runs" in sys.argv:
        runs = int(sys.argv[sys.argv.index("--runs") + 1])

    ok = 0
    for i in range(runs):
        if runs > 1:
            print(f"\n---------------- run {i + 1} of {runs} ----------------")
        rx = fake_channel(sig) if "--selftest" in sys.argv else play_and_record(sig)
        ok += report(rx, nbits, nsym, sent) == 0
        if runs > 1:
            time.sleep(1)

    if runs > 1:
        print("\n" + "=" * 52)
        print(f" RELIABILITY: {ok} / {runs} packets received with 0 bit errors")
        print("=" * 52)
        os.makedirs(OUT, exist_ok=True)
        with open(os.path.join(OUT, "ofdm_light_reliability.txt"), "w") as f:
            f.write(f"OFDM over light: {ok}/{runs} packets error-free\n")
            f.write(f"{len(DATA_SC)} subcarriers, QPSK, {REPEAT} copies averaged\n")
