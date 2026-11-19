# FTX-1 实机 FT8 发射 —— 既有素材综合(context-summary)

> 由只读探索 agent 产出(2026-11-11),原文照录。

素材范围:work/an/ 全部相关文本、docs/ft8-design.md、docs/ai-workflow/ft8-tx/4~6、patch/README.md、patch/payload/(ft8_dma_tx、ft8_radio、ft8_main 等)、patch/test_ft8_radio_dma.py、patch/test_ft8_main_rx.py、原理图 PNG(视觉读图,分辨率受限处已标注)。置信度:高 / 中高 / 中 / 低。

## §1 IFDSP 接口结论

| 结论 | 证据 | 置信度 |
|---|---|---|
| IFDSP = NXP MIMXRT685SFVKB,单芯片双核 Cortex-M33(主控)+ HiFi4(Xtensa DSP);M33 应用文件 0x61800-0x836FC→RAM 0x80000,HiFi4 blob 文件 0x21E88-0x5C3D0→DSP RAM 0x200000 | report-ifdsp.md:11-15, 65-87 | 高 |
| **M33↔HiFi4 之间不走 SPI**:共享 RAM 命令队列 0x20020000(M33→DSP)/0x20030000(DSP→M33),各 0x8000 带非缓存别名;**DSP 寄存器堆 = 0x20070000+2*reg 的 u16 数组**(bank1 reg≥0x4000 落 0x20078000)。"模式切换是共享内存寄存器而非 SPI 命令" | report-ifdsp.md:20-23, 108-118, 187-195 | 高 |
| **面板(DISPLAY)↔IFDSP 链路**:物理帧收发在 HiFi4 侧 `Composite_SPI`/`Rx_Audio` 任务(Xtensa,入口 blob 文件 0x4F8EC / 0x45C7C,已定位但未反汇编);M33 完全不碰面板 SPI。面板侧为 RZ/A1H RSPI 0x3fefa000,音频帧 8000B = 2ch×2000 样本×16bit@16kHz | report-ifdsp.md:180-186;report-display-tx-uart.md:25, 194-195 | 高(入口定位)/中(帧重组细节) |
| 音频到达 IFDSP 的路径:RX 方向 16kHz 音频由 HiFi4(Rx_Path→Rx_Audio)产生,经 DSP 堆乒乓缓冲(0x23A548-0x280000,描述表 blob 文件 0x5BFD0)打包经面板 SPI 送出;TX 方向 PCM 从面板经同一 SPI 链路进入(DISPLAY 侧 CH3 DMA→RSPI,见 §5)。**帧头/命令字/校验只能靠反汇编 Composite_SPI 的 Xtensa 循环确认——这是 IFDSP 报告明确留下的唯一缺口** | report-ifdsp.md:197-219 | 中 |
| IFDSP 侧 TX 命令的**间接**证据:`Tx_C4FM`/`Tx_Path` 任务存在(名称指针位置精确、入口中置信,report-ifdsp.md:158-161);CLI 模式脚本 `c4fm/gmsk/afsk/voice` = 对 DSP 寄存器堆写一组寄存器(afsk: reg0x4006=1, reg6=0xF99, reg0x3D=0x14, reg0x19=0x1000, reg8=0x71, reg0x400E=3, reg0x400F=3),调制解调在 HiFi4 blob 内,M33 侧无 1200/2200 波特常量 | report-ifdsp.md:237-279 | 高(寄存器脚本)/低(寄存器语义) |
| M33 外设角色:0x40100000=I2C 主→音频 codec;0x40110000=USART,疑似与 MAIN 的 C4UART 链路(候选);0x40106000=CLI 调试串口 | report-ifdsp.md:221-233 | 中 |
| 对 FT8 的既定结论:"FT8 无需改 IFDSP"——复用原厂 voice PCM 通路 | docs/ft8-design.md:33 | 高(设计判断) |

## §2 APRS/E7 路径 vs voice/E8 路径

**两协议同型**,9 字节 `E7/E8 01 00 00 00 <MD> 00 00 00`(report-display-tx-uart.md:8-42;dec_ptt.txt,高置信)。

| 环节 | E7/APRS 信标 | E8/voice 存储 |
|---|---|---|
| DISPLAY 触发 | FUN_00027a30,0x60936522={1,0x7f};控制器 FUN_00041724/41ff8(QSOAPRSBCN) | FUN_00027a8c,0x60936522={1,0};MD 0/1/2 |
| 音频由谁合成 | **不是 DISPLAY**。MAIN 组 AX.25 帧(fff5d189:呼名 shll#1、SSID or#0xE0),信标调度器 fff5ca72/fff5c898 检查 TX 允许(ffec7edc)与 TX 原因(0x17b54)后,经 ffea517c 命令槽向 IFDSP 发 0x1b/0x4b;AFSK modem 在 HiFi4 | DISPLAY 读 WAV→FUN_0006b5f0→CH3 DMA→RSPI→IFDSP;MAIN 收 E8(1) 后开 PCM 通路并键控 |
| 键控归属 | MAIN(数据模式键控) | MAIN(E8 请求 + 播放路径另设键控原因,见 §4) |

**结论(高置信)**:E7 只能触发 IFDSP 内固定参数 AFSK modem,FT8 的任意 8-FSK 波形必须走 E8/PCM 路径。当前实现用自定义 E8 子命令 `E8 F8 'F' 'T' '8' start/stop token 0 0`(ft8_tx_link.h:4-19;ft8_radio.c:129-136)。

## §3 PA/TX 硬件线索

- PA 板只处理 RF 不处理音频(uv-pa-schematic.png,中置信):驱动 RD16HHF1、末级 RD16HUP2/RD15HUP2 梯、SWR/温度检测、BIAS 驱动、TX BPF(137-160M/420-450M)、HF LPF 1.8-54M。**PNG 分辨率读不出网络名,SEND/BIAS_ON/APC 标签未确证(低置信)**。
- **键控物理线在 MAIN**:RX651 端口 **0x8C02B bit3 = SEND_A**(ft8_main.c:24-25;test_ft8_main_rx.py 实证)。
- DISPLAY↔DSP 板互连:DSP_D0-D7 并行 + DSP_LRCK/XMCK/DMCK/LMCK/CLK 时钟组、DSPIF_CLK/DO/DI/SS(面板 SPI)。**并行口与 RSPI 分工未定**。
- 面板硬件 PTT 仅为按键,不直接键控射频(与"PTT=串口协议"一致)。

## §4 键控相关旧反汇编解读(勘误+新证)

- **勘误:xrefs_5788.txt 不是 0xFFF5788 的 xref**,而是 DISPLAY 音频 ctx(0x607C0078/0x607C0090)引用图。
- uv-tx-path.txt = 频率→频段查表族(ffec7a59-ffec7bdd);**ffec7edc(913 指令)= 发射频率/TX 允许检查**(高置信);ffec7c2b 按边界返回频段结构(+0xa3 带内允许位)。
- uv-tx-routing.txt:ffed0a70 片段 = TX 参数配置序列(ffea517c 连发 cmd 0x15、0x55(1)、0x56(5)、0x57(1)、0x58(3)、0x59(param))→ MAIN→IFDSP 命令槽(0x800AF0+4*cmd 值、0x8529[cmd] 完成位,中置信);ffeccb8b/ffecdf26 = APRS 100 频道槽配置;ffea87a0 = 键控前模式/频率合法性检查链。
- dec_txseq.txt(FUN_00027ae0,DISPLAY)= 原厂 TX 条件监视器:带内检查失败→E8(0)——绕开 FUN_00027a8c 直接发裸 E8 的原因(report-display-tx-uart.md:184)。

## §5 当前实现覆盖度(ft8_dma_tx.c / ft8_radio.c / ft8_main.c)

已覆盖(VM/模拟验证,test_ft8_radio_dma.py + test_ft8_main_rx.py PASS):
1. **帧格式完全复刻原厂**:0x2260B/帧,头=u16 有效采样数+u16 魔数 0x1234,交错立体声 PCM,尾零填充;整段 cache clean(ft8_dma_tx.h:11-23)。
2. **CH3 挂钩三处**(build_ft8_menu.py TX_HOOKS):0x452B4 替换源、0x63DB4 完成归还、0xC9D00 读 0x20 报文 FT8 状态扩展。
3. **README 42 行全部替换前置条件已实现**(ft8_radio.c:421-434):静音源 0x6095C500、租约、无停止、无在途、无录放(0x607c0091/92、0x607c07c2/7c3/7c4)、credit REG16(0x607c4012)>0xFF、CH3(0xE82000E4)空闲;归还匹配实际完成帧。
4. **租约状态机+看门狗独立解键**(ft8_radio.c:207-267):REQUEST→KEYING→ON→STOPPING;270ms 起键超时、150ms 心跳、租约硬上限、停发重试;只有看门狗任务碰 E8;前导 6 块静音。
5. **MAIN 侧适配器**(ft8_main.c):PCM_SLOT(0x21B20)=1→PCM_PLAY(0x21D82)=1→VOICE_ACTIVE(0x21D3D)=1→VOICE_PTT(0x8013C5)=1;校验 DATA-U(MD 表索引 9)、radio_idle、stock_tx_allowed;状态扩展写 0x20 报文偏移 9(TAG 0x80|心跳 0x20|token<<2|状态),toggle 位对抗抑制;非 FT8 的 E8 原样转发 stock_e8(0xFFED6966)。
6. 全链模拟:253 块 202,240 有效采样;取消保住在途缓冲。

尚未做(实机项):CH3 提交/完成/取消实机连接、TX 所有权/波段/欠载/卡死/串口异常强制解键的实际测量;台架镜像键控禁用(TX OFFLINE);旧 LAB 镜像未释放 PTT 风险(结论已撤回)。

## §6 实机 TX 缺口清单(节选,全文见对话记录)

1. MAIN 三个关键函数反编译体未导出(→ **已由 main-tx-chain.md 补齐**)。
2. E7 在 MAIN 的入口未定位(→ 已补:ffed6822,+0x22028 事件槽,与 E8 同型独立)。
3. IFDSP HiFi4 blob 零反汇编(Tx_Path/Composite_SPI)。
4. MAIN→IFDSP 命令链路字节协议未还原(0x800AF0 值槽+0x8529 完成位,cmd 0x15/0x1b/0x4b/0x53-0x5a/0x69/0x6a 已知)。
5. DSP_D0-D7 并行口与 RSPI 分工未定。
6. PA/RF 键控网络名未读出(需高分辨率原理图重渲染)。
7. credit 0x607c4012 的生产者/单位未确证,>0xFF 门槛实机待验。
8. CH3 静音源 0x6095C500 生命周期只有模拟证据。
9. 实机时序未测:E8→SEND_A 延迟、采样率恰 16.000kHz 验证。
10. ft8_main 无实机刷写与 DISPLAY 联调;双端刷写/恢复流程未定义。
11. TX DMA 内存与原厂任务共存未验证(README:69)。
12. 更新器对加长镜像/尾区加载接受度未验证。
13. UTC 时隙实机校准未做;GPS 未接入。
14. 0x20 报文偏移 9 取值范围未枚举(TAG 0x80 碰撞风险)。
15. stock_audio_busy 5 状态字节语义是地址级推断。
16. DISPLAY 侧 APRS E7(2)+时间戳文件含义未解。
