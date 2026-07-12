# PRD：GFN Chrome 网页版窗口自动缩放

> [!NOTE]
> 本文档为产品需求文档（PRD），描述需求与设计约束，不包含最终实现。
> 状态：**草案**。涉及"待实测验证"的条目需在实现前于真实环境确认。
> 前置文档：[GeForce NOW 云游戏窗口支持 PRD](./geforce-now-support-prd.md)（下称"主 PRD"），特别是其风险 R8。

## 1. 背景与目标

### 1.1 背景

主 PRD 落地后，GFN 两种形态的现状分化：

- **GFN 原生客户端（`gfn_app`）**：流窗口为无边框 CEF 窗口、客户区即视频。Agent 启动时自动把客户区调整为 1280x720（`resize_client_area(manage_title_bar=False)`），并在缩放成功后提示串流渲染分辨率可能仍未跟随。该路径已实测跑通（2026-07-12 日志包 `MaaNTE-logs-0.0.9-gfn-test-*`，PinkPawHeist 多轮完整运行）。
- **GFN Chrome 网页版（`gfn_chrome`）**：**窗口化模式完全不可用**（主 PRD R8 实测）。页面自绘头部（标题条，实测 37px，见 §2）占据客户区顶部，游戏视频被下移**且按比例缩放**，所有固定 ROI 识别失败。当前运行前提为"16:9 显示器 + F11 全屏 + Windows 缩放 100%"。

F11 全屏前提对非 16:9 显示器用户（16:10、带鱼屏）不成立：全屏后视频上下留黑边，帧几何同样被破坏。这部分用户目前在 Chrome 形态下无解。

### 1.2 现状代码的两个缺陷

`agent/utils/win32_process.py` 的 `ensure_game_window_resolution()` gfn_chrome 分支（L671-688）：

1. **缩放目标错误**：把客户区调整为 1280x720。由于头部占掉顶部 37px，视频实际被压缩进 1280x683 区域（缩放 + 下移），**主动制造了 R8 描述的坏几何**。
2. **错误管理标题栏**：未传 `manage_title_bar`，走默认 `True` → `show_title_bar()` 向 Chrome 的自绘无边框窗口强加 `WS_CAPTION`，可能叠加原生标题栏、进一步压缩客户区。

### 1.3 目标

- GFN Chrome 窗口化模式下，Agent 自动把窗口客户区调整为 **1280 x (720 + 头部高度 H)**，使头部下方的串流视频恢复**原生 1:1 的 1280x720**（消除缩放误差，与 gfn_app 路径同源）。
- 缩放失败时优雅降级：任务不中断，输出明确的用户引导（对齐 gfn_app 的 `gfn_app_resize_failed` 行为）。
- 残留的"+H px 垂直平移"问题（见 §5）按**先实测、再定补偿方案**推进，本 PRD 不承诺补偿实现。

### 1.4 非目标

- 不在本期实现 +H px 平移的补偿机制（子窗口控制器、上游裁剪选项等仅作为候选方向记录，见 §5.3）。
- 不覆盖 Edge 及其他 Chromium 系浏览器（主 PRD §8 遗留）。
- 不改变 gfn_app 与本地客户端路径的任何行为。

## 2. 关键几何事实

| 形态 | 客户区构成 | 客户区 = 1280x720 时 | 客户区 = 1280x(720+H) 时 |
| --- | --- | --- | --- |
| GFN 原生客户端 | 客户区 = 视频 | 视频原生 1:1 720p ✅ | —（不适用） |
| GFN Chrome 窗口化 | 顶部头部 H(37px) + 视频 | 视频缩放至 1280x683 且下移 ❌（现状） | 视频原生 1:1 720p，但整帧内容相对 ROI 下移 H px ⚠️ |

约束条件（决定了 §5 残留问题的性质）：

- 头部在 Chrome 窗口的**客户区内部**（Chrome 自绘无边框窗口），`PrintWindow` 截图无法排除它。
- MaaFramework Win32 控制器无截图裁剪选项——`MaaCtrlOptionEnum`（`deps/include/MaaFramework/MaaDef.h` L201-212）仅有长/短边缩放与 `ScreenshotUseRawSize`。
- **实测踩坑（0.0.11-gfn-test）**：`interface.json` 未声明的控制器默认 `display_short_side=720`（`deps/tools/interface.schema.json` L412-416），MaaFramework 按**短边**（非长边）把任意原始截图等比缩放到该值。客户区调整为 1280x746 后，若不显式声明 `display_short_side`，MaaFW 仍会把 746 高的原始帧（含头部）压缩到短边=720，导致整帧连头部一起等比失真（1235x720），而非预期的"仅垂直平移"。**必须**在 `interface.json` 的 GFN-Chrome 控制器条目显式声明 `display_short_side = 720+H`，使缩放成功时截图 1:1 直通（见 FR2 补充）。
- 声明正确的 `display_short_side` 后，识别框坐标经控制器映射回客户区仍然一致，**识别驱动的点击不受平移影响**，受影响的只有写死的固定坐标（详见 §5.1）。

头部高度 H 的测量：主 PRD R8 最初目测估计约 26px；**该估计偏小**，经 0.0.12-gfn-test 实测截图（`screenshot/Screenshot 2026-07-12 194145.png`）逐像素测量确认为 **37px**——用 26px 时视频可用高度不足（746-26=720 看似够，但实际头部占用更多），浏览器按 `object-fit: contain` 等比缩小视频以适配剩余高度，两侧各留 10px 黑边（1260x709 而非 1280x720）。用正确的 37px 重新计算（客户区目标改为 1280x757），视频可用高度恢复满 720px，理论上黑边消失。注意 H 随 Windows DPI 缩放与 Chrome 版本变化（见 R2、FR5），当前 37px 为特定环境下的实测值。

## 3. 功能需求

### FR1 — 头部高度常量与覆盖参数（`agent/utils/win32_process.py`）

- 新增模块级常量 `GFN_CHROME_HEADER_HEIGHT = 37`（物理像素，见 §2 实测方法），注释标明实测来源与 DPI 依赖。
- `ensure_game_window_resolution()` 新增可选参数 `gfn_chrome_header_height`（默认取常量），并由 `resize_game_window` 动作的 `custom_action_param.header_height` 透传（FR4），供 DPI ≠ 100% 的用户手工覆盖。

### FR2 — gfn_chrome 缩放路径修正（`agent/utils/win32_process.py`）

gfn_chrome 分支对齐 gfn_app 分支的写法：

- 缩放目标改为 `(width, height + H)`，即基准调用下客户区 = 1280x757。
- 强制 `manage_title_bar=False`：不再向 Chrome 无边框窗口强加 `WS_CAPTION`（修复 §1.2 缺陷 2），`passthrough` 过滤列表同步加入 `manage_title_bar`。
- 复用现有 `ensure_process_client_size()` / `resize_client_area()`，不新增缩放原语。
- 优雅降级：缩放未生效时 `reason="gfn_chrome_resize_failed"`、`success` 置 `True`（任务继续），日志输出实际/期望客户区尺寸，引导用户手动调整窗口或退回 F11 全屏（对齐 gfn_app 的 `gfn_app_resize_failed` 语义）。
- 返回 dict 新增 `"video_size"` 键 =（客户区宽，客户区高 − H），供调用方区分"客户区尺寸"与"有效游戏画面尺寸"。
- **`interface.json` 配套变更（0.0.12-gfn-test 实测后补充，原 FR2 未预见）**：GFN-Chrome 控制器条目必须显式声明 `"display_short_side": 720 + H`。原因见 §2 实测踩坑——不声明时 MaaFW 默认按短边=720 缩放任意原始截图，会把含头部的 757 高原始帧整体压扁失真，而非仅保留预期的垂直平移。此项是让本 PRD 设计生效的**必要前提**，遗漏会导致画面全局失真（非本 PRD 设计目标的"仅 H px 平移"）。

### FR3 — Agent 启动检测适配（`agent/main.py::_check_game_resolution`）

- gfn_chrome 模式下，"分辨率正常"的判定基准从 `(1280, 720)` 改为 `(1280, 720 + H)`（容差不变）。
- `screen.update_screen_size()` 传入**有效视频尺寸** `(w, h - H)` 而非原始客户区尺寸——否则 `scale_y = 746/720 ≈ 1.036` 会以"缩放"模型错误描述实为"平移"的偏差，污染所有走 `screen.map_point/map_rect` 的自定义动作坐标。
- 缩放成功后输出与 gfn_app 同类的串流渲染分辨率告警（会话建立时已固定云端渲染分辨率，窗口缩放不追溯生效；引导在 GFN 设置固定 720p 或重启会话）。
- 探测/缩放结果日志包含 mode、客户区尺寸、有效视频尺寸、H 取值，便于 R8 回填。

### FR4 — `resize_game_window` 动作与用户提示（`agent/custom/action/Common/resize_game_window.py`、`utils/maafocus`）

- `_parse_optional_resize_kwargs()` 新增 `header_height` 参数解析（正整数校验），透传给 `ensure_game_window_resolution()`。
- PrintT 消息键更新（5 个 locale 同步：`assets/resource/locales/agent/{zh_cn,zh_tw,en_us,ja_jp,ko_kr}.json`）：
  - `gfn.mode_chrome_detected` 文案更新：窗口化模式已支持自动缩放（不再一律引导 F11）；
  - 新增 `gfn.chrome_resize_failed`：自动缩放失败时引导手动调整或 F11 全屏；
  - 新增 `gfn.chrome_stream_resolution_hint`：串流渲染分辨率未跟随的提示（与 gfn_app 文案同源）。
- 禁止 `print()`，调试细节走 `utils.logger`（`%` 风格格式化）。

### FR5 — 缩放后头部高度视觉校准（待实测验证）

缩放完成后通过控制器截取一帧，扫描顶部区域定位"头部条带下缘"（头部为近纯色横条 + 标题文字，与游戏画面存在明显行方差跳变）：

- 实测 H' 与配置 H 一致（±2px）：仅 DEBUG 记录。
- 不一致：WARNING 记录实测值，并用 H' 重新执行一次缩放（至多重试 1 次），最终以实测值更新 `screen.update_screen_size` 的有效视频尺寸。

该 FR 的检测算法与稳定性需实测确认（头部在深色/浅色主题下的外观、串流加载中黑屏的干扰），实现可作为独立 PR 跟进；FR1-FR4 不依赖它。

## 4. 非功能需求

- **零新增 Python 依赖**：FR5 的条带检测仅用现有 `numpy`/`opencv`（agent 已有依赖）。
- **平台守卫**：维持 `sys.platform` 守卫写法（参照 `resize_game_window.py` 现状）。
- **日志规范**：遵循 `maa-logging` 约定——`%` 风格格式化、DEBUG 记探测细节、WARNING 记降级路径。
- **向后兼容**：本地客户端与 gfn_app 路径行为零变化；新参数全部带默认值；`ensure_game_window_resolution` 返回 dict 只增键不改键。

## 5. 残留问题：+H px 垂直平移（实测门槛）

### 5.1 影响分类

缩放修正后，截图帧为 1280x(720+H)，游戏内容整体相对 720p 基准**纯平移** +H px（不再有缩放误差）。按坐标来源分类：

| 坐标来源 | 是否受影响 | 说明 |
| --- | --- | --- |
| 识别命中框驱动的点击（`target: true` / 节点默认） | ✅ 不受影响 | 帧与客户区 1:1，命中框 y 已含 +H，映射回客户区坐标正确 |
| 模板匹配 / OCR 的固定 `roi` | ⚠️ 视余量而定 | 内容比 ROI 作者预期低 H px；ROI 下方余量 ≥ H 的节点仍可命中，紧贴内容的 ROI 漏检 |
| 字面固定坐标 `target: [x,y,w,h]`、自定义动作硬编码坐标 | ❌ 系统性偏移 | 点击落点比预期高 H px |

### 5.2 实测验证计划（实现 FR1-FR4 后执行）

1. 窗口化 GFN Chrome + 自动缩放生效，运行代表性任务：`MakeCoffee`（密集固定 ROI/OCR）与 `PinkPawHeist`（自定义动作 + 固定坐标混合）。
2. 从 `maa.log` 统计 `Node.Recognition.Failed` 分布，输出"失败节点清单 + 坐标来源分类"。
3. 结论分流：
   - 失败集中在少量节点 → 逐节点扩 ROI / 调整坐标，窗口化即告可用；
   - 失败广泛 → 启动 §5.3 补偿方案评估，窗口化维持"实验性"标注，F11 全屏仍为推荐路径。

### 5.3 补偿方案候选（开放问题，本期不实现）

| 候选 | 思路 | 待验证点 |
| --- | --- | --- |
| Chrome 子窗口控制器 | 控制器直连 `Chrome_RenderWidgetHostHWND` 子窗口（网页内容区，不含浏览器自绘头部） | MaaToolkit 是否枚举子窗口；`PrintWindow` 对 GPU 合成子窗口是否黑屏；Seize 输入坐标基准 |
| 上游 MaaFW 截图裁剪选项 | 向 MaaFramework 提议 Win32 控制器新增客户区裁剪（offset/rect）选项 | 上游接受度与排期；MaaNTE 侧仅需 interface/控制器参数透传 |
| F11 全屏兜底（现状） | 16:9 显示器用户维持主 PRD R8 前提 | 无——已实测可用，作为文档化兜底 |

## 6. 风险与开放问题

| # | 风险 / 开放问题 | 影响 | 应对 |
| --- | --- | --- | --- |
| R1 | +H px 平移导致固定 ROI/坐标失效范围未知 | 窗口化可用性结论悬置 | §5.2 实测计划门控；失败广泛时降级为"实验性"并保留 F11 引导 |
| R2 | 头部高度随 Windows DPI 缩放与 Chrome 版本漂移（26px 仅为 100% DPI 实测值） | 缩放目标错位，重新引入缩放误差 | FR1 覆盖参数 + FR5 视觉校准；日志记录实测 H 供回填 |
| R3 | 串流渲染分辨率在会话建立时固定，窗口缩放不追溯生效（gfn_app 已实测同类问题） | 缩放成功但画面仍按原分辨率渲染，模板系统性失配 | FR3/FR4 告警引导：GFN 设置固定 720p 串流或缩放后重启会话 |
| R4 | Chrome 对外部 `SetWindowPos` 的响应（最小尺寸限制、页面 resize 事件后 GFN 播放器重排延迟） | 缩放后短窗口内截图几何仍旧 | 复用 `resize_client_area` 的轮询确认 + `settle_ms`；实测确认重排耗时后必要时上调默认 settle |
| R5 | 用户手动最大化/拖动窗口破坏已调好的几何 | 运行中途识别退化 | 本期不做窗口尺寸看护；日志可定位（`screen.update_screen_size` 仅启动时刷新），列入后续工作 |

## 7. 验收标准

- [ ] gfn_chrome 模式下 Agent 启动自动把客户区调整为 1280x(720+H)，日志输出客户区/有效视频双尺寸；本地客户端与 gfn_app 路径行为回归一致。
- [ ] 不再对 Chrome 窗口调用 `show_title_bar()`（无 `WS_CAPTION` 强加行为）。
- [ ] 缩放失败时任务不中断，`reason=gfn_chrome_resize_failed`，PrintT 引导消息可见。
- [ ] `screen.scaling_factors()` 在缩放成功后返回 (1.000, 1.000)（有效视频尺寸口径）。
- [ ] `custom_action_param.header_height` 覆盖生效（异常值被校验拒绝）。
- [ ] 5 个 locale 新增/更新键完整同步，`pnpm exec prettier --check` 通过。
- [ ] §5.2 实测报告产出：失败节点清单 + 分类 + 窗口化可用性结论，回填主 PRD R8 与本 PRD 状态。

## 8. 后续工作

按仓库 PR 约定拆分实现（全部合入 `dev`，分支命名 `feat/<name>`）：

1. `win32_process.py` FR1/FR2 + `main.py` FR3；
2. `resize_game_window` FR4 + maafocus 消息 + 5 locale；
3. FR5 视觉校准（独立 PR，依赖实测）；
4. §5.2 实测与文档回填（主 PRD R8 状态更新、用户使用说明）。

远期：§5.3 补偿方案评估；R5 运行中窗口尺寸看护。
