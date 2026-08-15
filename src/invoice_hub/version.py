"""Single source of truth for product and release identity."""

from __future__ import annotations


PRODUCT_NAME = "InvoiceHub"
PRODUCT_DISPLAY_NAME = "一站式发票汇总系统"
PRODUCT_VERSION = "0.3.0-alpha.1"
PYTHON_PACKAGE_VERSION = "0.3.0a1"
# Formal Windows and macOS artifacts embed exactly this runtime.  Development
# source mode remains compatible with any supported 3.14 patch release.
RELEASE_PYTHON_VERSION = "3.14.6"
RELEASE_TAG = f"v{PRODUCT_VERSION}"
UPDATE_CHANNEL = "alpha"
MACOS_BUILD_NUMBER = "1"
API_CONTRACT_VERSION = "2026-08-02-release-update-v1"

WEBSITE_URL = "https://lyc1126.github.io/InvoiceHub/"
PUBLIC_SOURCE_URL = "https://github.com/lyc1126/InvoiceHub"
RELEASES_URL = f"{PUBLIC_SOURCE_URL}/releases"
CHANGELOG_URL = f"{PUBLIC_SOURCE_URL}/blob/main/CHANGELOG.md"
UPDATE_FEED_URL = f"{WEBSITE_URL}updates/{UPDATE_CHANNEL}/latest.json"

# Feed and artifact URLs are immutable release metadata, not user configuration.
UPDATE_ALLOWED_HOSTS = (
    "github.com",
    "lyc1126.github.io",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
)

WINDOWS_PACKAGE_ID = "com.invoicehub.windows.x86_64.portable"
MACOS_DMG_PACKAGE_ID = "com.invoicehub.macos.arm64.dmg"
MACOS_SPARKLE_PACKAGE_ID = "com.invoicehub.macos.arm64.sparkle"
MACOS_SPARKLE_KEYCHAIN_ACCOUNT = "com.invoicehub.release"
TAURI_BUNDLE_IDENTIFIER = "com.invoicehub.desktop"
