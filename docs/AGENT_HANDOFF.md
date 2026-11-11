# Agent Handoff 1.1：通用任务接力

离线、标准库工具；模型和人读取同一协议。任务由 `project + task` 标识，线程链接是本地查找别名。工具不读聊天数据库、不调用模型、不上传内容、不执行笔记中的命令，也不转移登录或工具权限。

## 1. 切换 Agent 时复制什么

推荐复制工具生成的交接码：

```text
HANDOFF --project Example ticket --task task-A
```

输出只有任务定位与私有根目录，例如：

```json
{"handoff":"handoff://Example/task-A","state_root":"<私有根目录>"}
```

把这一行交给接手 Agent，要求它用 Agent Handoff 读取对应摘要。完整 `handoff://项目/任务` 始终指向明确任务线，跨 Agent、会话和 Git 分支均可继续使用。

也可粘贴 Codex 等工具的线程深度链接或 UUID，但须先绑定一次：

```text
HANDOFF --project Example bind --task task-A --actor Agent-A --expect-revision 1 --ref "<线程链接或UUID>"
HANDOFF resume --ref "<已登记的线程链接或UUID>"
```

`init --ref` 可在创建时直接绑定。含同一 UUID 的链接与裸 UUID 可互相查找；其它平台标识按登记原文匹配。不会打开 URL、联网取聊天或自动推断任务。一个线程关联多条任务时返回歧义，须改用具体 `handoff://`；不会按时间选“最新”。`resolve --ref` 仅查看映射。

接手方需要工具入口、对应工作目录及私有状态目录的访问权限。只粘贴链接不会授予这些能力；缺权限时说明缺失范围，由会话配置补齐，不能把私有数据搬进公开工作树绕过。

## 2. 解压和初始化

Mac Apple Silicon 包使用 `agent-handoff.command`，Windows x64 包使用 `agent-handoff.cmd`，自带固定 CPython 3.14.6，无需 pip 或系统 Python。下文 `HANDOFF` 代表平台启动器，源码模式可替换为 `python3 scripts/dev/agent_handoff.py`。占位符须换成实际值，全局选项位于子命令前。

```text
HANDOFF --project Example init --workspace "<工作目录>" --title "任务名称" --goal "完成目标" --actor Agent-A --acceptance "完成标准" --next-step "首个具体动作" --scope src docs --ref "<线程链接>"
```

Git 仓库需要现有 Git。普通文件或无 Git 环境用 `--no-git --scope draft.md`，只记录指定文件，不伪称存在 Git 身份。交互菜单支持创建、列表与链接/ID 接手，并询问实际目标、标准和下一步；CLI 未填写标准/下一步的模板提示须在交出前补齐。

私有根目录依次取 `--state-root`、`AGENT_HANDOFF_HOME`、`~/.agent-handoff`。所有参与者使用同一根目录；Windows 默认取用户主目录。私有根不得位于任何 Git 工作树内（包括 ignored），也不能与登记的工作目录互相包含。

```text
私有根目录/
├── .write.lock
└── Example/
    ├── INDEX.json
    └── tasks/task-A/
        ├── CURRENT.md
        └── EVENTS.jsonl
```

## 3. 最少读取，必要时展开

`resume --ref ...`、`resume --task ...` 和 `show` 默认输出一次紧凑 JSON 摘要，预算为 3000 字符，可用 `--max-chars 2000..20000` 调整。CURRENT.md 保存同一摘要，不再重复嵌入完整 notes 和文件哈希表。字符预算不等于精确 token 数。

摘要保留身份、目标、下一步、关键约束与待确认操作数量；历史验证/判断优先展示最近条目。截断或省略字段进入 `omitted_fields`；涉及约束、授权、阻塞、进程或下一步时 `expand_before_action=true`，必须先展开再行动。全文在 journal 中完整保留，不因摘要预算删除。

```text
HANDOFF --project Example show --task task-A --section constraints
HANDOFF --project Example show --task task-A --section verification
HANDOFF --project Example show --task task-A --section operations
HANDOFF --project Example show --task task-A --full
```

默认 resume 只读任务状态，`live_check=not_run`，不重新哈希工作目录。claim 内置一次完整现场核对；需要事先诊断时才运行 `check` 或 `resume --verify`。check 默认最多列出 20 个变更路径/待确认操作，数量字段表示完整结果，`check --full` 展开。完整文件状态不会因输出裁剪而漏验。

list 默认最多 20 条，用 --offset 显式翻页，--all 才返回完整列表。没有常驻进程、定时轮询或自动保存 hook。不要循环执行 list/resume/check，也不要把完整日志或全仓库文档重复送入模型；按任务地图读取命中专题即可。

## 4. 何时保存

只在目标/约束变更、重要判断形成、验证完成、阻塞改变和交接时保存。普通读取、每个工具调用和无变化的检查不形成新检查点。checkpoint 内容与现场均未变化时不写 journal/CURRENT/INDEX，也不增加 revision。

```text
HANDOFF --project Example template --task task-A --output "<私有项目目录>/notes.json"
HANDOFF --project Example checkpoint --task task-A --actor Agent-A --expect-revision 2 --input "<私有项目目录>/notes.json"
```

交出任务优先一次保存并释放，避免 checkpoint 后紧接着再写一次 release：

```text
HANDOFF --project Example release --task task-A --actor Agent-A --expect-revision 3 --input "<私有项目目录>/notes.json" --processes-checked
HANDOFF claim --ref "handoff://Example/task-A" --actor Any-Agent --expect-revision 4 --previous-writer-stopped
```

没有新 notes 时 release 可仅用 `--next "下一步"`。调用前核对前一执行者和后台写入已收束；有漂移时先解释差异，再显式 `--accept-drift`。跨目录/机器接手用 `--workspace "<新目录>"`，旧验证不能冒充新环境验证。actor 是协作标签，不是身份凭据。

## 5. 保留哪些进度信息

状态协议为 `agent-handoff/v2`：project、task、title、revision、status、owner、updated_at、references、notes、snapshot、operations。notes 的 goal 是字符串，其余字段为字符串列表；空列表只表示未记录。

| notes 字段 | 必要内容 |
|---|---|
| goal / acceptance_criteria | 最新目标与可观察的完成标准 |
| constraints / authorizations | 约束；授权来源、对象、范围和有效条件 |
| decisions / attempts | 简短结论、理由和证据位置；失败方法及停止重试的原因 |
| changes | 本任务修改、既有修改、归属未知的文件 |
| verification | 命令、结果、对应 revision/文件指纹、环境与未覆盖项 |
| open_questions / next_steps | 阻塞；首个动作、预期结果与失败处理 |
| processes | 仍写入的进程、身份/日志位置和收束状态 |

各字段只写当前接手必需的短条目，证据引用文件/日志位置。详细复盘留在历史事件或私有审计文件，不在每次 notes 中累计复制。不得写入隐藏推理或把未验证判断当事实。

工具采集文件名、大小、内容 SHA-256、可执行位与 Git HEAD/分支/暂存区身份，不复制源文件内容。符号链接只记录链接本身，不追踪外部目标。明确工作目录优先于环境中的 Git 工作区/索引覆盖变量。scope 控制文件范围；无 scope 的 Git 任务包括 tracked 与非 ignored 的 untracked 文件。

## 6. 操作结果和完成

可能产生重复后果的外部动作仍须在执行前记录 started、观察后记录 confirmed/failed_confirmed/unknown；不能为节省写入省略这两个检查点。工具只记账，不执行动作。

```text
HANDOFF --project Example event --task task-A --actor Agent-A --expect-revision 5 --operation export-001 --state started --detail "对象、范围与结果查询位置"
HANDOFF --project Example event --task task-A --actor Agent-A --expect-revision 6 --operation export-001 --state unknown --detail "返回中断；先只读核对结果"
```

同一 operation 不能再次 started，终态不能降级或重放。“没看到成功”只能记 unknown。完成使用 `checkpoint --status completed --processes-checked`；有未确认操作时拒绝完成。completed 后的新需求登记新任务，references 可继续补充。阻塞用 blocked 并记录原因。

## 7. 少写盘且可恢复

EVENTS.jsonl 是真值：首事件保存完整状态，后续 v2 事件只保存变更字段（put/edit/drop），仍保留单调 revision 与 SHA-256 前后链。v1 完整事件保持原字节可读，新写入追加 v2，绝不批量重写旧日志。同一私有根升级后应统一使用 1.1 工具；1.0 不能读取新事件。

内容相同时不提交；实际提交只更新本任务 CURRENT 和变化后的 INDEX，不重写其它任务的 CURRENT。命令内缓存已验证日志，文件元数据变化时失效，不另建磁盘缓存。读取不触发检查点保存。对 SSD 寿命更相关的是写入量；这里减少应用层重复写入，实际缓存和磁盘 I/O 仍由操作系统管理。

所有 project 的写命令共用私有根目录锁，使跨 project 认领核对与提交互斥。Unix flock / Windows msvcrt 锁随进程退出释放，短暂锁争用不等于后台轮询。只读命令不持写锁。要求本机文件系统，不承诺云盘/网络盘跨主机并发。

先追加事件并 fsync，再原子更新派生文件。中断后 `repair --task ...` 只重建指定任务与索引；内容相同不改写。不完整末行须显式 `--discard-incomplete-tail`：先验证完整前缀、保留原字节备份，再恢复。完整错误事件、坏 delta、未来 schema、重复 JSON 键或错误哈希不能被清空覆盖。revision 过期必须重新读取，不能机械重试。

上限：10,000 文件、单文件 64 MiB、总计 512 MiB、notes 256 KiB、journal 32 MiB；超限停止，缩小 scope 或建立关联任务。退出码 0=命令完成（摘要未核对现场也为0），2=错误，3=实际 check 发现漂移/过期投影/未确认操作，130=中断。

## 8. 会话权限和便携包

接手会话需分别授权工作目录、私有状态目录及指定工具/测试命令。授权不足时指出具体缺项，不用其它命令绕过、不反复请求同一被拒调用；私有数据始终留在仓库外。检查点中的授权说明不替代这些会话权限。

公开输入仅为工具脚本、本文、LICENSE 和通用模板。便携包含逐文件 MANIFEST 与外层 SHA，不递归复制项目、私有检查点、模型审计、配置或 Git 历史。Mac runtime 精确移除 9 项已知 Windows 辅助文件，其它 Windows 载荷拒绝入包。

打包脚本 `scripts/dev/build_agent_handoff.py build` 接受平台、输出目录及 SHA 固定的 `--runtime-archive`。更新也可用 `--runtime-package <旧便携ZIP> --runtime-package-sha256 <可信外层SHA>`：先验外层哈希、内部清单和平台，只复用 python 成员，工具/说明重新取当前公开源码，避免重复下载运行时。用 `verify <ZIP>` 复核。

聚焦验证：`python3 -m pytest tests/test_agent_handoff.py tests/test_agent_handoff_packaging.py tests/test_development_documentation.py`。Mac/Windows 原生执行、Gatekeeper、签名和网络盘互斥的未覆盖项分别披露，不能用静态包校验替代。
