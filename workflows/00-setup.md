# Workflow: first-run setup

Objective: get Review-Response AI from a fresh clone to drafting real replies,
in one sitting.

## Steps

1. **Install and check.**
   ```bash
   make setup
   make doctor
   ```
   `make setup` creates the virtualenv, installs `requirements.txt`, and
   copies `.env.example` -> `.env` and every `config/*.example.yaml` ->
   `config/*.yaml` (only if those files do not exist yet - it never overwrites
   your own copies). `make doctor` will show a `FAIL` on "hotel identity"
   right after setup - that is expected, it means the property name is still
   the shipped placeholder. It also prints `pms adapter` and `email adapter`
   lines: this agent does not use either, ignore them (see
   `docs/integrations.md`).

2. **Run the demo.** No credentials needed.
   ```bash
   make demo
   ```
   Expect to see 7 sample reviews from `fixtures/inbound/` sorted into
   drafted replies and escalations, and the line
   `DEMO OK - 7 items processed, 5 drafted, 0 sent (shadow)`. If you do not
   see that, stop and read `workflows/99-troubleshooting.md`.

3. **Fill in the property.** Edit `config/hotel.yaml` (name, address, contact,
   languages). Then edit `config/agent.yaml`:
   - `signoff.name` and `signoff.role` - who signs a reply when `brand-voice`
     is on.
   - `amenities` - which team each review category reaches. Add or remove
     categories to match how you tag reviews.
   - `competitors` - names that must never be quoted back to a guest.
   - `platforms` - purely descriptive; list what you actually watch.

4. **Connect a real review source.** `reviews.adapter` in `config/agent.yaml`
   starts as `mock`, which only ever sees the bundled fixtures. `csv` reads a
   CSV export from your review-management tool or aggregator - see
   `docs/integrations.md`. There is no live posting adapter for any platform
   yet; both `mock` and `csv` log a reply instead of posting it (see the same
   page for exactly what that means and why).

   Before switching `reviews.adapter` from `mock` to `csv` (or back), run
   `make clean` first. Both adapters share the same `data/agent.db` queue, so
   if you already ran `make run` on `mock` fixtures - to try `make review` or
   `tools/narrate.py`, say - those sample items stay in the queue and mix
   with your real reviews once you switch. `make clean` clears the database,
   logs and exports; it never touches `config/` or `.env`.

5. **Re-check.**
   ```bash
   make doctor
   ```
   Once the property name is real, the "hotel identity" line turns green.
   Move on to `workflows/10-review-response.md` to run the loop on your own
   reviews.
