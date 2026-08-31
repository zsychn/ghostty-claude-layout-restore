# ghostty-claude-layout-restore

保存并恢复 Ghostty 工作区 —— 窗口、tab、**分屏**，以及每个分屏里正在跑的 Claude Code 会话。

[English](README.md)

```console
$ gsess save
已保存: 1 窗口 / 5 tab / 8 分屏 / 8 个 Claude 会话

# ……退出 Ghostty、重启、回来、开一个终端……
# 每个分屏都回到原目录，跑着 `claude --resume <它自己那个会话>`
```

命令名是 `gsess`。中文界面设 `GSESS_LANG=zh`（系统 locale 是中文时自动启用）。

## 为什么又造一个

[`ghostty-claude-code-session-restore`](https://github.com/AtAFork/ghostty-claude-code-session-restore)
比这个早，核心思路做得不错 —— **如果它够用，就用它**。
这个工具存在的理由只有一个：**它能恢复分屏。**

那个项目用 System Events 发 `Cmd+T`、再把命令「打」进新 tab。这套做法早于
Ghostty 1.3.0（2026 年 3 月），而 1.3.0 才加入了带 `split` 命令的原生 AppleScript 字典。
所以一个有 4 个分屏的 tab，恢复回来会变成 4 个独立 tab，多窗口布局也会被拍平 ——
它的 README 自己也是这么写的。

如果你的工作区本来就是一排平铺的 tab，这个差别对你没意义，而那个项目还支持
Codex 和 Cmux，这个不支持。

| | AtAFork | 本项目 |
|---|---|---|
| 分屏 / 多窗口 | 拍平成 tab | **保留** |
| 怎么建 tab | System Events 发 `Cmd+T`，命令靠键盘打进去 | 原生 AppleScript `command:` |
| macOS 权限 | 辅助功能 | 自动化 |
| Codex、Cmux | ✅ | ❌ 只支持 Claude Code |
| 安装 | 往 shell rc 里塞约 40 行 | 一个 symlink + 6 行 |

## 安装

macOS、**Ghostty ≥ 1.3.0**、Python 3.8+。零第三方依赖。

```bash
git clone https://github.com/zsychn/ghostty-claude-layout-restore.git
cd ghostty-claude-layout-restore
ln -s "$PWD/gsess.py" /usr/local/bin/gsess
```

然后把自动的两半打开：

```bash
gsess agent install                        # 每 30 秒自动快照
gsess shell-init zsh >> ~/.zshrc           # Ghostty 退出过之后，开终端自动恢复
```

`shell-init` 也支持 `bash` 和 `fish`。第一次运行时 macOS 会弹窗要「自动化」权限。

## 用法

```
gsess save                  给当前工作区拍快照
gsess status                当前状态 vs 最新快照
gsess restore               还原（开新窗口）
gsess restore --dry-run     只打印将执行的 AppleScript，不动手
gsess autorestore           围绕当前 shell 还原（shell-init 用的就是它）
gsess list                  历史快照
gsess agent install|uninstall|status
gsess shell-init zsh|bash|fish
```

### 自动那条路是怎么跑的

Ghostty 开着的时候，launchd 定时器每 30 秒拍一次快照。当它发现 Ghostty 已经退出、
而且身后留着一份有内容的快照，就竖一个 pending 标记。你下次打开 Ghostty 终端时，
shell 片段看到标记，调用 `gsess autorestore`，它会：

- 把其余所有 tab、分屏、窗口**围绕调用它的那个 shell**建起来
- 把「你正待着的这个 tab」该跑的命令打印出来，由片段 `eval` 执行

所以不会多出一个空窗口。恢复出来的分屏都带 `GSESS_RESTORED=1`，片段在里面不会再触发
（它们跑的是 login shell，不防就会无限递归）。

三道防呆：

- Ghostty 没运行 → 整个跳过，不写快照
- Ghostty 在运行但一个 Claude 会话都没有 → 保留上一次快照（`--force` 可覆盖）
- 标记用原子 rename 认领，所以同时开好几个 tab 也只会恢复一次；而且除非 Ghostty
  是刚启动的状态（一个窗口、一个 tab、一个分屏），autorestore 会拒绝执行

除此之外恢复都是手动的 —— 开机登录不该自己弹出十五个窗口。

## 分屏 ↔ 会话是怎么对上的

这一步必须精确：同一个目录下开好几个分屏是完全正常的用法，而这正是「按目录匹配」
悄悄出错的地方。三个来源交叉验证：

1. **Ghostty 终端标题** —— Claude Code 把 sessionId 的前 16 个字符写进了标题
   （`proj · 某会话 · 1a2b3c4d-5e6f-4a`）。这是唯一能区分**同目录**两个分屏的来源，
   所以作为主来源。
2. **`~/.claude/sessions/<pid>.json`** —— 进程还活着的会话，其 id、目录、显示名以此为准。
   CLI flags 也是从这里的 pid 反查进程命令行拿到的。
3. **`~/.claude/projects/<目录>/<sessionId>.jsonl`** —— 把 16 位前缀补成完整 UUID，
   同时证明这段记录还在。

`gsess status` 会显示每个分屏是靠哪种方式匹配上的。如果你的终端标题被覆盖了，
会退回「按工作目录匹配」并把这些分屏标成 `~` —— 这种兜底**没法**区分同目录的分屏，
它会直说，而不是悄悄猜一个。

### flags 也会带回来

用 `claude --model sonnet --dangerously-skip-permissions` 起的会话，恢复时这些 flag 会跟着回来。
会话选择类的 flag（`--resume`、`--continue`、`--fork-session` 等）会被丢掉，因为 gsess
自己会给 `--resume`；位置参数也会丢掉 —— 把当初那句初始 prompt 重放一遍等于又发给模型一次。
`restore --no-flags` 可以关掉重放。

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
  适合开工，但不是「你实际开着什么」的快照。
- [tabkeep](https://github.com/rohansx/tabkeep) —— Linux 上的同类思路（读 `/proc`）；
  按目录反查会话，所以同目录的多个分屏会塌缩成同一个。

## 开发

```bash
python3 -m unittest discover -s tests -v
```

47 个测试，不需要 Ghostty，也不需要 macOS —— AppleScript 的输出以字符串喂进去，
会话库以 dict 传入。

## 许可

MIT
