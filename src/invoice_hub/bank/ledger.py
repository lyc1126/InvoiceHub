"""捷锐科目表读取与按路径定位科目。

科目表来自公司资料夹 `凭证/科目表.json`（只读）。不同账套的科目编码可能不同，
所以凭证草稿按“科目名称路径”（如 `应交税费/未交增值税`）定位，而不是写死编码；
找不到时返回空编码并在草稿中列入“待补科目”，绝不猜一个相近科目顶替。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Account:
    code: str
    name: str
    leaf: bool
    enabled: bool
    required_aux: list[str] = field(default_factory=list)


def _norm(text: str) -> str:
    return re.sub(r"[\s_、—\-（）()]", "", text or "")


class Ledger:
    def __init__(self, accounts: list[Account]):
        self.by_code = {a.code: a for a in accounts}
        self._codes = sorted(self.by_code)

    @classmethod
    def load(cls, path: Path) -> "Ledger":
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data.get("accounts") if isinstance(data, dict) else data
        if not isinstance(items, list):
            raise ValueError(f"{path.name} 缺少 accounts 列表")
        accounts = [
            Account(
                code=str(item["code"]),
                name=str(item["name"]).strip(),
                leaf=bool(item.get("is_leaf", True)),
                enabled=bool(item.get("enabled", True)),
                required_aux=list(item.get("required_aux_dimensions") or []),
            )
            for item in items
        ]
        return cls(accounts)

    def parent(self, code: str) -> str:
        for length in range(len(code) - 1, 0, -1):
            if code[:length] in self.by_code:
                return code[:length]
        return ""

    def children(self, code: str) -> list[Account]:
        return [self.by_code[c] for c in self._codes if c != code and self.parent(c) == code]

    def full_name(self, code: str) -> str:
        names = []
        current = code
        while current:
            names.append(self.by_code[current].name)
            current = self.parent(current)
        return "_".join(reversed(names))

    def find(self, path: str) -> str:
        """按 `一级/二级/…` 名称路径找末级科目编码；`*` 表示“唯一的末级下级”。找不到返回空串。"""
        parts = [p for p in path.split("/") if p]
        candidates = [a for a in self.by_code.values() if not self.parent(a.code) and _norm(a.name) == _norm(parts[0])]
        for part in parts[1:]:
            nxt: list[Account] = []
            for account in candidates:
                kids = self.children(account.code)
                if part == "*":
                    leaves = [k for k in kids if k.leaf and k.enabled]
                    nxt += leaves if len(leaves) == 1 else []
                else:
                    nxt += [k for k in kids if _norm(k.name) == _norm(part)]
            candidates = nxt
        usable = [a for a in candidates if a.leaf and a.enabled]
        return usable[0].code if len(usable) == 1 else ""

    def find_child_containing(self, parent_path: str, needle: str) -> str:
        """在某科目下找名称被 `needle` 包含（或包含 needle）的唯一末级明细，用于按户名匹配往来明细。"""
        parent_code = self.find_node(parent_path)
        if not parent_code or not needle:
            return ""
        key = _norm(needle)
        hits = [
            k for k in self.children(parent_code)
            if k.leaf and k.enabled and len(_norm(k.name)) >= 2 and (_norm(k.name) in key or key in _norm(k.name))
        ]
        return hits[0].code if len(hits) == 1 else ""

    def find_node(self, path: str) -> str:
        parts = [p for p in path.split("/") if p]
        current = [a for a in self.by_code.values() if not self.parent(a.code) and _norm(a.name) == _norm(parts[0])]
        for part in parts[1:]:
            current = [k for a in current for k in self.children(a.code) if _norm(k.name) == _norm(part)]
        return current[0].code if len(current) == 1 else ""

    def required_aux(self, code: str) -> list[str]:
        account = self.by_code.get(code)
        return list(account.required_aux) if account else []

    def is_usable(self, code: str) -> bool:
        account = self.by_code.get(code)
        return bool(account and account.leaf and account.enabled)


def load_aux_values(path: Path) -> dict[str, set[str]]:
    """读取 `凭证/辅助核算档案.json`，返回 维度 → 已建档名称集合。"""
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    dims = data.get("dimensions", {}) if isinstance(data, dict) else {}
    out: dict[str, set[str]] = {}
    for dim, values in dims.items():
        out[dim] = {str(v.get("name", "")).strip() for v in values or [] if isinstance(v, dict) and v.get("enabled", True)}
    return out


def load_mapping_rules(path: Path) -> list[dict]:
    """读取 `凭证/科目映射.json` 中人工确认过的采购映射规则（销售方+内部项目名称 → 科目）。"""
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    rules = data.get("rules", []) if isinstance(data, dict) else []
    return [r for r in rules if isinstance(r, dict)]
