# FTX-1F 原生 FT8 功能添加 — 研究与设计(定稿 v1)

> 目标:仿照原厂 APRS 的使用体验,在 FTX-1F 面板(DISPLAY 固件)内实现 FT8 自动解码与时隙化发射。
> 基线固件: 20260828 官方包(MAIN V01-13 / DISPLAY V01-10 / IFDSP V01-10),日版实机已刷扩频补丁并验证。
> 状态: 逆向调研完成(2026-11-10),所有关键链路已定位。尚未生成 FT8 补丁。
> 证据文件: [report-display-tx-uart.md](../work/an/report-display-tx-uart.md) · [report-ifdsp.md](../work/an/report-ifdsp.md)

## 1. 系统架构(全部逆向确证)

```
┌─────────────┐ SCIF5 @0xE8009800 ┌──────────────┐
│ MAIN        │ 345600bps 8N2     │ DISPLAY      │
│ RX651 (RXv2)│◄─────────────────►│ RZ/A1H A9@400│
│ AX.25/APRS  │ AA 00|u16len|cmd..|SUM           │
│ 信标/PTT/频率│ PTT=cmd 0xE8/E7   │ 运行基址     │
│ CAT/GPS NMEA│ 时钟=cmd 0x65 推送│ 0x60400000   │
│ 地区码EEPROM │                   │ µITRON 风格内核│
└──────┬──────┘                   └──────┬───────┘
       │命令                            RSPI 0x3fefa000
       ▼                                ▼ (Composite_SPI)
┌──────────────────────────────────────────┐
│ IFDSP = NXP MIMXRT685SFVKB (双核)         │
│  · Cortex-M33: Command/IPC 任务, CLI,     │
│    共享寄存器堆 0x20070000+2*reg          │
│  · HiFi4(Xtensa): Rx_Audio/Rx_C4FM/Tx_   │
│    C4FM/Composite_SPI/Rx_Path/Tx_Path    │
│ 模式: c4fm/gmsk/afsk/voice (寄存器脚本)   │
└──────────────────────────────────────────┘
```

### 分工结论
- **MAIN** 管理 APRS、DISPLAY 转发的 GPS 定位、发射频率检查（`0xFFEC7EDC`）和键控。原生接收可单独在 DISPLAY 实现。完整发射是否能保留原厂 MAIN，取决于能否找到可验证的独立键控与失联解键路径。E8(1) 打开 PCM 通路，原厂语音菜单另行申请键控。
- **IFDSP**:音频物理层。16kHz 音频由 HiFi4 产生,经 Composite_SPI 送面板(8000B/帧)。FT8 **无需改 IFDSP**。
- **DISPLAY**:FT8 的唯一改动目标。

## 2. FT8 数据面(全部挂钩点已定位,文件偏移,运行时 +0x60400000)

### 接收
| 环节 | 地址 | 说明 |
|---|---|---|
| 音频帧(常驻生产) | 队列对象 ctx+0x48, ID ctx+0x14 | ctx=RAM 0x607C0090(指针存 flash 0x8204);8000B=2ch×2000×16bit@16kHz,DMA |
| 收帧(poll) | `FUN_000088c8` | 公开 API:poll ctx+0x14 队列返回帧指针 |
| 收帧(过滤等待) | `FUN_0007b484` / 归还 `FUN_0007b8d4(1)` | 录放控制器同款 |
| cache 失效 | `FUN_00003000(ptr,8000)` | 读 DMA 帧前必调 |
| 状态避让 | ctx[+0x1c] | 2=录音中(让位),4=播放中,0=空闲 |
| 已知竞争者 | 0x45240 电平表组件 | ctx[+1] 表启用时也 poll——M1 需注意 |

### 发射(复用 voice-memory 通路,方案 A)
| 环节 | 地址 | 说明 |
|---|---|---|
| 播放音频路由 | `FUN_00014a1c(msg,9)` | `E8 01 00 00 00 <mode> 00 00 00`，mode 1 开启 PCM 播放状态，mode 0 关闭。原厂另由语音播放控制申请 PTT，DATA-U 原生键控待接入 |
| 音频流写 | `FUN_0006b5f0(handle, pcm, 0)` | handle 来自 `FUN_00006ea8`(WAV 打开,ctx+0x30);块 0xC80B=800样本×2ch |
| 播放启动(备选B) | `FUN_00007670(name,ch)` | 完整伪装 voice-memory 播放 `I:\FTX-1\MESSAGE\` |
| TX 波形规格 | — | 202,240 采样(0x31600)@16kHz 单声道，12.64s。6.25Hz 对应 2560 个采样。原厂每次 DMA 搬运 0x2260 字节，帧头标明有效 PCM 采样数 |

### 时钟
| 环节 | 地址 | 说明 |
|---|---|---|
| RTC 读 | `FUN_000135d4`(0xA6, 7B BCD)→`FUN_00013884` | 返回 {s,m,h,day,mon,year+2000};本地 RTC 芯片(RX-8025 风格) |
| GPS 校时 | MAIN→面板 cmd 0x65 | 推日期和时间(经 GPS TIME SET)，无亚秒 |
| GPS 定位 | 面板→MAIN cmd 0xE3 | DISPLAY 的 GPS 任务读取并解析 NMEA。FT8 在 DISPLAY 上观察已通过校验且状态为 `A` 的 RMC 定位 |
| 时隙同步 | RTC 秒 + 内核 tick 插值 | ±20ppm 晶体 → 15s 槽 0.3ms,足够;TX 起播延迟需实测校准 |

## 3. ft8_lib 资源基准(实测)
| 指标 | 值 | 说明 |
|---|---|---|
| PC 解码耗时 | **9.2 ms/15s段** | x86-64 -O2,稳定解出 4 条消息;A9@400MHz 保守估 0.3–1s(预算 15s,富余大) |
| 纯解码器体积 | **43 KB**(-O2 ARM)/**38.7 KB**(-Oz Thumb) | text+rodata+data;含 FFT/LDPC/文本解包;zig cc -mcpu=cortex_a9 |
| 运行时内存 | 堆 360KB + 输入缓冲 ≤960KB | 需在面板 SRAM 找 1.5MB 空闲(见 §4) |
| 发射合成 | <5 KB | LDPC 编码 + 8-FSK 连续相位合成,轻量 |

## 4. 注入布局(关键决策)
- 镜像内的连续 `0xFF` 也可能是有效数据。偏移 `0x12C66A–0x12F149` 是原厂 FUNC 菜单 110×50 背景的 5,488 个白色像素。Stage 1 复用其中的空间时，必须将原厂 `0x038868` 处的绘制调用重定向到等价的像素绘制。
- **策略:两级注入**——
  - **Stage 1（运行时 0x6052C670，窗口 10,970 B）**承载菜单、音频帧 tap 和收发状态机。TX 合成和 DMA 挂钩在 Stage 2。
  - **Stage 2(镜像尾 0x2C2FBC+, 运行时 0x606C2FBC)**:38.7KB 解码器 + 1.5MB 数据区(选面板 SRAM 低段空闲区,待实测 framebuffer 位置后定)。
- 打包器将 Stage 2 限制在原厂启动搬运终点 `0x606D0000` 以内。每次更改 Stage 1 应用原厂 FUNC 位图调用做逐像素回归。
- 挂钩点: `cmd_interval` 周期任务(0x156ac,天然 10ms 节拍)或键扫描 `key`(0x12d6c);`FUN_00027a8c` 入口跳转做开关。
- SFL 重封包: 头 CRC@0x220 = `crc32(载荷[0x240:]+8F93C635)` 手算(decode_sfl.py pack 对 DISPLAY 有 bug)。

## 5. 分阶段实施
1. **M1 旁观解码**:注入 Stage1+2,消费音频帧,log 解码文本(先验证 UART 打印或屏显)。验收:解码率、CPU 占用、与录音/电平表共存。
2. **M2 手动发射**:选呼号→合成波形→E8(1)→按块提交→E8(0)。验收:假负载+第二台收机测首符号时间/频偏/PTT 时序;实测 E8→射频起振延迟。
3. **M3 自动应答**:Enable TX 状态机(报告→RR73),时钟校准(CAT/GPS/手动),呼号哈希。
4. **M4 UI 原生化**:仿 APRS SCREEN 的列表/设置页。

## 6. 风险清单(按优先级)
1. **尾区加载机制未证实**(§4 前置验证)——决定 Stage 2 落点,首选验证项。
2. E8 mode 是否决定 DSP 音频路由到发射(方案 A 最大不确定点)——M2 首测;回退方案 B(WAV 伪装,链路全复用)。
3. 面板 SRAM 低段(0x60000000-0x603FFFFF)可能被 framebuffer 占用(stride 800 RGB595)——Stage 2 数据区选址前必须核实。
4. 电平表组件偷帧(ctx[+1])——M1 若解码率低先关表;根治=生产侧双投递(需进一步逆向 RSPI 任务 0x2bf830 `spi_slave_task`)。
5. RTC 秒粒度→TX 时隙对齐误差;需测 0x65 推送周期与 RTC 写回延迟。
6. 更新器对镜像长度变化的接受度(同风险 1)。
7. 回放队列采样率是否恰 16.000kHz(发射频轴缩放)——M2 用已知音校验。

## 7. 与 MAIN 扩频补丁的关系
RX4 只改 DISPLAY，已在用户设备上解码。完整发射是否需要修改 MAIN 取决于 DATA-U 独立键控和音频路由能否复用原厂协议。
