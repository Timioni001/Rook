# The post

Long enough to be read as a piece of writing, short enough to finish. It opens on the problem, not
on us; it gives numbers that can be checked; and it says the unflattering part out loud, because
the unflattering part is the whole argument.

Attach the video. Links at the bottom, where they will survive a crop.

---

**Most agent demos end at a recommendation. Ours had to end at proof.**

A doctor calls in sick at eight in the morning. Twelve patients are booked in with her today and
none of them know. Somebody at the front desk is about to lose the entire morning to the phone:
ringing round, finding gaps, apologising. At the end of it there is no record of what was actually
done, only someone's memory of it.

That work — the work that falls between the systems an organisation already runs — is what we built
Rook for. It reads every connected system before it touches anything, writes down what would have
to be true before the job can be called done, proposes the fix as ordered steps, waits for a human
before anything reaches a person outside the building, and then checks the result against the
systems themselves.

The last part is the one we care about. A tool returning "ok" is not evidence. Rook reads the
appointment back out of the appointment book, the message out of the messaging system, the
revocation out of an authentication probe. Of forty scenarios we run end to end, sixteen close with
proof and twenty-four stop and say why: no slot free, nobody who can be told, a key whose
revocation would break a live service. Every one of those refusals comes out of the run named, with
a reason, handed to a person. An agent that will not say "I could not do this" is not safe to let
near a real system.

Then the agent ran into a problem of its own, and this is the part I would normally leave out.

Neatlogs raised it against our exported traces before we had noticed anything: six negative
detections against a baseline of zero, pattern **silent degradation**. Four runs we had called fine
were sending tool, retriever and chain spans with nothing inside them, and two tools were failing
with transient and timeout errors that never surfaced as workflow failures. It named both tools and
what to check on each one, and we sent the incident straight to the coding agent with the traces as
the brief.

The fix was not the one recommended. The retries were already there — the engine re-reads live
state before it retries anything. What was missing was honesty: a failure the engine *survived*
closed its span green, so a step that quietly died and a step that worked looked identical from the
outside. A handled failure now marks its own span, no span can export an empty output, and one test
sweeps every span of a full run and fails if a single one comes back empty. 225 tests, all passing.

cfo.ai modelled the business from inputs each labelled measured, benchmark or assumption, and found
the fragile one for us: the moment customer acquisition is paid in cash rather than founder time,
year one needs roughly $15,000 more capital. Entire checkpointed every session that built this,
with the checkpoint id in the commit itself, so the provenance travels with the repository.

It only says done when it has proof.

Demo and waitlist → rook-keywarden.pages.dev
Code → github.com/Timioni001/Rook
The plan, inputs and all → cfo.ai/s/D9MnZeXwqy0WpZeV

Built by Keywarden for #neatHack with @neatlogs.

---

## If you want a shorter one for the timeline

> A doctor calls in sick at 8am. Twelve patients are booked in and none of them know.
>
> Rook works that morning for you, and then proves it: every step read back from the system it ran
> on, not from a tool saying "ok". 40 scenarios — 16 close with proof, 24 stop and say exactly why.
>
> Neatlogs caught the one we missed. Four runs we had called fine were emitting empty tool spans,
> and failures the engine survived were closing green. A handled failure now marks its own span,
> and a test fails if any span comes back empty.
>
> rook-keywarden.pages.dev · github.com/Timioni001/Rook · cfo.ai/s/D9MnZeXwqy0WpZeV
>
> #neatHack @neatlogs

## Notes before posting

- Check the handles for cfo.ai and Entire on X yourself and tag them in the first reply rather than
  the post. I could not verify either handle, and tagging the wrong account is worse than not
  tagging.
- The video is 4:05, over X's 2:20 limit for a standard account. Either post it on LinkedIn in full
  and put the link on X, or cut to the 60-second version in `docs/demo-video.md`.
- Post the long one as an X article or LinkedIn post; the short one is the timeline version.
