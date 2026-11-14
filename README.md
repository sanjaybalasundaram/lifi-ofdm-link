# Li-Fi Communication Link (Visible Light Communication)

A working data link that sends text from a laptop **through light** — an LED transmitter and a photodiode receiver built on a breadboard, driven over UART by a CP2102 USB-to-TTL module.

This is Phase 1 of a larger project: a Li-Fi system using **OFDM**, with a Verilog OFDM baseband core as the VLSI part.

## Demo

![Li-Fi demo: light on 10/10, paper blocking 0/10, light on again 10/10](media/lifi_demo.gif)

Phone camera (top) synced with the terminal (bottom) running `demo.py`: **10/10** messages with the light on, **0/10** while a sheet of paper blocks the light, and **10/10** again once it is removed. The idle 20-second countdowns are cut out, and the phone recording ends a few seconds before the final test finishes (the terminal shows the result). [Full-quality video](media/lifi_demo.mp4)

![Breadboard: CP2102, BC547 LED driver, BPW34 photodiode and LM393 comparator](media/breadboard.jpg)

## How it works

```
Mac ──USB──► CP2102 TXD ──► BC547 switch ──► Red LED  ~~~light~~~►  BPW34 photodiode ──► LM393 comparator ──► CP2102 RXD ──USB──► Mac
```

- **Transmitter:** UART TXD drives a BC547 transistor (via 1 kΩ base resistor), which switches the LED (2 × 100 Ω current limit) from 5 V. Each UART bit becomes an ON/OFF flash of light (On-Off Keying).
- **Receiver:** the BPW34 photodiode (reverse-biased, 100 kΩ load) converts light to voltage. An LM393 comparator compares it against a 2.5 V reference (two 10 kΩ resistors) and outputs a clean 0 / 5 V logic signal (4.7 kΩ pull-up) into UART RXD.

### Why the comparator was needed
Connecting the photodiode directly to RXD failed: the CP2102's internal pull-up on RXD held the line at ~2.5 V even in darkness, so RXD never saw a logic 0. The LM393 isolates the photodiode from RXD and squares up the signal.

## Components

| Part | Role |
|---|---|
| CP2102 USB-to-TTL | Laptop ↔ UART |
| BC547 NPN transistor | LED driver |
| 5 mm red LED | Optical transmitter |
| BPW34 PIN photodiode | Optical receiver |
| LM393 comparator | Signal slicer |
| Resistors: 1k, 2×100Ω, 100k, 2×10k, 4.7k | Biasing / reference / pull-up |

## Results

20 messages of 23 bytes per baud rate. Full log: [`results/speed_test_2026-11-14.txt`](results/speed_test_2026-11-14.txt)

| Baud rate | Light path open | Light path blocked (control) |
|---|---|---|
| 1200 | 20/20 | 0/20 |
| 2400 | 20/20 | 0/20 |
| 4800 | 20/20 | 0/20 |
| 9600 | 20/20 | 0/20 |
| 19200 | 20/20 | 0/20 |
| 38400 | 20/20 | 0/20 |
| 57600 | 20/20 | 0/20 |
| 115200 | 20/20 | 0/20 |

**Error-free transmission up to 115.2 kbps through light**, with the control test confirming the data travels only through the optical path. Current range: LED in contact with the photodiode.

## Running the tests

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python3 lifi_test.py      # 10 messages at 1200 baud
python3 speed_test.py     # 20 messages at each baud rate, 1200–115200
python3 demo.py           # guided light-on / blocked / light-on demo
```

Update the serial port in the scripts if yours differs (`ls /dev/cu.*`).

## Roadmap

- [x] Phase 1 — UART/OOK link through light, verified up to 115.2 kbps
- [ ] Increase range — 1 W LED, lens, transimpedance amplifier
- [ ] Phase 2 — OFDM over light (Python: QPSK, IFFT, cyclic prefix, sync)
- [ ] Phase 3 — live dashboard (constellation, BER) and KiCad PCB
- [ ] Phase 4 — OFDM baseband core in Verilog on FPGA

## Author

Sanjay Balasundaram — B.E. Electronics and Communication Engineering
