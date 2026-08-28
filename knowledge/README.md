# knowledge/

For most agents in this family, this folder is read before every reply. For
**Review-Response AI specifically, it is not** - drafting a reply is
deterministic template + slot fill (`tools/engine.py`), and never reads
`property.md` or `faq.md`. The only thing that reads from here is the
optional, cosmetic morning note (`tools/narrate.py`) - see
`docs/how-it-works.md`. `property.md` and `faq.md` still ship because every
repo in this family shares the same shape; feel free to leave them as the
examples if you never turn `narrate` on.

## What to put here

| File | What it holds |
|---|---|
| `property.md` | The facts. Rooms, times, prices, policies, directions, what is nearby. Read only by the optional morning note. |
| `faq.md` | Questions guests actually ask, and the answers you actually give. Not read by this agent at all - kept for shape consistency with the rest of the family. |
| `reputation-voice.md` | This agent's own file. A few lines on house tone for the morning note - see `reputation-voice.example.md`. |

Copy the `.example.md` files, rename them without `.example`, and fill them in:

```bash
cp knowledge/property.example.md         knowledge/property.md
cp knowledge/faq.example.md              knowledge/faq.md
cp knowledge/reputation-voice.example.md knowledge/reputation-voice.md
```

`knowledge/*.md` is gitignored (the `.example.md` files are not), because your
property notes are yours.

## How to write it

**Write it the way you would brief a new receptionist.** Short sentences,
concrete facts, no marketing language. The agent will quote this material to
guests, so anything vague here becomes something vague in an email.

**Be specific about numbers and times.** "Check-in from 15:00" is usable.
"Check-in in the afternoon" is not.

**Say what you do NOT do.** "We have no parking; the nearest car park is X, about
EUR 15 a day" prevents a wrong answer far better than silence does.

**Keep prices dated.** "Breakfast EUR 18 per person (2026 rates)" tells the agent
and you when it is stale.

**One fact per line where you can.** It makes the agent's job easier and it makes
your job easier when something changes.

## Keeping it current

The agent is only as right as this folder. When a policy changes, change it here
first. A good habit: whenever you correct one of the agent's drafts in the review
queue, ask whether the correction belongs in `property.md`. If it does, the agent
stops making that mistake.

You can also ask your Claude Code session to do it:

> Read knowledge/property.md and the last ten items in the review queue. If any
> of my edits contradict what is in the file, tell me which line to change.
