"""脱敏视图与泄漏扫描。

设计取舍：
- 自由文本（摘要/用途/附言）采用**白名单**：只保留会计用途关键词，其余整体丢弃。
  银行摘要里会夹带人名、班组名、项目名，黑名单替换永远漏不干净。
- 户名用带密钥的 HMAC 生成稳定化名，同一密钥下跨月份一致，便于 AI 或协作者识别“同一往来方”；
  没有私有密钥无法反推。化名→真名对照表只写在私有目录。
- 金额和日期保留：它们是做账本身需要的信息。脱敏底稿用于 AI 辅助或外部协作，不是公开发布物。
- 写出前对全部输出字符串做泄漏扫描，命中任何已登记的敏感值即整体拒绝写出（fail closed）。
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from pathlib import Path

PURPOSE_VOCABULARY = (
    "材料预付款", "材料款预付款", "材料款", "预付款", "货款", "垫付款", "垫入款", "往来款", "借款", "还款",
    "保证金", "油卡充值", "油卡费", "油卡", "网银汇划费", "汇款手续费", "手续费", "工资", "报销", "费用",
    "电梯款", "运费", "租金", "退款", "社保", "公积金", "利息", "结息", "实时缴税", "国内汇款", "汇兑",
    "代收费", "收费",
)
# 公共机构保留机构类型、去掉地名：会计判断只需要知道“这是国库/税务/银行收费”，不需要所在县市。
PUBLIC_NAME_PATTERNS = (
    (re.compile(r"^国家金库.*$"), "国家金库"),
    (re.compile(r"^.*税务局\d*$"), "税务局"),
    (re.compile(r"^.*银行.*收费业务专用账号$"), "银行收费专用账户"),
)
COMPANY_CATEGORY_WORDS = (
    "建筑劳务", "建材", "商贸", "贸易", "建设集团", "建设", "电气工程", "工程", "石油", "石化", "物流", "运输",
    "科技", "银行",
)
BANK_BRANDS = (
    "中国工商银行", "中国农业银行", "中国银行", "中国建设银行", "交通银行", "中国邮政储蓄银行", "招商银行",
    "浦发银行", "中信银行", "兴业银行", "民生银行", "光大银行", "平安银行", "华夏银行", "广发银行",
)
_LONG_ID = re.compile(r"[0-9A-Za-z]{8,}")
KEY_FILE = ".脱敏密钥"


def core_name(name: str) -> str:
    """去掉组织形式和行业词，得到字号部分（如“某某建材贸易有限公司”→“某某”），用于泄漏扫描。"""
    core = re.sub(r"(股份有限公司|有限责任公司|有限公司|集团|公司)$", "", name)
    changed = True
    while changed:
        changed = False
        for word in COMPANY_CATEGORY_WORDS:
            if core.endswith(word) and len(core) > len(word):
                core = core[: -len(word)]
                changed = True
    return core


class RedactionLeak(RuntimeError):
    def __init__(self, count: int, kinds: list[str]) -> None:
        super().__init__(f"脱敏输出仍含 {count} 个敏感值（类型：{'、'.join(sorted(set(kinds)))}），已拒绝写出")
        self.count = count
        self.kinds = kinds


def load_or_create_key(private_dir: Path) -> bytes:
    path = private_dir / KEY_FILE
    if path.exists():
        key = bytes.fromhex(path.read_text(encoding="ascii").strip())
        if len(key) < 16:
            raise ValueError("脱敏密钥文件损坏")
        return key
    private_dir.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    path.write_text(key.hex(), encoding="ascii")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return key


class PrivateView:
    """私有底稿：原样输出。与 RedactedView 同接口，保证两份底稿由同一构建代码生成。"""

    redacted = False

    def name(self, value: str, role: str = "") -> str:
        return value

    def account(self, value: str) -> str:
        return value

    def bank(self, value: str) -> str:
        return value

    def free_text(self, value: str) -> str:
        return value

    def ident(self, value: str, kind: str) -> str:
        return value

    def filename(self, value: str, kind: str, index: int) -> str:
        return value


class RedactedView:
    redacted = True

    def __init__(
        self,
        key: bytes,
        *,
        own_names: set[str],
        own_accounts: set[str],
        extra_terms: set[str] | frozenset[str] = frozenset(),
    ):
        self._key = key
        self._own_names = {n for n in own_names if n}
        self._own_accounts = {a for a in own_accounts if a}
        self.mapping: dict[str, str] = {}
        # 敏感值 → 类型；用于最终泄漏扫描。
        self.sensitive: dict[str, str] = {}
        for name in self._own_names:
            self.sensitive[name] = "本公司名称"
            core = core_name(name)
            if len(core) >= 2:
                self.sensitive.setdefault(core, "本公司简称")
        for acct in self._own_accounts:
            self.sensitive[acct] = "本公司账号"
        for term in extra_terms:
            if term.strip():
                self.sensitive[term.strip()] = "自定义敏感词"

    def _tag(self, kind: str, value: str) -> str:
        return hmac.new(self._key, f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()[:6].upper()

    @staticmethod
    def public_alias(name: str) -> str:
        return next((alias for pattern, alias in PUBLIC_NAME_PATTERNS if pattern.match(name)), "")

    def name(self, value: str, role: str = "") -> str:
        value = value.strip()
        if not value:
            return ""
        if value in self._own_names:
            return "本公司"
        public = self.public_alias(value)
        if public:
            self.sensitive.setdefault(value, "机构全称")
            return public
        if role == "individual" or (len(value) <= 4 and "公司" not in value):
            alias = f"自然人-{self._tag('person', value)}"
            self.sensitive.setdefault(value, "自然人姓名")
        else:
            category = next((w for w in COMPANY_CATEGORY_WORDS if w in value), "单位")
            alias = f"单位-{self._tag('org', value)}（{category}）"
            self.sensitive.setdefault(value, "单位名称")
        self.mapping[alias] = value
        return alias

    def account(self, value: str) -> str:
        value = value.strip()
        if not value:
            return ""
        self.sensitive.setdefault(value, "银行账号")
        prefix = "本公司账户" if value in self._own_accounts else "账户"
        return f"{prefix}尾号{value[-4:]}" if len(value) > 6 else f"{prefix}（已脱敏）"

    def bank(self, value: str) -> str:
        value = value.strip()
        if not value:
            return ""
        brand = next((b for b in BANK_BRANDS if value.startswith(b)), "")
        return f"{brand}（网点已脱敏）" if brand else "银行（已脱敏）"

    def free_text(self, value: str) -> str:
        if not value.strip():
            return ""
        found: list[str] = []
        rest = value
        for word in PURPOSE_VOCABULARY:  # 长词在前，命中后从剩余文本删除，避免“油卡充值/油卡”重复
            if word in rest:
                found.append(word)
                rest = rest.replace(word, " ")
        kept = "、".join(found)
        return f"{kept}（其余文本已脱敏）" if kept else "（文本已脱敏）"

    def ident(self, value: str, kind: str) -> str:
        value = value.strip()
        if not value:
            return ""
        self.sensitive.setdefault(value, kind)
        return f"{kind}#{self._tag(kind, value)}"

    def filename(self, value: str, kind: str, index: int) -> str:
        suffix = Path(value).suffix
        return f"{kind}-{index:02d}{suffix}"

    def register_free_text_ids(self, text: str) -> None:
        """把自由文本中的长编号（流水号、业务编号、税号等）登记为敏感值，供泄漏扫描使用。"""
        for match in _LONG_ID.findall(text or ""):
            if sum(ch.isdigit() for ch in match) >= 6:
                self.sensitive.setdefault(match, "编号")

    def scan(self, strings: list[str]) -> list[str]:
        """返回泄漏的敏感值类型列表；空列表表示通过。"""
        blob = "\n".join(strings)
        leaks = []
        for value, kind in self.sensitive.items():
            if len(value) < 2:
                continue
            if value.isascii() and value.isalnum():
                # 账号/编号按完整词边界匹配：短账号嵌在哈希串或更长编号中不构成泄漏。
                if re.search(rf"(?<![0-9A-Za-z]){re.escape(value)}(?![0-9A-Za-z])", blob):
                    leaks.append(kind)
            elif value in blob:
                leaks.append(kind)
        return leaks
