# Security Policy

## Reporting a Vulnerability

Do not open a public issue for a suspected vulnerability, exposed credential,
or user-data disclosure. Use GitHub's private vulnerability reporting feature
for this repository. Include the affected version or commit, reproducible
steps, impact, and any proof-of-concept that avoids real invoices or secrets.

If private reporting is unavailable, contact the repository owner through the
GitHub profile listed in the repository metadata and request a private channel.

## Scope

Security-sensitive areas include local file and path authorization, source-file
preview and printing, skin ZIP validation, localhost/native bridges, updater
verification, release provenance, monitor lifecycle, and accidental inclusion
of invoices, configuration, runtime state or credentials in source and release
assets.

Please allow maintainers reasonable time to investigate before disclosing a
report publicly. Do not test against systems or data you do not own or control.
