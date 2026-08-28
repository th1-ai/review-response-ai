# Why this folder is empty

Review-Response AI does not read or write your PMS - see `docs/how-it-works.md`,
"Design decisions" (#2), and `docs/integrations.md`. This folder exists only so
the generic PMS health check in `make doctor` finds a directory instead of
reporting a false failure for an adapter this agent never calls. It is safe to
ignore the `pms adapter` line in `make doctor`'s output.
