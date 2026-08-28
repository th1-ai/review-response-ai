# Workflow: shadow to live

Objective: decide, together with the hotel, whether Review-Response AI is
ready to post approved replies on its own instead of only drafting them - and
make the change safely if so.

This is the hotel's decision, never the agent's. Do not suggest it until the
checklist below is genuinely true, and when you do raise it, say plainly what
changes - and what does not.

## Checklist

- [ ] `make doctor` shows no `FAIL` lines other than `pms adapter` /
      `email adapter` - this agent does not use either, and those two lines
      are safe to ignore (`docs/integrations.md`). Every other line should be
      `ok`. `warn` on `mode` is expected until you flip it.
- [ ] `config/hotel.yaml` has the real property name and contact details.
      `config/agent.yaml` has your real `signoff`, `amenities` and
      `competitors` - not the shipped examples.
- [ ] At least a few real `make run` passes have gone through the review
      queue, not just the demo fixtures, and you have read enough drafts to
      trust the template + rule combination for your reviews.
- [ ] You have decided which reviews adapter you are actually running on
      (`mock`, `csv`, or a real one you wrote yourself - see
      `docs/integrations.md`). Going live on `mock` would only ever touch
      the fixtures.
- [ ] You have a real answer for how a posted reply actually reaches the
      platform. With `mock` or `csv`, "posting" only logs the reply - going
      live does not make either of those call a real API. If you need that,
      it is new work, not a flag to flip (`docs/integrations.md`).

## Making the change

1. Edit `config/hotel.yaml`:
   ```yaml
   mode: live
   ```
2. `review.require_approval_for` still lists `publish` by default - it
   should. Going live means **approved drafts get posted**, not that the
   agent starts posting unapproved ones, or that a 2-star-or-below review
   stops being escalated. There is no config that changes either of those.
3. Run `make doctor` again to confirm.
4. Clear the shadow-era backlog before it can post by accident:
   ```bash
   python3 tools/review.py stale
   ```
   Everything drafted, escalated, approved or edited while you were only
   testing in shadow moves to `stale` - it was never sent and is out of
   date, so it will not go out just because `mode` changed. Revive one item
   with `python3 tools/review.py show <id>` first if it still matters.
5. Run one real pass and manually watch a post go through:
   ```bash
   make run ARGS="--limit 1"
   python3 tools/review.py list
   python3 tools/review.py approve <id>
   python3 tools/review.py post
   ```
6. Tell the hotel exactly what just changed: an approved draft now actually
   gets posted (or logged for hand-posting, on `mock`/`csv`) the next time
   someone, or a scheduled job, runs `python3 tools/review.py post`. It is
   still never automatic before that approval, for any star rating, and
   escalated reviews still always go to a person.

## Going back to shadow

```yaml
mode: shadow
```
in `config/hotel.yaml`, or `AGENT_MODE=shadow` in `.env` for one run. Either
stops every outbound action on the next pass, mid-schedule, with no other
change required.
