# 切片计划(3-plan.md)

依据 2-spec.md。垂直切片,每片穿过 构建→模拟器验证→产物,片尾全量测试绿。
注: 工作区非 git 仓库,无逐片 commit;以"片尾新鲜测试输出 + build 产物"为完成证据。
ABI 演进: 尾部 ft8_arm_api v2→v3(尾部追加指针,文件名不变), live ABI v3→v4。

## 切片 1 — 尾部 TX 核心: 编码 + 流式合成(预重构并含)

改 `build_ft8_rx.py`(加源+生成脉冲表)、新增 `payload/ft8_tx.c`(LUT 正弦、
`encode/tx_begin/tx_next`、合成状态)、构建期生成 `payload/ft8_pulse.h`(3×2560 float,
Python math.erf)。主机回环 + Unicorn 尾部回环双测试。

- 新增 `test_ft8_tx.py`: GCC 主机编译 ft8_tx.c+ft8_lib 编码链+monitor 解码,
  三类消息(CQ/标准报告/自由文本)往返一致。
- 扩展 `test_ft8_arm.py`: emu 内 encode→分块 tx_next→拼 202,240 采样→回灌 emu 解码器。

**完成判据**: `python patch/test_ft8_tx.py` 与 `python patch/test_ft8_arm.py` 均 PASS,
ft8_rx.bin(含 TX 核心)链接地址/大小在尾部余量内。

## 切片 2 — TX 引擎 + 模拟器集成

尾部 TX 状态机 `tx_arm/tx_tick`(ARMED→E8(1)→首块 0.3s 静音引Lead→2ch 块提交 0x6b5f0
→202,240 采样→E8(0)→record_tx),`set_calls/std_message`;live ABI v4;workspace 扩展。
Panel 桩: 0x6b5f0 捕获块(合计采样、双声道复制、留 mono 拼回环)、E8 帧走既有 0x14a1c 捕获。

**完成判据**: `python patch/test_ft8_live.py` 扩展 PASS——武装→驱动时隙→E8 开/关帧字节
精确、总采样数正确、捕获 mono 回灌解码解出原文、TX 历史行出现。

## 切片 3 — UI 重构: WSJT-X 布局 + NEXT TX + 键盘

尾部 `ui_draw/ui_hit`(新布局、RX FREQ 面板、NEXT TX 窗口、Tx1-6+FREE 选中、置灰)、
迷你键盘(A-Z 0-9 SPACE BKSP ENTER, 覆盖左栏)、点行选 DX(呼号启发式+频率)、
LOC 秒时钟(0x135d4, emu 桩)。空洞仅加分发行。Panel/LivePanel 新点触目标与 RTC 桩。

**完成判据**: `python patch/test_ft8_live.py` UI 序列 PASS(选行→DX 填充→键盘输入→
置灰逻辑→TX NEXT→ARMED→发射→DONE);`--screenshots` 产出新布局 PNG;preview 交互窗口
人工核对一次。

## 切片 4 — QSO 日志(ADIF)+ 已通联标记

先 RE(限时): ①原厂文件 open/read/write/close 原语(线索 0x74ec 录音/0x6ea8 WAV/0x829c);
②RF 频率在 0x60935bb4 镜像的字段(0x20-0x33 应用函数 xref)。结论写入单点包装
`log_open/write/close` 与 `rf_frequency()`,RE 不决则用占位地址+`--freq` 默认并标注。
尾部 `adif.c`(记录生成/追加/解析 CALL 集合 512 上限)、自动记录启发式(发 73 完成或
发 RRR 后收到 73/RR73, 每 DX 每会话一次)、[LOG] 手动、● 标记与计数。
Panel 桩: 文件写捕获(ADIF 字节流)、文件读回放样本(3 呼号+畸形行)、RTC 固定时间。

**完成判据**: `python patch/test_ft8_tx.py`(含主机 ADIF 生成/解析单测)PASS;
`python patch/test_ft8_live.py` 日志流程 PASS(样本日志 3 呼号标记→RRR/73 自动记录
→ADIF 字段齐全闭合→标记更新);全量套件(test_ft8_rx/menu/arm/live)收尾全绿。

## 依赖与顺序

1→2→3→4 严格顺序(共享尾部 ABI 与 workspace);切片 4 的 RE 子项可在 2/3 期间穿插。
风险闸门: 任一片使空洞超过 10,976B 或尾ABI 兼容性破坏 → 回 Stage 2。
