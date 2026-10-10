#!/usr/bin/env python3
"""Copy Entire checkpoints from local git refs into .entire/checkpoints/<id>/ as ordinary files.

Entire stores checkpoints as git refs (refs/entire/checkpoints/*). Those refs only travel with an
explicit push, so this script also writes each checkpoint as plain files that are committed with the
code and merge into main with it. Per checkpoint it keeps the metadata, the prompt and the compact
transcript (the full transcript stays in the ref). Email addresses and model identifiers are
redacted on the way out, plus any extra words listed (comma-separated) in ENTIRE_REDACT.

    python3 scripts/export-entire-checkpoints.py          # export new checkpoints, then commit them
"""
import json, os, pathlib, re, subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / ".entire" / "checkpoints"
EMAIL = re.compile(rb"[A-Za-z0-9._%+-]+@(?!users\.noreply\.github\.com)[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
MODEL = re.compile(rb"claude-(?:opus|sonnet|haiku|fable)-[0-9][0-9a-z.-]*(?:\[1m\])?|\b(?:Opus|Sonnet|Haiku|Fable) [0-9](?:\.[0-9])?\b")


def git(*a):
    return subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, check=True).stdout


EXTRA = [w.encode() for w in os.getenv("ENTIRE_REDACT", "").split(",") if w.strip()]


def clean(data: bytes) -> bytes:
    data = MODEL.sub(b"[model]", EMAIL.sub(b"[email]", data))
    for w in EXTRA:
        data = data.replace(w, b"[redacted]")
    return data


def export(ref):
    cid = ref.rsplit("/", 1)[1]
    dest = OUT / cid
    if dest.exists():
        return None
    top = json.loads(git("show", f"{ref}:metadata.json"))
    dest.mkdir(parents=True)
    (dest / "metadata.json").write_bytes(clean(git("show", f"{ref}:metadata.json")))
    for i, s in enumerate(top.get("sessions", [])):
        for key, name in (("metadata", "session.json"), ("prompt", "prompt.txt"), ("compact_transcript", "transcript.jsonl")):
            path = s.get(key)
            if path:
                data = clean(git("show", f"{ref}:{path.lstrip('/')}"))
                (dest / (name if i == 0 else f"{i}-{name}")).write_bytes(data)
    return cid


def main():
    refs = git("for-each-ref", "--format=%(refname)", "refs/entire/checkpoints/").decode().split()
    done = [c for c in (export(r) for r in refs) if c]
    print("exported: " + (", ".join(done) if done else "nothing new"))


if __name__ == "__main__":
    main()
