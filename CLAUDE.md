# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Flash Commands

All commands run via PlatformIO CLI or the PlatformIO IDE extension.

```bash
# Build
pio run

# Build and upload to device
pio run --target upload

# Monitor serial output (115200 baud)
pio device monitor

# Build, upload, and monitor in one step
pio run --target upload && pio device monitor

# Clean build artifacts
pio run --target clean
```

## Project Overview

ESP32 audio project targeting the **NodeMCU-32S** board using the Arduino framework via PlatformIO.
The firmware streams real-time audio from a MAX9814 analog microphone over Wi-Fi UDP to a Python backend for playback and processing.

- **Target board:** `nodemcu-32s` (Espressif ESP32)
- **Framework:** Arduino
- **Serial baud rate:** 115200
- **No external library dependencies** — uses only the built-in Arduino ESP32 framework (`WiFi.h`, `WiFiUDP.h`) and ESP-IDF headers (`driver/adc.h`, `esp_wifi.h`)
- **Python:** requires >= 3.14; managed with `uv`; dev dependency: `ruff`

## Hardware

- **Microphone:** MAX9814 analog electret mic amplifier
- **ADC pin:** GPIO 35 (ADC1 channel 7, input-only)
- **ADC config:** 12-bit resolution, 12 dB attenuation (`ADC_ATTEN_DB_12`, full 0–3.3 V range)
- **Sample rate:** 16 000 Hz

## Code Structure

- [src/main.cpp](src/main.cpp) — single entry point; Arduino `setup()` and `loop()`
- [platformio.ini](platformio.ini) — board, platform, and framework config
- [receiver.py](receiver.py) — Python UDP receiver and real-time audio playback
- [pyproject.toml](pyproject.toml) — Python project config (managed with `uv`)
- [lib/](lib/) — local libraries; contains `Elio_Wake_v3_inferencing` (Edge Impulse wake-word model)
- [include/](include/) — shared headers (currently empty)
- `.pio/` — generated build artifacts and downloaded lib dependencies (not edited manually)
- `.venv/` — Python virtual environment (managed by `uv`, not edited manually)

## Current Functionality

The firmware samples the MAX9814 microphone at **16 kHz** using a hardware timer ISR and streams raw ADC samples to a PC over **Wi-Fi UDP**.

### Architecture

- **Hardware timer ISR (`onTimer`)** — fires at exactly 16 000 Hz (timer 0, prescaler 5, alarm 1000; derived from 80 MHz CPU clock). Each invocation calls `adc1_get_raw(ADC1_CHANNEL_7)` and stores the 12-bit sample into the active half of the UDP double buffer. When 512 samples are collected the buffer is marked ready and the write pointer swaps to the other half.
- **Edge Impulse inference buffer** — same ISR also feeds samples (converted to `int16_t` and upscaled by 16) into a second double buffer managed by `ei_inference_t`. When a slice is full, the ISR sends a FreeRTOS task notification (`vTaskNotifyGiveFromISR`) to wake the inference task.
- **`inferenceTask`** (pinned to core 0) — blocks on `ulTaskNotifyTake` until the ISR signals a slice is ready, then calls `run_classifier_continuous()` and prints per-label scores. When the `"elio"` label exceeds `0.6`, it lights `LED_BUILTIN` for 500 ms and sends a single-byte trigger packet (`0x01`) to the Python receiver via `CTRL_UDP_PORT`.
- **`loop()`** (core 1) — when a UDP buffer is flagged ready, sends the 1024-byte payload as a single UDP packet to the configured PC IP. Retries on send failure (does not drop packets). Core 1 also hosts the WiFi/UDP stack; splitting inference to core 0 prevents EI processing from delaying packet transmission.
- **Double buffer** — decouples sampling from sending so the ISR never stalls waiting for UDP transmission.
- **`esp_wifi_set_ps(WIFI_PS_NONE)`** — disables WiFi modem sleep to reduce RF interference on the ADC.

### UDP Packet Format

Each packet is exactly **1024 bytes**: 512 little-endian `uint16_t` samples representing raw 12-bit ADC values (0–4095). The receiver subtracts 2048 (DC midpoint) and normalises to float before playback.

### Wake Word Control Channel

When the Edge Impulse classifier detects the wake word (label `"elio"` > 0.6), the ESP32 sends a 1-byte UDP packet (`0x01`) to `CTRL_UDP_PORT` on the PC. The Python receiver's `control_listener` thread picks this up and drives a `ListenState` state machine:

| State | Description |
|-------|-------------|
| `IDLE` | Waiting for wake word signal. Audio is streamed but not transcribed. |
| `SKIP_WAKEWORD_BLEED` | Discards `BLEED_SKIP_PACKETS` (~256 ms) of audio after the wake word to avoid transcribing the utterance itself. |
| `CAPTURING` | Actively recording the user's command. VAD accumulator builds a speech segment. |
| `TRANSCRIBING` | Whisper is processing; new captures are blocked until transcription completes. |

Flow: `IDLE` → (wake packet received) → `SKIP_WAKEWORD_BLEED` → `CAPTURING` → (silence or max segment) → `TRANSCRIBING` → `IDLE`.

### Configuration (`src/main.cpp` defines)

| Define | Default | Description |
|--------|---------|-------------|
| `WIFI_SSID` | — | Wi-Fi network name |
| `WIFI_PASSWORD` | — | Wi-Fi password |
| `PC_IP` | — | Receiver's IPv4 address (run `ipconfig` on Windows) |
| `UDP_PORT` | `12345` | UDP port for audio stream (must match Python receiver) |
| `CTRL_UDP_PORT` | `12346` | UDP port for wake word trigger signal (must match Python `CTRL_PORT`) |
| `SAMPLES_PER_PKT` | `512` | Samples per UDP packet |

### Python Backend

The receiver ([receiver.py](receiver.py)) is a multi-threaded design:

- **`receive_loop`** — receives UDP datagrams, decodes samples, pushes to `packet_queue` (playback, noise-gated) and `vad_queue` (original audio for VAD). Drops oldest on overflow.
- **`control_listener`** — listens on `CTRL_PORT` for wake word trigger packets from the ESP32; drives the `ListenState` state machine.
- **`vad_accumulator_loop`** — builds speech segments from `vad_queue` when in `CAPTURING` state; pushes completed segments to `transcribe_queue`.
- **`transcription_loop`** — runs `faster-whisper` on completed segments and prints transcripts.
- **`audio_callback`** — `sounddevice` callback; drains `packet_queue` with pre-buffering and leftover-sample carry.

#### Python Configuration (`receiver.py` constants)

| Constant | Default | Description |
|----------|---------|-------------|
| `UDP_PORT` | `12345` | Must match firmware `UDP_PORT` |
| `SAMPLE_RATE` | `16000` | Must match firmware sample rate |
| `SAMPLES_PER_PKT` | `512` | Must match firmware `SAMPLES_PER_PKT` |
| `PREBUFFER_PKTS` | `3` | Packets to queue before playback starts (~96 ms) |
| `MAX_QUEUE_LEN` | `10` | Max queued packets before dropping oldest (~320 ms) |
| `NOISE_GATE` | `0` | RMS threshold below which a packet is silenced (0 = off) |
| `VAD_SILENCE_THRESHOLD` | `0.03` | RMS threshold below which a packet is considered silence for VAD |
| `WHISPER_MODEL` | `"turbo"` | Whisper model size (`tiny` / `base` / `small` / `turbo`) |
| `WHISPER_DEVICE` | `"cuda"` | Inference device (`cuda` or `cpu`) |
| `WHISPER_COMPUTE` | `"float16"` | Compute precision (`float16` / `int8`) |
| `VAD_SILENCE_MS` | `500` | Trailing silence required to end a speech segment |
| `VAD_MIN_SPEECH_MS` | `400` | Minimum speech length; shorter segments are discarded |
| `MAX_SEGMENT_S` | `10` | Hard cap — force transcribe even if no silence detected |
| `CTRL_PORT` | `12346` | UDP port for wake word trigger signal (must match firmware `CTRL_UDP_PORT`) |
| `BLEED_SKIP_PACKETS` | `8` | Packets to discard after wake word (~256 ms of bleed from the wake utterance) |

#### Running the receiver

```bash
# Install dependencies (requires uv)
uv sync

# Run
uv run receiver.py
```

ESP32 streams live diagnostic counts to serial: `Sent: N | Failed: N`. A rising `Failed` count indicates network or send-path issues.

## Troubleshooting

### `endPacket(): could not send data: 12`
Error 12 is `ENOMEM` in lwIP — the UDP send buffer was temporarily unavailable. Root cause was a race where `readyBuf` was marked consumed *before* `endPacket()` was called, so a failed send silently dropped audio data. The fix in `loop()` retries until send succeeds.

### Python receiver stays at "Waiting for N packets to pre-buffer..."
1. Verify ESP32 and PC are on the same subnet (ESP32 streams to `PC_IP`, not broadcast)
2. Check firewall allows UDP port 12345 inbound
3. Confirm `PC_IP` in `src/main.cpp` matches the machine running `receiver.py`
4. ESP32 shows `Sent:` and `Failed:` counters — `Failed` incrementing indicates send errors

### Serial Output During Streaming
ESP32 prints live counts: `Sent: N | Failed: N`. If `Failed` keeps growing, check network path to receiver.

### PlatformIO Serial Config
`platformio.ini` sets `monitor_dtr = 0` and `monitor_rts = 0` to prevent the ESP32 from resetting when the serial monitor connects.
