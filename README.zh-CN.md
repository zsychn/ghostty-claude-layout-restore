# ghostty-claude-layout-restore

保存并恢复 Ghostty 工作区 —— 窗口、tab、**分屏**，以及每个分屏里正在跑的 Claude Code 会话。

[English](README.md)

```console
$ gsess save
已保存: 1 窗口 / 4 tab / 7 分屏 / 7 个 Claude 会话

# ……退出 Ghostty、重启、回来……

$ gsess restore
将恢复: 1 窗口 / 4 tab / 7 分屏 / 7 会话
恢复中 …
完成。
```

每个分屏都回到原目录，跑着 `claude --resume <它自己那个会话>`，连原来带的 flags 一起。
命令名是 `gsess`。

这是个**手动**工具，后台不跑任何东西 —— 理由见[为什么是手动的](#为什么是手动的)。

## 为什么又造一个

[`ghostty-claude-code-session-restore`](https://github.com/AtAFork/ghostty-claude-code-session-restore)
比这个早，核心思路做得不错 —— **如果它够用，就用它**。
这个工具存在的理由只有一个：**它能恢复分屏。**

那个项目用 System Events 发 `Cmd+T`、再把命令「打」进新 tab。这套做法早于
Ghostty 1.3.0（2026 年 3 月），而 1.3.0 才加入了带 `split` 命令的原生 AppleScript 字典。
所以一个有 4 个分屏的 tab，恢复回来会变成 4 个独立 tab，多窗口布局也会被拍平 ——
它的 README 自己也是这么写的。

| | AtAFork | 本项目 |
|---|---|---|
| 分屏 / 多窗口 | 拍平成 tab | **保留** |
| 怎么建 tab | System Events 发 `Cmd+T`，命令靠键盘打进去 | 原生 AppleScript `command:` |
| macOS 权限 | 辅助功能 | 自动化 |
| 存 / 恢复 | 全自动，daemon + shell 钩子 | **手动，刻意如此** |
| Codex、Cmux | ✅ | ❌ 只支持 Claude Code |

如果你的工作区本来就是一排平铺的 tab，第一行对你没意义，那个项目做的事更多。

## 安装

macOS、**Ghostty ≥ 1.3.0**、Python 3.8+。零第三方依赖，单文件。

```bash
git clone https://github.com/zsychn/ghostty-claude-layout-restore.git
cd ghostty-claude-layout-restore
ln -s "$PWD/gsess.py" /usr/local/bin/gsess
```

第一次运行时 macOS 会弹窗要「自动化」权限。不需要辅助功能权限。

## 用法

```
gsess save                  给当前工作区拍快照
gsess status                当前状态 vs 最新快照
gsess restore               还原
gsess restore --dry-run     只打印将执行的 AppleScript，不动手
gsess list                  历史快照（保留 20 份）
```

快照存在 `~/.local/state/gsess/`（可用 `GSESS_STATE_DIR` 覆盖）。
`GSESS_LANG=zh` 切中文界面。

两道防呆，避免一次随手的 `save` 把你真正想要的那份冲掉：

- Ghostty 没运行 → 什么都不写
- Ghostty 在运行但一个 Claude 会话都没有 → 保留上一次快照（`--force` 可覆盖）

## 为什么是手动的

自动快照听上去显然更好，其实不然：

**你并不总是想记录当前状态。** 一个做实验做到一半的工作区，或者刚拆干净的工作区，
会毫不客气地覆盖掉你真正想要回来的那个布局。「什么时候的布局值得留」本身就是这件事的核心，
而只有你知道答案。

**而且在 macOS 上，自动的代价比看起来大。** 拍快照必须走 AppleScript ——
那是唯一能看见 tab 和分屏的途径。而 macOS 的自动化权限是按**责任进程**授予的：
LaunchAgent 是它自己的责任进程，没有授权；它又没有界面，连授权框都弹不出来。于是直接失败：

```
error: Not authorized to send Apple events to Ghostty. (-1743)
```

从 Ghostty **内部**的 shell spawn 出来的进程倒是能继承授权，所以出路是「由 shell rc 启动一个
后台 daemon」—— 为了自动化一个你多半更想自己做的决定，代价是一个常驻进程加几行塞进
`.zshrc` 的代码。（那些用 `ps`/`lsof` 轮询而不用 AppleScript 的工具没有这个问题，
但这也正是它们看不见你的分屏的原因。）

所以就是：觉得这个工作区值得留就 `gsess save`，想要回来就 `gsess restore`。

## 分屏 ↔ 会话是怎么对上的

这一步必须精确：同一个目录下开好几个分屏是完全正常的用法，而这正是「按目录匹配」
悄悄出错的地方。三个来源交叉验证：

1. **Ghostty 终端标题** —— Claude Code 把 sessionId 的前 16 个字符写进了标题
   （`proj · 某会话 · 1a2b3c4d-5e6f-4a`）。这是唯一能区分**同目录**两个分屏的来源，
   所以作为主来源。
2. **`~/.claude/sessions/<pid>.json`** —— 进程还活着的会话，其 id、目录、显示名以此为准。
   CLI flags 也是靠这里的 pid 反查进程命令行拿到的。
3. **`~/.claude/projects/<目录>/<sessionId>.jsonl`** —— 把 16 位前缀补成完整 UUID，
   同时证明这段记录还在。

`gsess status` 会显示每个分屏是靠哪种方式匹配上的。如果你的终端标题被覆盖了，
会退回「按工作目录匹配」并把这些分屏标成 `~` —— 这种兜底**没法**区分同目录的分屏，
它会直说，而不是悄悄猜一个。

### flags 会跟着回来

用 `claude --model sonnet --dangerously-skip-permissions` 起的会话，恢复时这些 flag 会带回来。
会话选择类的 flag（`--resume`、`--continue` 等）会丢掉，因为 gsess 自己会给；
位置参数也会丢掉 —— 把当初那句初始 prompt 重放一遍等于又发给模型一次。`--no-flags` 可关掉重放。

### 怎么找到 `claude` 可执行文件

恢复出来的分屏跑的是 `zsh -lc ...` —— 它是 **login shell 但不是交互式的**，
所以**不会**读 `.zshrc`。而绝大多数安装方式正是靠 `.zshrc` 把 claude 放进 PATH 的。
于是直接按名字调用会得到 `command not found: claude`、退出码 127，
后面的 `exec zsh -l` 立刻接班给你一个完全正常的 shell ——
看上去布局恢复好了，实际上每个会话都悄无声息地没了。

所以 gsess 会在生成脚本前先解析出绝对路径，依次尝试：
`$GSESS_CLAUDE_BIN` → `which claude` → `$SHELL -ic 'command -v claude'`
（交互式 shell **会**读 `.zshrc`）→ 常见安装位置。
`restore` 会打印它选中的可执行文件；一个都找不到时**直接拒绝执行**，
而不是吐出一堆注定悄悄失败的命令。

如果你的安装位置比较特别：

```bash
GSESS_CLAUDE_BIN=/path/to/claude gsess restore
```

## 恢复什么、不恢复什么

会恢复：窗口/tab/分屏结构、原来选中的 tab、每个分屏的工作目录、带原始 flags 的
`claude --resume <id>`，以及退出 Claude 后落回一个正常 shell 而不是分屏直接关掉。

不恢复：

- **滚动历史**，以及 agent 之外的任何进程（跑着的 `npm run dev` 不会回来）
- **分屏的精确比例** —— Ghostty 的 AppleScript 只能创建分屏、不能设尺寸，一律 50/50
- **分屏的排布结构** —— 这个 API 只给出一个 tab 里有哪些分屏，不给布局树，
  所以按默认策略重建（2 个 → 左右，4 个 → 田字），策略以 `split_plan` 存在快照里，可手改：

  ```json
  "split_plan": [[0, "right"], [0, "down"], [1, "down"]]
  ```

  每项是 `[要切分的分屏序号, 方向]`，按顺序执行。

已经在运行的会话会被跳过，所以 `restore` 跑两次是安全的 —— 不会把一个活着的对话开出第二份。
真想那样就加 `--force`。

## 其他值得知道的工具

- [gtab](https://github.com/Franvy/gtab) —— 命名式 Ghostty 工作区，分屏几何还原得更准
  （用 Accessibility 读每个分屏的位置）。但不恢复运行中的进程，agent 会话回来是空的。
- [gpane](https://github.com/minorole/gsx) —— 启动**预先定义好的**布局，每个分屏跑指定命令。
  适合开工，但不是快照。
- [tabkeep](https://github.com/rohansx/tabkeep) —— Linux 上的同类思路（读 `/proc`）；
  按目录反查会话，所以同目录的多个分屏会塌缩成同一个。

## 开发

```bash
python3 -m unittest discover -s tests -v
```

44 个测试，不需要 Ghostty，也不需要 macOS —— AppleScript 的输出以字符串喂进去，
会话库以 dict 传入。

## 许可

MIT
