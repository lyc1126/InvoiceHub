# InvoiceHub third-party notices

InvoiceHub `0.3.0-alpha.1` is distributed under `AGPL-3.0-or-later`. The
following end-user runtime components and selected build components are included
in, or used to build, the Windows and macOS packages. Exact transitive runtime
and build-tool inventories are recorded in the hash locks and generated SBOMs;
the license text shipped by each upstream project remains authoritative.

| Component | Locked version | License | Upstream |
|---|---:|---|---|
| CPython | 3.14.6 | PSF-2.0 | <https://www.python.org/> |
| annotated-doc | 0.0.5 | MIT | <https://github.com/fastapi/annotated-doc> |
| annotated-types | 0.8.0 | MIT | <https://github.com/annotated-types/annotated-types> |
| anyio | 4.14.2 | MIT | <https://github.com/agronholm/anyio> |
| certifi | 2026.7.22 | MPL-2.0 | <https://github.com/certifi/python-certifi> |
| click | 8.4.2 | BSD-3-Clause | <https://github.com/pallets/click> |
| colorama | 0.4.6 (Windows only) | BSD-3-Clause | <https://github.com/tartley/colorama> |
| et-xmlfile | 2.0.0 | MIT | <https://foss.heptapod.net/openpyxl/et_xmlfile> |
| FastAPI | 0.141.1 | MIT | <https://github.com/fastapi/fastapi> |
| h11 | 0.16.0 | MIT | <https://github.com/python-hyper/h11> |
| idna | 3.18 | BSD-3-Clause | <https://github.com/kjd/idna> |
| openpyxl | 3.1.5 | MIT | <https://foss.heptapod.net/openpyxl/openpyxl> |
| packaging | 26.2 | Apache-2.0 OR BSD-2-Clause | <https://github.com/pypa/packaging> |
| Pillow | 12.3.0 | HPND | <https://github.com/python-pillow/Pillow> |
| Pydantic | 2.13.4 | MIT | <https://github.com/pydantic/pydantic> |
| pydantic-core | 2.46.4 | MIT | <https://github.com/pydantic/pydantic-core> |
| PyMuPDF | 1.28.0 | AGPL-3.0-or-later OR commercial | <https://github.com/pymupdf/PyMuPDF> |
| Starlette | 1.3.1 | BSD-3-Clause | <https://github.com/Kludex/starlette> |
| typing-extensions | 4.16.0 | PSF-2.0 | <https://github.com/python/typing_extensions> |
| typing-inspection | 0.4.2 | MIT | <https://github.com/pydantic/typing-inspection> |
| Uvicorn | 0.52.1 | BSD-3-Clause | <https://github.com/encode/uvicorn> |
| watchdog | 6.0.0 (Windows only) | Apache-2.0 | <https://github.com/gorakhargosh/watchdog> |
| Sparkle | 2.9.2 (macOS only) | MIT | <https://github.com/sparkle-project/Sparkle> |
| python-build-standalone | 20260623 artifacts (macOS runtime) | project and bundled component licenses | <https://github.com/astral-sh/python-build-standalone> |

Release-only tools (`pytest`, `httpx2`, `pip-tools`, and `cyclonedx-bom`) are
not placed in the end-user runtime unless a package manifest explicitly lists
them. Their exact versions and hashes are recorded under `requirements/`.

PyMuPDF requires special attention: this release plan uses the AGPL route and
therefore requires complete corresponding source availability. A qualified
person must complete the legal and license review before public distribution;
this file is not legal advice.
