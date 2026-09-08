# OFD preview component — third-party notices

InvoiceHub's preview adapter is licensed under AGPL-3.0-or-later, as specified
in the repository LICENSE. It exposes only page-to-PNG rendering.

OFD Reader & Writer 2.4.0: https://github.com/ofdrw/ofdrw — Apache-2.0.
The upstream jars are redistributed unmodified. Their metadata and embedded
notices remain intact. Dependency coordinates, exact artifact URLs and SHA-256
values are recorded in dependencies.lock.json and sbom.cdx.json.

The retained iText 7.2.6 libraries use AGPL-3.0/commercial licensing; InvoiceHub
uses the AGPL option. PDFBox/FontBox, Commons, Dom4j, Jaxen, SLF4J,
TwelveMonkeys, Bouncy Castle, UJMP and Zip4j have their own licenses.
OFDRW's Apache license does not replace the licenses of these dependencies.
Font parsing and compositing dependencies remain even though PDF export is
not exposed. No third-party classes or embedded notices are removed from jars.
The writer-only OFDRW layout/graphics2d/font modules and UJMP's unused JSON
export dependency are excluded from the preview runtime.

The Java runtime is built from the SHA-pinned Azul Zulu OpenJDK 21 archive.
Its GPLv2 with Classpath Exception and additional bundled component notices
are retained under java/legal. Source and distribution information:
https://www.azul.com/downloads/zulu-community/ and https://github.com/openjdk/jdk21u

No commercial fonts or customer documents are bundled. System font fallback
may differ across platforms; embedded OFD fonts take precedence where supported.
