# gsess

保存并恢复 Ghostty 工作区 —— 窗口、tab、分屏，**以及每个分屏里正在跑的 Claude Code 会话**。

[English](README.md)

```console
$ gsess save
已保存: 1 窗口 / 5 tab / 8 分屏 / 8 个 Claude 会话 -> ~/.local/state/gsess/state.json

# ……退出 Ghostty、重启、回来……

$ gsess restore
将恢复: 1 窗口 / 5 tab / 8 分屏 / 8 会话
恢复中 …
完成。
```

每个分屏都回到原来的目录，并且已经在跑 `claude --resume <它自己那个会话>`。

> 中文界面：设 `GSESS_LANG=zh`（或系统 locale 是中文时自动启用）。

## 为什么需要它

这件事的两半各自都已经被解决，但它们互相不知道对方存在：

- Ghostty 的 `window-save-state` 能恢复工作区的**形状**，但每个分屏回来都是空 shell。
- `claude --resume <id>` 能恢复**一段对话**，前提是你知道哪段对话属于哪个分屏。

官方版本的这个需求已经被标记为不做
（[claude-code#43262](https://github.com/anthropics/claude-code/issues/43262)）。
gsess 就是中间缺的那一块。

## 安装

需要 macOS、**Ghostty ≥ 1.3.0**（要有 AppleScript 支持）、Python 3.8+。零第三方依赖。

```bash
git clone https://github.com/zsychn/gsess.git
cd gsess
ln -s "$PWD/gsess.py" /usr/local/bin/gsess    # 或 PATH 里任何位置
```

第一次运行时 macOS 会弹窗要「自动化」权限（控制 Ghostty）。不需要辅助功能权限。

## 用法

```
gsess save                  给当前工作区拍快照
gsess status                当前状态 vs 最新快照
gsess restore               还原
gsess restore --dry-run     只打印将执行的 AppleScript，不动手
gsess list                  历史快照
gsess agent install         装 launchd 定时器，每 60 秒自动快照
gsess agent uninstall       停掉
```

### 让它扛得住重启

快照只有在你**关掉之前**拍的才有用。装上定时器：

```bash
gsess agent install --interval 60
```

两道防呆，避免定时任务把你要恢复的东西冲掉：

- Ghostty 没在运行 → 整个跳过，不写快照
- Ghostty 在运行但一个 Claude 会话都没有 → 保留上一次快照（`--force` 可强制覆盖）

所以最终留下来的，永远是你**最后一次有内容的**工作区，而不是你关闭前那个空壳。

恢复是刻意做成手动的 —— 开机登录不该自己弹出十五个窗口。

## 分屏 ↔ 会话是怎么对上的

这一步必须精确，因为「同一个目录下开好几个分屏」是完全正常的用法。三个来源交叉验证：

1. **Ghostty 终端标题** —— Claude Code 会把 sessionId 的前 16 个字符写进标题
   （`proj · my-session · 1a2b3c4d-5e6f-4a`）。这是唯一能把**同目录**的两个分屏区分开的来源，
   所以作为主来源。
2. **`~/.claude/sessions/<pid>.json`** —— 进程还活着的会话，其 sessionId / 目录 / 名字以此为准。
3. **`~/.claude/projects/<目录>/<sessionId>.jsonl`** —— 用 16 位前缀补全成完整 UUID，
   同时证明这段记录还在。

`gsess status` 会显示每个分屏是靠哪种方式匹配上的。如果你的终端标题被覆盖或禁用了，
gsess 会退回到「按工作目录匹配」，并把这些分屏标成 `~` —— 这种兜底**没法**区分同目录的分屏，
它会直说，而不是悄悄猜一个。

## 恢复什么、不恢复什么

会恢复：

- 窗口 / tab / 分屏结构，以及原来选中的是哪个 tab
- 每个分屏的工作目录
- 每个分屏在正确目录下 `claude --resume <id>`
- 退出 Claude 后落回一个正常 shell，而不是分屏直接关掉

不恢复：

- **滚动历史**，以及 agent 之外的任何进程（跑着的 `npm run dev` 不会回来）
- **分屏的精确比例。** Ghostty 的 AppleScript 只能创建分屏、不能设尺寸，所以一律 50/50。
- **分屏的排布结构。** 这个 API 只给出一个 tab 里有哪些分屏，不给它们的布局树，
  所以排布是按默认策略重建的（2 个 → 左右，4 个 → 田字）。
  策略以 `split_plan` 存在快照里，可以手改：

  ```json
  "split_plan": [[0, "right"], [0, "down"], [1, "down"]]
  ```

  每一项是 `[要切分的分屏序号, 方向]`，按顺序执行。

已经在运行的会话会被跳过，所以 `gsess restore` 跑两次是安全的 —— 不会把一个活着的对话
开出第二份。真想那样就加 `--force`。

## 和其他工具的关系

- [gtab](https://github.com/Franvy/gtab) —— 命名式的 Ghostty 工作区，分屏几何还原得更准
  （它用 Accessibility 读每个分屏的位置）。但它不恢复运行中的进程，agent 会话回来是空的。
- [gpane](https://github.com/minorole/gsx) —— 启动**预先定义好的**布局，每个分屏跑指定命令。
  适合开工，但不是「你实际开着什么」的快照。
- [tabkeep](https://github.com/rohansx/tabkeep) —— 思路相同，但只支持 Linux（靠读 `/proc`），
  而且是按目录反查会话，所以同目录的多个分屏会塌缩成同一个 id。

## 开发

```bash
python3 -m unittest discover -s tests -v
```

29 个测试，不需要 Ghostty、也不需要 macOS —— AppleScript 的输出以字符串喂进去，
会话库以 dict 传入。

## 许可

MIT
