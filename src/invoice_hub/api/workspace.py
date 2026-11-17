"""Presentation-only adapter for trusted classic pages inside the Vue workspace."""
from fastapi import Request


WORKSPACE_ISOLATED_SKINS = frozenset({"ink-pulse", "animal-island"})


def workspace_skin_isolated(request: Request, skin_id: str) -> bool:
    workspace = request.url.path == "/workspace" or request.url.path.startswith("/workspace/")
    return (workspace or request.query_params.get("workspace_embed") == "1") and skin_id in WORKSPACE_ISOLATED_SKINS


def workspace_appearance_policy(text: str) -> str:
    # One reversible presentation policy reaches Vue and cached classic consumers.
    # It never resets the saved skin, so standalone classic pages keep that preference.
    isolated = " ".join(sorted(WORKSPACE_ISOLATED_SKINS))
    script = f'<script>document.documentElement.dataset.workspaceIsolatedSkins = "{isolated}";</script>'
    return text.replace("</head>", script + "\n</head>", 1)


def embed_workspace_page(text: str, request: Request) -> str:
    if request.query_params.get("workspace_embed") != "1":
        return text
    path = request.url.path
    if path not in {"/costs", "/documents", "/bookkeeping", "/ocr", "/consistency", "/settings", "/skins"} and not path.startswith("/invoices/"):
        return text
    if path == "/skins":
        text = text.replace('<section id="skinBanner"',
            '<p class="banner banner--muted" role="status">Ink Pulse、Animal Island 已在工作区暂停应用；保存的皮肤仍用于单独打开的经典页面。工作区可继续切换浅色和深色。</p><section id="skinBanner"', 1)
    # Only layout/navigation/SSE lifetime is adapted. The existing page/controller
    # keeps all business actions and their server-side confirmation/CAS contracts.
    resources = (
        '<link rel="stylesheet" href="/static/css/workspace-embed.css?v=20261116-prototype-3">'
        '<script src="/static/js/workspace-embed.js?v=20261116-prototype-2"></script>'
    )
    return workspace_appearance_policy(text).replace("</head>", resources + "\n</head>", 1)
