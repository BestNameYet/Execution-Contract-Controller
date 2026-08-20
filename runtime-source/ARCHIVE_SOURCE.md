# Runtime artifact source

Files placed directly in this folder are the source set for the GitHub Actions runtime artifact. The workflow publishes these files as a flat archive with no enclosing `runtime-source/` directory.

When the controller runtime is added here, keep exactly one Python entrypoint file in this folder so the generated root `runtime-bootstrap.md` can identify the script that receives the predefined initialization JSON.
