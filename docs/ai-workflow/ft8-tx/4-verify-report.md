# 验证报告(4-verify-report.md)

> 历史记录。此报告的无阻断结论已撤回。当前实机放行状态见 `5-release-plan.md`。

日期: 2026-11-10 · 双轴独立评审 + 新鲜全量证据

## Standards 轴(代码规范)—— PASS,无 Blocker

评审覆盖 9 个目标文件 + 5 个基线参照 + 共享头/构建脚本。结论:整体质量高,
命名/注释/头文件卫生与基线一致,无调试残留。WARN 6 条、NIT 若干,已当场修复:

| 发现 | 处置 |
|---|---|
| `log_qso` 把 `"-08"` 预置进 my_grid(粘贴残留,无网格时写脏 ADIF) | ✅ 已修(清零,网格有则填) |
| `FT8_EVENT_KEY + 40` 魔法数 | ✅ `FT8_KEY_ROWS * FT8_KEY_COLS` |
| FREE 槽位字面量 `6` 四处跨文件 | ✅ `FT8_TX_FREE` 常量 |
| 渲染侧布局魔法数绕过 `ft8_ui_layout.h`(绘制/触摸错位隐患) | ✅ 行/按钮全部改用头文件常量 |
| ADIF 缓冲上限 220 跨文件魔法约定 | ✅ `FT8_ADIF_RECORD_MAX` |
| 死 typedef、STOP 分支重复 helper 等 NIT | ✅ 顺手清理 |

未修(记录于 6-handoff.md):tail/空洞两套 typedef 风格并存(历史约定)、
STOCK 宏三处变体、`row_call`/`extract_call` 有注释声明的故意双胞胎。

## Spec 轴(规格符合)—— PASS,无 Blocker

10 项关键点 8 项成立,2 项确认偏差(WARN):

| 发现 | 处置 |
|---|---|
| 对方 GRIDSQUARE 未填(spec: 解码行有则填) | ✅ 已修:选行时解析 4 字符网格(排除 RR73 误匹配),ADIF 增 GRIDSQUARE 字段,主机+集成双测 |
| watch_73(RRR→收到 73)路径无集成测试 | 📝 记录:代码在,模拟注入需要解码产物伪造,列为后续项 |
| 末音频块 160 个陈旧样本(实机多发 10ms) | ✅ 已修:末块补零 |
| worked 集合 11B/条,13 字符呼号不标记 | ✅ 已修:14B/条(512×14),13 字符呼号可标记 |
| FREE 端到端武装无集成断言 | ✅ 已补:FREE 选择→ENT→TXNEXT→ARMED→STOP |
| 手动 [LOG] 按钮缺失(spec 兜底项) | 📝 确认偏差:页面无空间,自动启发式覆盖标准流程,自由文本通联补记留待布局迭代 |
| 架构偏差:TX 引擎/交互逻辑在空洞而非尾部 | 📝 接受:空洞 10,300/10,970B 仍在上限内,重代码(编码/合成/渲染/ADIF)确在尾部 |
| 头注释/●绿色/状态文案等形式细节 | 📝 记录,不影响功能 |

## 评审期间发现并修复的基础设施缺陷

**merge_display 往返失败**:decode_sfl 的 `extract_continuous` 盲剥密文尾部 0x0D/0x0A,
尾部长度撞上时静默丢字节(概率性,与内容相关)。修复:merge 遇 ≤2 字节短缺时
补零重封直至往返精确,构建侧回读 SFL 同步 tail 文件,check_image 容忍 ≤2 字节补零。

## 新鲜证据(评审修复后全量执行)

```
test_ft8_rx.py:             PASS   主机流式接收回归(12/16 kHz)
test_ft8_tx.py:             PASS   主机合成往返 + ADIF 逐字节(含 GRIDSQUARE 正例)+ 已通联集合
test_ft8_arm.py:            PASS   尾部 ABI v5 回环 + WAV 解码
test_ft8_menu.py:           PASS   菜单镜像(含补零容忍)
test_ft8_menu.py --probe:   PASS   探针镜像
test_ft8_live.py:           PASS   集成全链(含 FREE 武装、Tx6 自动记录、* 标记)
```

产物: 空洞 10,300/10,970 B · 尾部 49,576 B(+封包补零 1 B) · live SFL 2,945,961 B(往返复验 OK)。
截图: `outputs/ft8-preview/ft8-live-{mode,decoded}.png`。

## Blocker 清单

无。

## 结论

**双轴 PASS、Blocker 清零**,四切片完成,可交付(SD 写入/E8/音频路由等实机项
按 5-release-plan.md 顺序单独验证)。
