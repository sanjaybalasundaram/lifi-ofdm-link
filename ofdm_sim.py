"""
Phase 2 - Step 1: DCO-OFDM simulation for a Li-Fi link
Author: Sanjay Balasundaram

An LED can only send light intensity (a real, positive signal),
so this uses DCO-OFDM:
  * Hermitian symmetry -> the IFFT output is real
  * a DC bias + clipping -> the signal is never negative

Pipeline:
  text -> bits -> QPSK -> Hermitian-symmetric IFFT -> cyclic prefix
       -> DC bias + clip -> channel (multipath + noise)
       -> remove CP -> FFT -> pilot channel estimate -> equalize
       -> QPSK decision -> bits -> text

Run:  python ofdm_sim.py
Outputs go in the results/ folder.
"""
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ---------------- parameters ----------------
N_FFT   = 64          # FFT size
N_CP    = 16          # cyclic prefix length
DATA_SC = np.arange(1, N_FFT // 2)   # subcarriers 1..31 carry data (0 = DC, 32 = Nyquist)
BIAS_K  = 2.0         # DC bias = BIAS_K * std(signal)  (common DCO-OFDM choice)
CHANNEL = np.array([1.0, 0.45, 0.2])  # small multipath, like light bouncing off a wall
MESSAGE = "Hello Li-Fi from Sanjay"
SEED    = 1
OUT     = "results"

rng = np.random.default_rng(SEED)


# ---------------- helpers ----------------
def text_to_bits(text):
    data = np.frombuffer(text.encode(), dtype=np.uint8)
    return np.unpackbits(data)

def bits_to_text(bits):
    bits = bits[: len(bits) // 8 * 8]
    raw = np.packbits(bits).tobytes().decode(errors="replace")
    return "".join(c if c.isprintable() else "?" for c in raw)

def qpsk_mod(bits):
    b = bits.reshape(-1, 2).astype(int)   # int, so 1 - 2*b can go negative
    return ((1 - 2 * b[:, 0]) + 1j * (1 - 2 * b[:, 1])) / np.sqrt(2)

def qpsk_demod(sym):
    return np.column_stack([sym.real < 0, sym.imag < 0]).astype(np.uint8).ravel()


def ofdm_tx(bits):
    """bits -> real, non-negative time signal (one long array)."""
    per_sym = 2 * len(DATA_SC)
    pad = (-len(bits)) % per_sym
    bits = np.concatenate([bits, np.zeros(pad, dtype=np.uint8)])
    qam = qpsk_mod(bits).reshape(-1, len(DATA_SC))

    # first OFDM symbol is a known pilot (all ones) for channel estimation
    pilot = np.ones(len(DATA_SC), dtype=complex)
    blocks = np.vstack([pilot, qam])

    X = np.zeros((len(blocks), N_FFT), dtype=complex)
    X[:, DATA_SC] = blocks
    X[:, N_FFT - DATA_SC] = np.conj(blocks)          # Hermitian symmetry
    x = np.fft.ifft(X, axis=1).real * np.sqrt(N_FFT)  # real-valued
    x = np.hstack([x[:, -N_CP:], x])                  # cyclic prefix

    sig = x.ravel()
    bias = BIAS_K * np.std(sig)
    led = np.clip(sig + bias, 0, None)                # LED drive: never negative
    return led, bias, pad, qam


def channel(tx, snr_db):
    y = np.convolve(tx, CHANNEL)[: len(tx)]
    ac = y - np.mean(y)
    noise_pow = np.mean(ac ** 2) / 10 ** (snr_db / 10)
    return y + rng.normal(0, np.sqrt(noise_pow), len(y))


def ofdm_rx(rx, bias, pad, n_bits):
    sym_len = N_FFT + N_CP
    r = (rx - np.mean(rx)).reshape(-1, sym_len)[:, N_CP:]   # remove DC, remove CP
    Y = np.fft.fft(r, axis=1) / np.sqrt(N_FFT)
    Yd = Y[:, DATA_SC]

    H = Yd[0]                     # pilot symbol was all ones -> Y = H
    eq = Yd[1:] / H               # one-tap equalizer per subcarrier
    bits = qpsk_demod(eq.ravel())
    return bits[:n_bits], eq, H


# ---------------- 1. send the message once ----------------
def demo_message(snr_db=20):
    bits = text_to_bits(MESSAGE)
    tx, bias, pad, qam = ofdm_tx(bits)
    rx = channel(tx, snr_db)
    rbits, eq, H = ofdm_rx(rx, bias, pad, len(bits))
    errors = int(np.sum(rbits != bits))
    return tx, rx, eq, H, bits_to_text(rbits), errors, len(bits)


# ---------------- 2. BER vs SNR ----------------
def ber_curve(snrs, n_bits=62 * 400):
    bers = []
    for s in snrs:
        bits = rng.integers(0, 2, n_bits, dtype=np.uint8)
        tx, bias, pad, _ = ofdm_tx(bits)
        rbits, _, _ = ofdm_rx(channel(tx, s), bias, pad, n_bits)
        bers.append(np.mean(rbits != bits))
    return np.array(bers)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)

    tx, rx, eq, H, text, errs, nb = demo_message(20)
    print("=" * 50)
    print(" DCO-OFDM Li-Fi simulation")
    print("=" * 50)
    print(f" FFT size {N_FFT}, CP {N_CP}, data subcarriers {len(DATA_SC)}, QPSK")
    print(f" Sent     : {MESSAGE}")
    print(f" Received : {text}")
    print(f" Bit errors at 20 dB SNR: {errs} / {nb}")

    snrs = np.arange(0, 26, 2)
    bers = ber_curve(snrs)
    print("\n SNR (dB)   BER")
    for s, b in zip(snrs, bers):
        print(f"   {s:4d}     {b:.2e}" if b > 0 else f"   {s:4d}     0 errors")

    # ---- figure ----
    fig, ax = plt.subplots(2, 2, figsize=(11, 8))

    n = 3 * (N_FFT + N_CP)
    ax[0, 0].plot(tx[:n], lw=1)
    ax[0, 0].axhline(0, color="k", lw=0.6)
    ax[0, 0].set_title("LED drive signal (3 OFDM symbols)\nreal and never negative")
    ax[0, 0].set_xlabel("sample"); ax[0, 0].set_ylabel("intensity")

    ax[0, 1].scatter(eq.real.ravel(), eq.imag.ravel(), s=8, alpha=0.6)
    ax[0, 1].set_title("Received QPSK constellation (20 dB, after equalizer)")
    ax[0, 1].set_xlim(-2, 2); ax[0, 1].set_ylim(-2, 2)
    ax[0, 1].axhline(0, color="k", lw=0.5); ax[0, 1].axvline(0, color="k", lw=0.5)
    ax[0, 1].set_aspect("equal")

    ax[1, 0].plot(DATA_SC, np.abs(H), "o-", ms=3)
    ax[1, 0].set_title("Estimated channel |H| per subcarrier (from pilot)")
    ax[1, 0].set_xlabel("subcarrier"); ax[1, 0].set_ylabel("|H|")

    ok = bers > 0
    ax[1, 1].semilogy(snrs[ok], bers[ok], "o-")
    ax[1, 1].set_title("Bit error rate vs SNR")
    ax[1, 1].set_xlabel("SNR (dB)"); ax[1, 1].set_ylabel("BER")
    ax[1, 1].grid(True, which="both", alpha=0.3)

    fig.suptitle(f'DCO-OFDM Li-Fi simulation  —  received: "{text}"', fontsize=12)
    fig.tight_layout()
    path = os.path.join(OUT, "ofdm_sim.png")
    fig.savefig(path, dpi=130)
    print(f"\n Plot saved: {path}")
