# QSForge 快速入门（中文）

> 完整说明见 `README.md`（英文）。本文档聚焦安装和日常使用。

## 它是什么

**QSForge** 是一款 Windows 桌面软件，把 Revit 模型（`.rvt`）转成一份"健康报告"，60 到 120 秒出结果。回答两个问题：

- **QS 视角：** 这个模型能不能直接做工程量计算（QTO）？大概要多花多少小时？
- **BIM 视角：** 具体是哪些 Revit Element 缺体积 / 缺楼层 / 缺材质？给出 Element ID 清单，BIM 工程师可直接粘到 Revit 的"按 ID 选择"对话框里定位。

整个过程不需要 Revit license、不联网、不上传文件、不修改原 `.rvt`。

---

## 能做什么 / 不能做什么

先明确期望，避免误用。

### ✅ 它能做什么

| 能力 | 说明 |
|---|---|
| 读 `.rvt` 文件 | 不需要安装 Revit，不需要 Revit license |
| 60–120 秒出结果 | 200 MB / 7 万构件模型大约 1 分半 |
| 给出 **0–100 分** 和判定 | Ready / Conditionally Ready / High Risk / Do Not Use |
| 估算"额外 QS 工时" | 告诉你这个模型直接做 QTO 要多烧几小时 |
| 列 **9 项具体检查** | 体积/楼层/材质/通用模型/概念体/跨层柱墙/门窗寄主/嵌套/组合层 |
| 给出 **Revit Element ID 清单** | BIM 工程师可直接 `AD` 快捷键在 Revit 里定位 |
| 一键复制 ID 到剪贴板 | 粘进邮件就能发 |
| **导出 PDF 报告** | 分两页：QS 看的执行摘要、BIM 看的详细清单 |
| 全程离线 | 不联网、不上传、不修改原文件 |

### ❌ 它不能做什么

| 不能做 | 替代方案 |
|---|---|
| ❌ 不直接生成工程量 / BOQ | 它告诉你"模型能不能用来算量"，算量还是要用 QS 自己的工具（Cubicost / CostX / 手工等） |
| ❌ 不修改 Revit 模型 | 只做检测，不碰原 `.rvt`。问题点整理好发回给 BIM 团队修 |
| ❌ 不做碰撞检测 / MEP 协调 | 用 Navisworks / Solibri |
| ❌ 不做规范合规性检查 | 用 Solibri / 建筑规范专用工具 |
| ❌ 不对接价格库 / WBS | QS 本职工作，不归它管 |
| ❌ 不支持 IFC / DWG / DGN | 现版本只认 `.rvt`；未来版本可能扩展 |
| ❌ 不能替代人工判断 | 分数是参考，临界分数（60–75）的模型建议双人复核 |

### 一句话

> **"给不给做 QTO、要花多少额外时间"——它来告诉你；**
> **"具体怎么算 QTO"——还是你的事。**

---

## 安装（两种方式任选其一）

> **DDC 转换器已内置**，不需要单独安装任何东西。约需 700 MB 硬盘空间。

### A. 安装包方式（推荐）

1. 双击 `QSForge-Setup.exe`
2. 点"下一步" → 默认装到 `%LOCALAPPDATA%\QSForge\`（不需要管理员权限）
3. 开始菜单或桌面找 QSForge 快捷方式

### B. 绿色版（免安装）

1. 把 `QSForge.zip` 解压到任何位置（建议 `C:\QSForge\`）
2. 双击 `QSForge.exe`
3. 首次启动 Windows 可能弹"无法验证发布者"——点 **"更多信息" → "仍要运行"**（只会弹一次）

### 系统要求

- Windows 10 或 11（64 位）
- Microsoft Edge WebView2 Runtime（Win10/11 默认已装）
- 700 MB 硬盘空间

---

## 使用（三步）

1. **启动 QSForge**
2. **把 `.rvt` 文件拖进窗口**（或点窗口挑选）
3. 等 1 到 2 分钟，看结果

结果页顶部一定会显示：
- 一个 **0–100 的总分**
- 一个 **判定**：Ready for QS / Conditionally Ready / High Risk / Do Not Use
- 预估 **额外 QS 工时**（例如 "+80 hours extra QS effort"）

下面是 **QS View** 和 **BIM View** 两个页签：

| 页签 | 做什么用 |
|---|---|
| **QS View** | 看 5 大维度分数条、读一段描述性解读、看 Top 3 最严重问题 |
| **BIM View** | 看 9 项详细检查、每项的 Element ID 列表、一键复制 ID 到剪贴板 |

---

## 9 项检查在查什么

| # | 检查项 | 问题 | 对 QS 意味着 |
|---|---|---|---|
| 1 | Volume Coverage     | 墙/楼板/梁柱 没体积 | 没体积 = 算不出混凝土量 |
| 2 | Level Assignment    | 没关联楼层          | 算不出楼层分量 |
| 3 | Mass Elements       | 概念设计体块还没删  | 看起来是实体，其实没量 |
| 4 | Generic Models      | 通用模型（未分类）  | 无法归入任何 BOQ 项 |
| 5 | Multi-storey        | 跨多层的单根柱/墙   | 楼层分量失真 |
| 6 | Unhosted Doors/Win  | 门窗没挂墙          | 门窗计数对但扣减失真 |
| 7 | Nested Sub-comp     | 嵌套子构件          | 父子同时计数会重复 |
| 8 | Material by Type    | 没赋材质            | 算不出具体强度等级 |
| 9 | Layer Materials     | 组合层没赋材质      | 无法分层（砌块/抹灰/涂料）计量 |

每项检查会给出 **CRITICAL（红色）/ WARNING（黄色）/ OK（绿色）** 三种严重度。

---

## 对接 BIM 团队

标准流程：

1. 在 BIM View 里找到任何非绿色的检查
2. 点 **"Copy IDs"** → 所有受影响的 Element ID 自动复制到剪贴板
3. 直接粘到邮件里，加一句"请检查：xxx"
4. 或点 **"Export PDF"**，PDF 里已经整理好每一项的 Element ID 列表，发给 BIM 即可

BIM 同事收到 ID 后在 Revit 里 **"管理 → 查询 → 按 ID 选择"**（快捷键 `AD`），粘贴后 Revit 会自动高亮所有问题元素，非常直观。

---

## 判定标准速查

| 分数 | 判定 | 该怎么做 |
|---|---|---|
| 85–100 | **Ready for QS** | 可直接用，正常做 QTO |
| 65–84  | **Conditionally Ready** | 可用，但要手动补漏，记得把 Top Blockers 发给 BIM |
| 40–64  | **High Risk** | 先退回 BIM 修改，硬做会多烧很多工时 |
| 0–39   | **Do Not Use** | 坚决退回，这样的模型出 BOQ 过不了审 |

---

## 常见问题

**Q: 启动窗口一闪而过**
A: 看 `QSForge.exe` 同目录下的 `qsforge_crash.log`，把最后 20 行发给 IT/开发者排查。

**Q: 转换一直卡在 "Launching DDC"**
A: 正常。200 MB 以上大模型要 2 分钟左右。打开任务管理器能看到 `RvtExporter.exe` 在吃 CPU，说明在工作。超过 3 分钟才算异常。

**Q: DDC 报错**
A: 看同目录（或桌面、或 `%LOCALAPPDATA%\QSForge\logs\`）下的 `qsforge_rvtexporter_last.txt`，里面有 DDC 的原始错误信息。最常见是：工作共享中心文件没 detach（需要先在 Revit 里"另存为 → 分离中心文件"）。

**Q: 提示 `RvtExporter.exe` 找不到**
A: 正常安装不会出现这个错误。如果出现了，几乎都是杀毒软件误杀了 `vendor\ddc\` 文件夹里的 DLL。把 QSForge 安装目录加入杀软白名单后重装即可。

**Q: 我的模型明明没问题，怎么分这么低？**
A: 看 Top Blockers 面板里前 3 条，重点看 CRITICAL 那几项。如果是 Volume Coverage 或 Level Assignment 大面积缺失，通常就是这两项拖分。点维度条会展开子项让你看到具体的扣分构成。

**Q: 数据会上传吗？**
A: 不会。完全本地运行，断网也能用。QSForge 只创建 4 个本地文件：`last_result.json`（上次分析结果）、`qsforge_crash.log`（日志）、`.webview-data\`（浏览器缓存，每次启动清空）、以及失败时 DDC 的错误 dump。

**Q: 每次分析完浏览器自动弹出 DDC 官网广告**
A: 这是 DDC 免费版（Community Edition）的强制行为——它会 `ShellExecute` 让默认浏览器打开 `datadrivenconstruction.io`。QSForge 已经内置了广告窗口拦截器（运行时会自动关掉新开的 DDC 广告窗口）。
如果你的浏览器本来就开着，DDC 会把广告塞进**已有浏览器的新标签页**，这种情况拦截器无法干净关闭（避免抢你正在用的窗口焦点）。**永久根治方法**：双击安装目录里的 `block_ddc_ads.bat`（开始菜单里也有快捷方式 "Block DDC promo pages (admin)"），选 1 → 弹 UAC → 确认。它会在 Windows 的 hosts 文件里把 `datadrivenconstruction.io` 指向 `0.0.0.0`，从此所有浏览器都连不上这个域名，广告内容自然加载不出来。只需配一次，永久生效；想撤销再跑一次选 2 即可。QSForge 本身不联网，完全不受影响。

---

## 反馈

使用中发现问题、想加检查项或调评分规则，直接找内部 QSForge 维护人。建议反馈时附上：

- `qsforge_crash.log`（如果闪退）
- `last_result.json`（如果评分异常）
- `qsforge_rvtexporter_last.txt`（如果 DDC 转换失败）
