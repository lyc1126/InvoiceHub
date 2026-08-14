# Contributing to InvoiceHub

Thank you for contributing. Please keep changes focused, preserve the source
invoice and file-projection boundaries, and do not include invoices, company
data, local configuration, runtime state, credentials, or built installers.

## Development Process

1. Open an issue or discussion before broad architecture changes.
2. Work on a topic branch from current `main`.
3. Add focused tests for behavior changes and update the architecture documents
   named in `AGENTS.md` when a contract, workflow, file or data model changes.
4. Run the smallest relevant checks before requesting review. Run the full
   regression only when the changed surface or RC gate requires it.
5. Submit a pull request with a concise explanation, verification performed,
   known gaps, and any release or privacy impact.

## Developer Certificate of Origin

All commits must include a `Signed-off-by` trailer in the form:

```text
Signed-off-by: Your Name <you@example.com>
```

Use `git commit -s` to add it. By signing off, you certify the Developer
Certificate of Origin 1.1:

```text
By making a contribution to this project, I certify that:

(a) The contribution was created in whole or in part by me and I have the
    right to submit it under the open source license indicated in the file; or

(b) The contribution is based upon previous work that, to the best of my
    knowledge, is covered under an appropriate open source license and I have
    the right under that license to submit that work with modifications, whether
    created in whole or in part by me, under the same open source license
    (unless I am permitted to submit under a different license), as indicated
    in the file; or

(c) The contribution was provided directly to me by some other person who
    certified (a), (b) or (c) and I have not modified it.

(d) I understand and agree that this project and the contribution are public
    and that a record of the contribution (including all personal information I
    submit with it, including my sign-off) is maintained indefinitely and may
    be redistributed consistent with this project or the open source license(s)
    involved.
```

## Licensing and Attribution

Contributions are submitted under `AGPL-3.0-or-later`. Contributors keep their
copyright. Do not submit third-party code, fonts, logos, data, or assets unless
their license and attribution are compatible and documented.
