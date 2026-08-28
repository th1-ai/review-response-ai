# Reputation voice notes

Read only by the optional morning note (`tools/narrate.py`, off by default -
see `docs/how-it-works.md`). It is never read by the drafting logic itself:
the actual reply templates live in `tools/engine.py`, and the tone rules that
matter for a guest-facing reply are the five toggles in `config/agent.yaml`,
not prose here.

Use this file for the couple of sentences that help a short daily note read
like it understands the property, not for policy the agent needs to follow -
policy belongs in `config/agent.yaml` or `docs/safety.md`.

## What we care about, in a review

Three or four short lines about what actually matters at this property when a
guest writes something specific. Examples of the kind of thing that belongs
here (replace with your own):

- A mention of a particular member of staff by name is worth flagging to that
  person directly, not just noting in the aggregate count.
- A slow-service complaint at breakfast is a known busy window on weekends -
  worth distinguishing from a slow-service complaint on a quiet Tuesday.
- A repeat guest (mentioned in the review, or you happen to recognise the
  name) is worth a heads-up even in a one-paragraph note.

## What "good" looks like this quarter

One or two lines on what you are actually trying to improve right now, so the
note can say something more useful than a plain count when it is relevant -
for example, "breakfast speed" or "faster replies to Booking.com specifically".

Keep this file short. It is a seasoning, not a script - the note it feeds is
a few sentences a day, never something a guest reads.
