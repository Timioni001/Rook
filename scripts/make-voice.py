#!/usr/bin/env python3
"""Speak the narration, then lay it under the recording.

Two steps, because the video has to be recorded between them:

    python scripts/make-voice.py speak      # one wav per line, plus durations
    node scripts/record-demo.js             # holds each beat for as long as its line takes
    python scripts/make-voice.py mix        # places each line at the time it was said

Holding each beat for the length of its own line is what keeps picture and voice together: there
is no edit pass, and no line can drift off the thing it is describing. A line that gets longer
makes its shot longer, automatically, on the next run.

The voice is local (piper, an on-device neural model), so nothing is sent anywhere and the whole
thing re-runs offline once the model is on disk:

    uv venv .voice && VIRTUAL_ENV=.voice uv pip install piper-tts
    curl -sSfLO https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/cori/high/en_GB-cori-high.onnx{,.json}
"""
import json, os, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
VO = ROOT / "docs" / "video" / "vo"
LINES = json.loads((ROOT / "scripts" / "video" / "narration.json").read_text())["lines"]
PY = os.getenv("PIPER_PYTHON", sys.executable)
MODEL = os.getenv("PIPER_MODEL", str(ROOT / "docs" / "video" / "en_GB-cori-high.onnx"))
GAP = 0.45          # breath between the line ending and the picture moving on


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    return round(float(out.stdout.strip()), 3)


def speak():
    if not pathlib.Path(MODEL).exists():
        sys.exit(f"no voice model at {MODEL}; see the docstring")
    VO.mkdir(parents=True, exist_ok=True)
    out = {}
    for key, line in LINES.items():
        wav = VO / f"{key}.wav"
        subprocess.run([PY, "-m", "piper", "-m", MODEL, "-f", str(wav)],
                       input=line["voice"], text=True, check=True, capture_output=True)
        out[key] = {"caption": line["caption"], "seconds": duration(wav), "hold": duration(wav) + GAP}
        print(f"{key:12} {out[key]['seconds']:5.2f}s  {line['voice'][:60]}")
    (VO / "lines.json").write_text(json.dumps(out, indent=2) + "\n")
    print(f"\n{len(out)} lines, {sum(v['seconds'] for v in out.values()):.0f}s of speech -> {VO}")


def mix():
    """Place each line at the moment its caption appeared, and mux it onto the video."""
    cues = json.loads((VO / "cues.json").read_text())        # written by the recorder
    video = ROOT / "docs" / "video" / "rook-demo.webm"
    track = VO / "voice.wav"
    offset = float(os.getenv("ROOK_VO_OFFSET", "0"))
    args, mixes = ["ffmpeg", "-y", "-v", "error"], []
    for i, cue in enumerate(cues):
        args += ["-i", str(VO / f"{cue['id']}.wav")]
        mixes.append(f"[{i}:a]adelay={int(max(0, cue['at'] + offset) * 1000)}:all=1[a{i}]")
    chain = ";".join(mixes) + ";" + "".join(f"[a{i}]" for i in range(len(cues)))
    # normalize=0 keeps each line at its own level (amix would duck them all); loudnorm then puts
    # the whole track at the -16 LUFS that reads as normal speech on a phone.
    chain += f"amix=inputs={len(cues)}:normalize=0:dropout_transition=0,loudnorm=I=-16:TP=-1.5:LRA=11[out]"
    subprocess.run(args + ["-filter_complex", chain, "-map", "[out]", str(track)], check=True)
    out = ROOT / "docs" / "video" / "rook-demo.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-i", str(track),
                    "-c:v", "libx264", "-preset", "slow", "-crf", "22", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
                    str(out)], check=True)
    print(f"{out}  {out.stat().st_size / 1e6:.1f} MB  {duration(out)}s")


if __name__ == "__main__":
    {"speak": speak, "mix": mix}[sys.argv[1] if len(sys.argv) > 1 else "speak"]()
