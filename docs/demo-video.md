# The submission video

One video, 4:05, with a voice-over, in the order neatHack asked for it:

1. **the problem the agent solves** — the front page, with the waitlist and the demo on it
2. **the agent solving it** — a real run on the deployed site, start to verified closure
3. **how neatlogs identified and resolved an incident the agent ran into** — the incident it raised
   against our own traces, and the fix that came out of it
4. **how cfo.ai and Entire were part of the project**

It is recorded by `scripts/record-demo.js`, which drives the live site in a real browser, draws a
cursor (Playwright's video does not capture the system one), burns a caption in at each beat, and
then cuts to the cards in `scripts/video/story.html` for the parts that have no screen to show.
Those cards use the product's own type, colours and 5px hard shadow, so the cut does not jolt.

That matters for a deadline: change a word, run it again, get the same clip with the same pacing.
No re-recording by hand, no stray notifications in frame, no mouse wobble.

```bash
# the screenshots the neatlogs cards use (not in git: they are a browser window, not product UI)
scripts/video/shots/{raised,sessions,recommended,sent,overview}.png

python scripts/make-voice.py speak      # one wav per line, and how long each one takes
PLAYWRIGHT_MODULE=/opt/node-tools/node_modules/playwright \
ROOK_DEMO_URL=https://rook-keywarden.pages.dev node scripts/record-demo.js
python scripts/make-voice.py mix        # lay the voice under it, at the times it was said
```

**Picture and voice cannot drift.** The words live in `scripts/video/narration.json`, each beat with
a short `caption` for the screen and a fuller `voice` line to speak. `make-voice.py speak` measures
every line, the recorder holds each shot for exactly that long and writes down when it happened,
and `mix` places each line at its own cue. Rewrite a line and its shot gets longer by itself. There
is no edit pass to redo.

The voice is piper, an on-device neural model, so nothing is sent to a service and it re-runs
offline. `ROOK_DEMO_PACE=1.3` slows the whole thing down if you want more air.

Output lands in `docs/video/`, which is gitignored: video does not belong in the repository.
1600x900, about 6 MB as mp4.

---

## Shot list, with what to say over it

The captions are already burned in, so this is the voice-over, not a description of the screen. If
you record a voice track and the captions start to feel redundant, comment out the `say(...)` calls
and run it again.

| Time | On screen | What you say |
|---|---|---|
| 0:00 | Front page, hero | "Every organisation runs on work that falls between its systems. A doctor calls in sick at eight. Twelve patients are booked in with her today, and none of them know." |
| 0:11 | The three panels | "Normally a person at the front desk loses the whole morning to the phone — and at the end of it, nobody can prove what was actually done." |
| 0:22 | Open the demo | "This is Rook. Same engine for a clinic, a production outage, or an API key that outlived the person who made it." |
| 0:30 | The who-are-you sheet | "First it asks who you are. That is not decoration: what you are allowed to do here depends on the answer." |
| 0:40 | Priya, the incident loads | "Rook has already read the appointment book, the patient records and the messaging system — and changed nothing. It writes down what would have to be true before this can be called done." |
| 0:58 | Findings | "Who is affected, who has room, and who it cannot reach." |
| 1:05 | Run, steps turn green | "Now it works. Move the appointment, tell the patient, check it landed. Eleven times." |
| 1:18 | The approval card | "And it stops. Texting a patient reaches a real person, so a human says yes first. That pause is deliberate." |
| 1:32 | Closed, the six-line account | "Done — and the whole morning is six lines of plain English." |
| 1:40 | Verification table | "Every one of those lines was read back from the systems themselves. Not a tool saying 'ok'." |
| 1:48 | The Limits panel | "One patient had a dead phone number. Rook did **not** quietly move her. It left the appointment alone and handed reception her name, her time and the reason." |
| 1:56 | Card: "a problem of its own" | "That was Rook working. Here is the part most demos leave out." |
| 2:00 | neatlogs incident 4c1da347 | "We did not find this. Neatlogs did — six negative detections against a baseline of zero, raised off our exported traces while we were busy building. Pattern: silent degradation." |
| 2:08 | neatlogs sessions | "Four runs we had called fine. Tool, retriever and chain spans arriving with nothing in them — a step that worked and a step that quietly died looked identical." |
| 2:14 | Recommended action | "It named the two tools: `app.update_dependent` and `cloud.rollback_service`, and what to check on each." |
| 2:20 | Sent to Claude Code | "One button from the incident to the coding agent, with the traces as the brief." |
| 2:25 | The fix | "The retries were already there. The honesty was not: a failure the engine survived closed its span green. Now a handled failure marks its own span, and no span can export an empty output — one test sweeps a whole run and fails if one does." |
| 2:33 | cfo.ai | "cfo.ai modelled the business from inputs that are each labelled measured, benchmark or assumption. It found the fragile one: the moment acquisition is paid in cash rather than founder time, year one needs about fifteen thousand more capital." |
| 2:40 | Entire | "Entire checkpointed every session that built this, and the checkpoint id is in the commit itself, so the provenance travels with the repository." |
| 2:46 | Closing card | "It only says done when it has proof." |

If you need a 60-second cut: the problem (0:00–0:22), the approval pause (1:18), the refusal
(1:48), the neatlogs incident (2:00–2:08), the fix (2:25), the closing card.

## Editing and voice

- To record it in your own voice instead, read the `voice` lines out of `narration.json`, replace
  the wavs in `docs/video/vo/` keeping the names, and run `make-voice.py mix`. Everything else,
  including the pacing, stays as it is.
- The captions stay burned in for the silent-autoplay case on X and LinkedIn.
- The mix is normalised to -16 LUFS, which is the level speech wants on a phone. Listen to it
  anyway before posting: levels can be measured, delivery cannot.
- For a terminal shot (`pytest -q`), record it rather than filming it: **asciinema** replays a
  session as text at any size, and **VHS** (charmbracelet/vhs) writes the recording from a script,
  so the typing is as repeatable as the browser part.
