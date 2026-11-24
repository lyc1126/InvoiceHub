"""银行流水整理：把各银行对账单/回单翻译成标准记录，校验、匹配、给出建议分录并导出底稿。

数据流：银行适配器（如 boc.py）→ models 标准记录 → checks 勾稽 → matching 回单匹配
→ classify 建议分录 → workpaper 私有底稿 → redaction 脱敏底稿。
整条链只读源文件，不写公司资料夹 `凭证/` 状态，也不操作任何账套；建议分录必须人工确认。
"""

from __future__ import annotations

WORKPAPER_SCHEMA = "invoicehub.bank_workpaper/v1"
