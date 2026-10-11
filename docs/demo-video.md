# The two videos

Two different jobs, so two different cuts. The first has to make a non-technical person understand
what Rook is for in under two minutes. The second has to convince someone technical that it is real.

Both are recorded by `scripts/record-demo.js`, which drives the live site in a real browser, draws
a cursor (Playwright's video does not capture the system one), and burns a caption in at each beat.
That matters for a deadline: change a word, run it again, get the same clip with the same pacing.
No re-recording by hand, no stray notifications in frame, no mouse wobble.

```bash
# local, against the single container
ROOK_DEMO_URL=http://localhost:8000 node scripts/record-demo.js
# or against the deployed site
ROOK_DEMO_URL=https://rook-keywarden.pages.dev node scripts/record-demo.js
ROOK_DEMO_PACE=1.4 node scripts/record-demo.js        # slower, if you are talking over it

ffmpeg -i docs/video/rook-demo.webm -c:v libx264 -preset slow -crf 23 \
  -pix_fmt yuv420p -movflags +faststart docs/video/rook-demo.mp4
```

Output lands in `docs/video/`, which is gitignored: video does not belong in the repository.

---

## Video 1 — for anyone (target 1:45, recorded 1:48)

The rule for this one: **no word a receptionist would have to look up.** No "agent", no "playbook",
no "closure condition", no "orchestration". The screen can show those; the voice must not.

| Time | On screen | What you say |
|---|---|---|
| 0:00 | Front page, hero | "A doctor calls in sick at eight in the morning. Twelve patients are booked in with her today, and none of them know." |
| 0:12 | Scroll to the three panels | "Normally someone at the front desk loses the whole morning to the phone. Ringing round, finding gaps, apologising." |
| 0:22 | Open the demo | "This is Rook. It does that morning for you." |
| 0:30 | The who-are-you sheet | "First it asks who you are. That is not decoration: what you are allowed to do here depends on the answer." |
| 0:40 | Pick Priya, the incident loads | "Priya is the practice manager. Rook has already read the appointment book, the patient records and the messaging system — and changed nothing." |
| 0:55 | Findings | "It knows who is affected, which colleagues have room, and who it cannot reach." |
| 1:05 | Press Run, steps turn green | "Now it works. Move the appointment, tell the patient, check it landed. Eleven times." |
| 1:20 | The approval card | "And it stops here. Texting a patient reaches a real person, so a human says yes first. That pause is deliberate." |
| 1:32 | Closed, the six-line account | "Done. Here is the whole morning in six lines." |
| 1:40 | Verification table | "And every one of those lines was checked against the systems themselves. Not a tool saying 'ok' — actually checked." |
| 1:48 | The Limits panel | "One patient had a dead phone number. Rook did **not** quietly move her. It left the appointment alone and handed reception her name, her time and the reason." |

Last line, over the front page: **"It only says done when it has proof. rook-keywarden.pages.dev."**

If you only have 60 seconds, cut to: the problem (0:00–0:20), the approval pause (1:20), the
refusal (1:48), the closing line.

---

## Video 2 — technical (target 3:00)

Same flow, different commentary. Assume the viewer builds agents and is sceptical.

| Time | On screen | What you say |
|---|---|---|
| 0:00 | README or front page | "Most agent demos end at a recommendation. The interesting question is how you know it worked." |
| 0:15 | Start the incident, Findings | "Rook investigates first: ten sandboxed adapters, read-only. The plan comes from the state, not from a model — the planner is deterministic code, so ordering and policy cannot be talked out of." |
| 0:40 | The Plan, by dependency depth | "The plan is a DAG. This view is the actual `depends_on` the engine executes from, so what runs in parallel is what you see." |
| 1:00 | Verification section | "Before anything changed, it wrote the closure checks. Each one names an independent observer — a probe against the live system, not the tool's reply." |
| 1:25 | Approval card, policy line | "Policy is evaluated at plan time and again immediately before execution, against live state. Rules R0 to R11: allowlist, ownership, dependency, safe order, approval, known-good rollback, truthful record." |
| 1:50 | Switch identity to Eve | "Authorisation is server-side. Another organisation gets a 404, not a 403 — you cannot even learn the incident exists." |
| 2:05 | Run `cover` or `fixtures` with a fault | "On a failure it checkpoints, re-reads real state, and decides whether a retry is even safe. Idempotency keys mean nothing is applied twice." |
| 2:25 | The escalated run | "And when it cannot finish, it escalates and names what is still not true. Of 40 scenarios, 24 end that way on purpose." |
| 2:40 | Evidence pack download | "Every run produces this: the plan, the approvals with who approved, every check with its observed evidence, the refusals, and a hash-chained audit log." |
| 2:55 | Terminal: `pytest -q` | "221 tests. One of them runs all 40 scenarios end to end and asserts closed means every check passed." |

Worth saying out loud, because it is the unusual bit: **zero inference cost at run time.** No model
call is on the critical path, which is why the cost model holds at a low price.

---

## Recording the terminal part

For the `pytest` shot, record the terminal rather than filming it:

- **asciinema** (`asciinema rec`) — records a terminal session as text, replays at any size, tiny files.
- **VHS** (charmbracelet/vhs) — writes the recording from a script (`Type "pytest -q"`, `Sleep 2s`,
  `Enter`), so the terminal clip is as repeatable as the browser one. This is the one to use if you
  want the typing to look clean without typing it cleanly.

Either exports a GIF or MP4 you can cut in next to the browser footage.

## Editing and voice

- The recorded clip has no audio. Record the voice-over separately and lay it under — reading from
  the table above beats talking over a live run, and you can retake one line instead of all of them.
- If a line runs long, raise `ROOK_DEMO_PACE` and re-record rather than speeding up your speech.
- Keep the captions in for the silent-autoplay case (X, LinkedIn). If you add a voice-over for the
  judges' cut and the captions start to feel redundant, comment out the `say(...)` calls.
