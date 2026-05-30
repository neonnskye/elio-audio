import os
import sys
import wave

import numpy as np


def convert(input_file, output_file=None, var_name=None):
    if output_file is None:
        output_file = os.path.splitext(input_file)[0] + ".h"
    if var_name is None:
        var_name = (
            os.path.splitext(os.path.basename(input_file))[0]
            .replace("-", "_")
            .replace(" ", "_")
        )

    with wave.open(input_file, "rb") as wav:
        channels = wav.getnchannels()
        sampwidth = wav.getsampwidth()
        framerate = wav.getframerate()
        n_frames = wav.getnframes()
        raw = wav.readframes(n_frames)

    print(f"  Channels   : {channels}")
    print(f"  Sample rate: {framerate} Hz")
    print(f"  Bit depth  : {sampwidth * 8} bit")
    print(f"  Frames     : {n_frames}")

    # Convert to 16-bit mono if needed
    samples = np.frombuffer(raw, dtype=np.int16 if sampwidth == 2 else np.int8)
    if sampwidth == 1:  # 8-bit unsigned → 16-bit signed
        samples = (samples.astype(np.int16) - 128) * 256
    if channels == 2:  # stereo → mono (average L+R)
        samples = samples.reshape(-1, 2).mean(axis=1).astype(np.int16)

    # Resample to 8000 if needed
    if framerate != 8000:
        from scipy.signal import resample

        new_len = int(len(samples) * 8000 / framerate)
        samples = resample(samples, new_len).astype(np.int16)
        framerate = 8000
        print("  Resampled to 8000 Hz")

    data = samples.tobytes()
    n = len(data)

    with open(output_file, "w") as f:
        f.write(f"// Auto-generated from {os.path.basename(input_file)}\n")
        f.write(f"// {framerate} Hz, 16-bit, mono\n\n")
        f.write("#pragma once\n")
        f.write("#include <stdint.h>\n\n")
        f.write(f"const uint32_t {var_name}_sample_rate = {framerate};\n")
        f.write(f"const uint32_t {var_name}_length = {n};\n\n")
        f.write(f"const int16_t {var_name}[] = {{\n  ")
        for i, s in enumerate(np.frombuffer(data, dtype=np.int16)):
            f.write(f"{s},")
            if (i + 1) % 16 == 0:
                f.write("\n  ")
        f.write("\n};\n")

    print(f"  Written to : {output_file}  ({n} bytes, {n // 2} samples)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python wav_to_header.py <input.wav> [output.h] [var_name]")
        sys.exit(1)
    convert(
        sys.argv[1],
        sys.argv[2] if len(sys.argv) > 2 else None,
        sys.argv[3] if len(sys.argv) > 3 else None,
    )
