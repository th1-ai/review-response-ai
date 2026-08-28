#!/usr/bin/env python3
"""tools/doctor.py - is Review-Response AI configured and reachable right now?

    make doctor
    python3 tools/doctor.py

Runs the generic core.doctor checks (python, deps, config, .env, hotel
identity, mode, llm provider, the store, knowledge) plus this agent's own:
the reviews adapter, the messaging adapter it uses for duty-manager alerts,
the five rules, and the sign-off name. Exits 0 when everything passed, 1 when
a FAIL line needs fixing. Never a traceback.

Note: the generic checks also print a `pms adapter` and an `email adapter`
line. This agent does not use either - see docs/integrations.md - they show
`mock` and pass by default; ignore them.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.adapters import get_messaging  # noqa: E402
from core.config import ConfigError, Settings, load_settings  # noqa: E402
from core.doctor import Check, FAIL, PASS, WARN, print_table, run_checks  # noqa: E402
from reviews_adapters import get_reviews  # noqa: E402


def check_reviews_adapter(settings: Settings) -> Check:
    try:
        adapter = get_reviews(settings)
    except Exception as exc:  # noqa: BLE001
        return Check("reviews adapter", FAIL, str(exc)[:200],
                     "Fix reviews.adapter in config/agent.yaml.")
    health = adapter.ping()
    status = PASS if health.ok else (WARN if adapter.status == "stub" else FAIL)
    caps = ", ".join(sorted(adapter.capabilities())) or "none"
    detail = f"{adapter.name} [{adapter.status}] {health.detail}"
    if health.ok:
        detail += f" | can: {caps}"
    return Check("reviews adapter", status, detail, health.fix_hint)


def check_duty_manager_channel(settings: Settings) -> Check:
    try:
        messaging = get_messaging(settings)
    except Exception as exc:  # noqa: BLE001
        return Check("duty-manager alert", FAIL, str(exc)[:200],
                     "Fix systems.messaging in config/hotel.yaml.")
    health = messaging.ping()
    status = PASS if health.ok else WARN
    return Check("duty-manager alert", status,
                 f"{messaging.name} - used by `python3 tools/review.py notify`", health.fix_hint)


def check_rules(settings: Settings) -> Check:
    rules = settings.agent_get("rules", {})
    if not rules:
        return Check("rules", FAIL, "no rules configured in config/agent.yaml",
                     "Copy config/agent.example.yaml to config/agent.yaml - it ships "
                     "with all five rules on.")
    on = [k for k, v in rules.items() if v]
    return Check("rules", PASS, f"{len(rules)} configured, {len(on)} on: {', '.join(on)}")


def check_signoff(settings: Settings) -> Check:
    name = settings.agent_get("signoff.name", "")
    if not name and settings.agent_get("rules.brand-voice", True):
        return Check("sign-off", WARN, "brand-voice is on but signoff.name is blank",
                     "Set signoff.name and signoff.role in config/agent.yaml so signed "
                     "replies are not signed by nobody.")
    return Check("sign-off", PASS, f"signed replies use: {name or '(unsigned house voice)'}")


def main() -> int:
    try:
        settings = load_settings()
    except ConfigError as exc:
        checks = run_checks(None) + [Check("config", FAIL, str(exc),
                                           "Fix config/hotel.yaml or config/agent.yaml.")]
        return print_table(checks, title="Review-Response AI - doctor")

    checks = run_checks(settings, extra=[check_reviews_adapter, check_duty_manager_channel,
                                         check_rules, check_signoff])
    return print_table(checks, title="Review-Response AI - doctor")


if __name__ == "__main__":
    raise SystemExit(main())
