# Simplified Transaction Layer

This folder is an isolated implementation surface for a simplified transaction layer. It does not replace or modify the existing `minimal_controller.py` implementation.

## Intended boundary

The transaction layer accepts executable script source, creates a runner for that script, runs it, transparently carries stdin downward and stdout/stderr upward, and records the observable transaction boundary.

The transaction layer does not interpret the semantic meaning of stdin, stdout, stderr, or the script contents.

The execution derivative is intentionally script-oriented and will use a single `subprocess.Popen(...)` child so a running script can perform multiple stdin/stdout exchanges before it exits.

Receipt requirements and any JSON continuation behavior will be implemented and tested inside this folder without changing the existing minimal controller until explicitly requested.
