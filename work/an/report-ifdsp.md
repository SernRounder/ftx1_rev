# FTX-1 IFDSP 固件逆向报告 (FTX-1_IFDSP_V0110.SFL.bin)

分析对象: `work/dec/FTX-1_IFDSP_V0110.SFL.bin` (0x836FC 字节, 已解密)
方法: capstone THUMB|MCLASS 线性扫描+重同步, 字面池聚类, 服务手册原理图渲染 (pymupdf) 交叉验证。
除非注明, 所有"文件偏移"均指 bin 内偏移; flash 地址 = 文件偏移 + 0x08000000 (已证明, 见 §1)。

---

## 0. 一页结论 (TL;DR)

1. **芯片 = NXP MIMXRT685SFVKB** (原理图 MAIN-2 页 Q20002 丝印, 高置信): 单芯片双核
   **Cortex-M33 (主控) + Cadence HiFi4 (Xtensa DSP)**。因此本镜像里有两份程序:
   - M33 引导块: flash 0x08001000 (文件 0x1000-0x1900)
   - **M33 应用 (文件 0x61800-0x836FC)** → 复制到 RAM 0x00080000 运行 (RAM=文件+0x1E784)
   - **HiFi4 DSP 程序 blob (文件 0x21E88-0x5C3D0)** → 复制到 DSP RAM 0x00200000 (DSP地址=文件+0x1DE178)
2. **任务名 'C4Uart'...'Composite_SPI' 全部属于 HiFi4 侧 RTOS** (blob 内自有内核, 状态名
   idle/suspend/delay/exited/join)。M33 侧任务是 Command Task / IPC Task / Tmr Svc / IDLE。
   **Composite_SPI / Rx_Audio 的主循环是 Xtensa 代码**, capstone 无法反汇编 (给出了精确入口,
   可用 Xtensa/HiFi4 工具继续)。
3. M33↔HiFi4 通过共享 RAM: 命令队列 0x20020000 / 0x20030000 (各 0x8000, 带非缓存别名 +0x8000),
   **DSP 寄存器堆 = 0x20070000 + 2*reg 的 u16 数组** (0x10000 字节, 分两个 32KB bank,
   reg≥0x4000 落在 0x20078000 bank)。CLI 的 `w/r` 命令和 c4fm/gmsk/afsk/voice 模式脚本
   就是对这个寄存器堆的读写 → **模式切换是"共享内存寄存器"而非 SPI 命令**。
4. afsk 1200bd modem 不在 M33 侧; 'afsk' 只是把 reg6=0xF99、reg0x400E=3、reg0x400F=3 写进 DSP
   寄存器堆, 调制解调在 HiFi4 blob 的 Rx_C4FM/Tx_C4FM 任务里 (入口已定位)。

---

## 1. CPU 与基址 (问题 1)

### 1.1 文件布局 (高置信)

| 文件范围 | flash 地址 | 内容 |
|---|---|---|
| 0x0000-0x0400 | — | 全 0 |
| 0x0400-0x0600 | 0x08000400 | SFL 容器头, 魔数 "FCFB" |
| 0x1000-0x1900 | 0x08001000 | **M33 引导程序** (向量表+Reset) |
| 0x1900-0x21E88 | 0x08001900-0x08021E87 | 全 0 (真实 flash 内为 HiFi4 IRAM 库, 升级文件不含) |
| 0x21E88-0x5C3D0 | 0x08021E88 | **HiFi4 DSP 程序 (Xtensa blob), 0x3A548 字节** |
| 0x5C3D0-0x61810 | 0x0805C3D0 | 全 0 → 装载时清零共享队列区 |
| 0x61800-0x836FC | 0x08061800 | **M33 应用 (Thumb-2), 0x21EFC 字节** |

### 1.2 证据: flash 基址 = 0x08000000, 文件偏移 == flash 偏移 (高置信)

文件 0x1000 处为向量表, 文件 0x11A8 是标准 ARMv8-M Reset Handler:

```
0x080011a8: push {r3,r4,r5,lr}; cpsid i
0x080011ac: ldr r3, =0x08001000      ; 向量表地址
0x080011ae: ldr r2, =0x001F8000      ; MSPLIM (低 32KB 为栈限)
0x080011b0: ldr r0, =0xE000ED08      ; SCB->VTOR
0x080011b2: str r3,[r0]              ; VTOR = 0x08001000  ← 文件 0x1000
0x080011b6: msr msp, r1              ; MSP = [0x08001000] = 0x00200000
0x080011ba: msr msplim, r2           ; ← MSPLIM ⇒ ARMv8-M (Cortex-M33/M55)
0x080011be: bl 0x08001540            ; SystemInit (时钟: 16MHz/24MHz 常量)
... scatter 拷贝循环 (12 字节表项) → bl 0x08001222 (word copy) → bl main(0x080016c8 → veneer)
```

- 向量表@文件 0x1000: SP=0x00200000, Reset=0x080011A9, 其余向量指向 0x0800120C-0x08001220 的
  `b .` 死循环 (标准默认处理器) — 完全自洽。
- 文件 0x1220-0x122E 为 copy/zero 例程; 0x1240-0x140E 为 IRQ trampoline 表。
- 0x080016C8 起是一串 `ldr r12,=0x00083xxx~0x0009Cxxx; bx r12` veneer → 跳进 RAM 0x80000-0x107A00
  (即 M33 应用的 RAM 镜像), 证明引导块与 RAM 应用的衔接。

### 1.3 M33 应用的 RAM 基址 = 0x00080000 (文件+0x1E784) (高置信)

引导块 scatter 表 (文件 0x1130, 12 字节项 {src, dst, len_words}):
```
{src=0x0806187C, dst=0x00080000, len=0x21E80 words}   → 0x87A00 字节, 覆盖文件 0x6187C..0x836FC(全文件)
随后 8 字节 {addr,len} 零填表: {0x000A1E80, 0x0001D138}  (清 .bss)
```
验证: 'Command Task' 字符串 (文件 0x833D0) 指针 = 0x833D0+0x1E784 = **0xA1B54**, 该字确实出现在文件 0x62810。✓

### 1.4 HiFi4 blob 的加载地址 = 0x00200000 (文件+0x1DE178) (高置信)

M33 应用内 DSP 启动函数 (文件 0x65E18) 构造三段加载描述符后 `bl 0x65EBC`:
```
段1: {src=0x08001844, dst=0x24000000, len=0x20644}   ; HiFi4 IRAM/启动库 (本文件中该区为 0)
段2: {src=0x08021E88, dst=0x00200000,  len=0x3A548}   ; DSP 主程序 blob → 0x200000..0x23A548
段3: {src=0x0805C3D0, dst=0x20040000,  len=0x54A0}    ; 共享队列区清零 (全 0 数据)
```
随后 0x65500: 配 HiFi4 时钟 ([0x40021000+0x200/0x204/0x20C], 0x40002000+0x620=0x180000),
`str 0,[0x40002000+0xC]` 释放 DSP 复位。
验证: blob 内指针族 0x20xxxx-0x23Axxx 与该映射吻合; blob 文件 0x28E20 表内
0x2388A4/0x23A800 → blob 内偏移 0x5A72C/0x5C978 ✓。任务名指针: 'C4Uart'(文件 0x28D10) → DSP 0x206E88,
该值确实出现在 blob 文件 0x2A848。✓

### 1.5 芯片识别 (高置信: 原理图丝印)

- 服务手册 MAIN-2 (SDR-DSP 电路图) 大芯片丝印 **Q20002 = MIMXRT685SFVKB**。
- 与固件全部吻合: RT685 = CM33+HiFi4; FlexSPI flash XIP @ **0x08000000**; 大 SRAM@0;
  DSP 专用窗口 0x24000000 (HiFi4 IRAM)。
- blob 为 Xtensa 的独立证据: 每个任务入口处以 `36 61 xx` 开头 — Xtensa `entry` 指令 (操作码 0x36);
  Thumb 解码密度测试显示该区 push/pop/BL 近乎为零 (109k"指令"无有效函数序言)。
- 原理图网络名 (OCR): DSPIF_CLK/DSPIF_DO/DSPIF_DI/DSPIF_SS、DSP_I2C_SCL/SDA、ATC_MOSI/SCLK/MISO/SS、
  QSPI_LSBx — 与固件中 FLEXCOMM 0x401xxxxx 外设族对应。

### 1.6 存储映射总图 (观测值)

```
0x00000000-0x001FFFFF  M33 RAM (2MB, SP 顶=0x200000)
  0x00080000-0x00107A00  M33 应用镜像 (=文件 0x6187C-0x836FC)
  0x000A1E80+0x1D138      应用 .bss
  0x000A4F48 / 0x000A5354 / 0x000A4730  应用内环形缓冲控制块 (+0x400 计数/+0x408 头/+0x404 尾)
0x00200000-0x00280000+ DSP 共享 RAM
  0x00200000-0x0023A548  HiFi4 blob (=文件 0x21E88-0x5C3D0)
  0x0023A548-0x00280000  DSP 堆/缓冲 (运行期)
0x02400000-0x0260644     HiFi4 IRAM (段1)
0x20020000-0x20028000    M33→DSP 命令队列 (+0x8000 非缓存别名 0x20028000)
0x20030000-0x20038000    DSP→M33 队列 (+别名 0x20038000)
0x20040000-0x200454A0    共享队列区 (段3 清零)
0x20070000-0x20080000    DSP 寄存器堆 u16[0x8000]: 0x20070000+2*reg (bank0 reg 0..0x3FFF,
                          bank1 0x20078000 reg 0x4000..0x7FFF)
外设: 0x40001000 CLKCTL(时钟门控 +0x218), 0x40002000 复位/DSP 控制(+0xC 释放 DSP),
      0x40004000 (+0x54/0x58=0x40 时钟分频), 0x40021000/0x40022000/0x40026000,
      FLEXCOMM 族: 0x40100000, 0x40106000, 0x40110000, 0x40112000, 0x40124000, 0x40125000,
      0x40134000, 0x40135000 (身份推断见 §3, 中置信)
```

> 注: 早期对文件 0x28D10 字符串做指针聚类得到的 "0x1E3290 基址" 是**伪影** — 由 blob 中高频
> 字节模式 `c0 20 00`(2426 次) 造成, 已废弃。正确映射是上面的两段式 (+0x1E784 / +0x1DE178)。

---

## 2. 任务表 (问题 2)

### 2.1 M33 侧 (region2, 全部高置信)

线程创建原语: 文件 0x63A3C, 签名 `create(entry, name, stack_size, arg, prio)` (prio 经栈传递)。

| 任务 | 名字串 | 入口 (RAM/文件) | 栈 | 优先级 | 创建点(文件) |
|---|---|---|---|---|---|
| IDLE | "IDLE"@flash 0x08001834* | 0x82118 / 0x63994 | 0x80 | 0 | 0x63C6E |
| Command Task | 0xA1B54 | **0x80E70 / 0x626EC** | 0x1800 | 1 | 0x627EA |
| IPC Task | 0xA1B61 | **0x8116C / 0x629E8** | 0x1800 | 1 | 0x62ABA |
| Tmr Svc | "Tmr Svc"@0xA1C9D | 0x82C60 / 0x644DC | 0x100 | 2 | 0x643D0 |

\* 名字串位于引导 flash 区, 同处还有字符串 "Cortex-M33"。
创建示例 (文件 0x627D0-0x627EE):
```
0x627e2: mov.w r2,#0x1800          ; 栈大小
0x627e6: ldr r1,=0xA1B54           ; "Command Task"
0x627e8: ldr r0,=0x80E71           ; 入口 (thumb)
0x627ea: bl 0x63A3C                ; create(entry,name,stack,arg,prio=1)
```

### 2.2 HiFi4 侧 (blob; 高置信 = 名称指针/描述符位置, 入口为中置信 — Xtensa 指针约定未最终验证)

blob 内每个任务的创建描述符形如 `{entry_ptr, name_ptr, tcb/bss_ptr...}` (名称指针位置精确):
描述符中的 entry 指向 blob 内 Xtensa `entry` 序言 (0x36 0x61) 附近 (个别差 2 字节对齐)。

| 任务 | 名称指针位置(文件/DSP) | 入口 DSP = 文件 | 描述符上下文(文件) |
|---|---|---|---|
| Thread_Ipc | 0x295F4 / 0x20776C | 0x21CC5C = 0x3EAE4 | 0x295D4-0x29608 (含 0x20020000 队列基址!) |
| Thread_Main | 0x29660 / 0x2077D8 | 0x21CEE0 = 0x3ED68 | 0x29640-0x29674 (含 0x40100004/15/16 — DSP 写 I2C 编解码器) |
| Rx_Audio | 0x29BC4 / 0x207D3C | **0x223DF4 = 0x45C7C** | 0x29BA4-0x29BD8 |
| Rx_C4FM | 0x29BD8 / 0x207D50 | 0x223E84 = 0x45D0C | 0x29BB8-0x29BEC |
| Tx_C4FM | 0x29EC0 / 0x208038 | 0x2276C4 = 0x4954C | 0x29EA0-0x29ED4 |
| **Composite_SPI** | 0x2A2BC / 0x208434 | **0x22DA64 = 0x4F8EC** | 0x2A29C-0x2A2D0 |
| Rx_Path | 0x2A420 / 0x208598 | 0x22F46C = 0x512F4 | 0x2A400-0x2A434 (含 0x40105284/0x401052B4 — DSP 直接访问的外设寄存器!) |
| Tx_Path | 0x2A438 / 0x2085B0 | 0x22F61C = 0x514A4 | 0x2A418-0x2A44C (含 0x20064CA0/0x20064EA0 大缓冲指针) |
| C4Uart | 0x2A848 / 0x2089C0 | (描述符另置, 0x239CF0 附近) | 0x2A830-0x2A858 |
| (内核 idle) | 0x2A5A0 / — | — | 状态名表 @0x28804: {idle,suspend,exited,join,delay} |

blob 尾部缓冲描述表: 文件 0x5BFD0 起 8 组 (指针对, 步长 8): 0x23A140/48/50/58/60/68/70/78 —
DSP 堆内乒乓缓冲描述符 (音频块候选, 见 §3.3)。
另: blob 文件 0x29A88 处有 u32 常量 **4000** (= 2ch×2000 样本, 位于 Thread_Ipc 与 Rx_Audio
描述符之间) — 与面板侧 8000 字节/帧 (=4000 样本×16bit) 吻合 (中置信线索)。

### 2.3 建议下一步

用 Xtensa/HiFi4 工具反汇编 blob: `xt-objdump -D --config=hifi4` (Cadence Xplorer, NXP 提供
RT685 的 HiFi4 配置) 或 Ghidra Xtensa 模块。装载基址 0x200000 (DSP 视图可能为 0x200000 或其本地
窗口, 以 IRAM@0x24000000 的映射为准)。

---

## 3. Rx_Audio / Composite_SPI 与 SPI 链路 (问题 3)

### 3.1 谁拥有面板 SPI

- 'Composite_SPI' 与 'Rx_Audio' 是 **HiFi4 任务** → **面板 SPI (DSP_SCLK/SS/MOSI/MISO) 的
  物理帧收发在 Xtensa 代码里** (入口: Composite_SPI @blob 文件 0x4F8EC / DSP 0x22DA64)。
  本轮 capstone 无法反汇编其循环, 以下给出已证实的周边事实与静态线索。
- M33 侧完全不碰面板 SPI; M33 的 IPC Task 管理的是与 HiFi4 的共享内存队列 + 与外部的 USART。

### 3.2 M33 ↔ HiFi4 IPC (高置信, 文件 0x629E8-0x62C68)

IPC Task 主循环:
- 初始化 FLEXCOMM 0x40110000 (+0x64 ← 0xC8000000|旧值; +0x60 状态), NVIC;
- 在共享 SRAM 建立两个 0x8000 队列: **0x20020000** (别名 0x20028000) 与 **0x20030000**
  (别名 0x20038000), 每个头部 8 字节描述 + 4 字节指针域, [0x20020000] 为有效标志字节;
  0x7E070(FC, 0x80000) 配置传输长度 0x80000。
- 事件等待 (0x7D984, 超时 -1) → 处理 [0xA4F48+0x400/0x408] 本地环形计数 (互斥锁 0x63880/0x6389C)。
- blob 侧 Thread_Ipc 描述符同样引用 0x20020000 与 0xC8000000/0xFFF00190 → 两侧协议一致。

### 3.3 音频通路与 8000 字节帧的定位 (中置信推断 + 高置信地址)

- 静态证据 1: M33 启动时 (文件 0x625F4) memset 0x20070000-0x20080000, 写
  `*(u16*)0x20070000 = 0x110`、`*(u16*)0x20078000 = 1` → 该 64KB 区被两核当作
  **u16 寄存器堆/状态区** 使用 (CLI 的 w/r 即写读这里, 见 §4)。
- 静态证据 2: blob 尾 0x5BFD0 描述表 (0x23A140.., 8×2 指针) 与 Tx_Path 的大缓冲指针
  (0x20064CA0/0x20064EA0) → 音频采样缓冲在 DSP 堆 0x23A548-0x280000 一带。
- 静态证据 3: blob 0x29A88 常量 4000。
- **结论 (中置信)**: 16kHz 音频由 HiFi4 (Rx_Path→Rx_Audio) 产生, 经 DSP RAM 缓冲,
  由 Composite_SPI 任务打包经面板 SPI 送出。8000 字节帧是 **SPI 载荷以上的重组结果** 的可能性大
  (共享缓冲最小颗粒是 0x8000=32KB 双 bank, 8000 字节帧应是 SPI 侧分包), 但**分帧/命令字/校验
  只能靠反汇编 0x4F8EC 起的 Xtensa 循环确认** — 这是下一步唯一缺口。

### 3.4 SPI 帧格式字节图 (待 Xtensa 确认, 当前仅能给约束)

```
???  [模式/命令字?]  [长度?]  [payload: 2ch×2000×16bit interleaved?]  [校验?]
观察约束:
- 面板侧已知: 每帧 8000B, 16kHz, 2ch×2000 样本 (来自面板固件, 本报告外部事实)
- M33 侧无 SPI-to-panel 痕迹 → 帧头/命令定义全在 blob
- 非音频控制通道 = 共享寄存器堆 (0x20070000) + 队列 (0x20020000/30000), 不走面板 SPI
  (面板收到的模式切换等控制如何到达: 面板→Composite_SPI→共享队列→M33/DSP, 中置信)
```

### 3.5 M33 侧外设角色 (中置信, 按寄存器行为推断)

| 基址 | 行为证据 | 推断 |
|---|---|---|
| 0x40100000 | 0x65890(base,page,reg,buf) 页/寄存器写; blob 也写 0x40100004/15/16 | I2C 主 → 音频 codec |
| 0x40106000 | +0xE10 水印=10, 字节环形队列 0xA4730, "Command Task" 独占 | **CLI 调试串口** |
| 0x40110000 | +0x20 字节 TX (FIFO), 环形 0xA5354, 与 0x20020000/30000 队列联动 | USART (与主机的 C4UART 链路候选) |
| 0x40112000 | 0x65C44 init + 0x7E0C0(FC,0x40) | USART 2 |
| 0x40124000/0x40125000 | 仅 IRQ 派发桩 (查表 0xA5A40/0xA5A68/0x9E824) | FLEXCOMM (角色未定) |
| 0x40134000 | +0xE0 轮询位, +0 FIFO | I2S 数据口候选 |
| 0x40135000 | +0x20←0x04040808, +0x14←0xA | I2S/时钟配置候选 |

blob 侧 Rx_Path 描述符引用 0x40105284/0x401052B4 — HiFi4 直接访问的外设寄存器 (窗口归属待查)。

---

## 4. afsk 模式与 CLI (问题 4) — 全部高置信

### 4.1 CLI 框架 (M33, USART 0x40106000)

- Command Task 主循环: 文件 0x626EC — 使能 0x40106000+0xE10 水印, NVIC, 循环
  `wait_event(1000ms) → ring_pop([0xA4730]) → 解析器 0x631F4`。
- 解析器/分派器: 文件 0x631F4 (`sub r3,r0,#0x20; cmp #0x5E` 字符分类 → 分词)。
- 提示符 ">> "、帮助 "\r\n?\r\n>> "、Ctrl+C 处理均在 0x62F6C-0x63600 一带。
- 命令: `w <reg> <val>` (0x63000-0x63030 → bl 0x62638)、`r <reg>` (0x63178-0x6319C, 打印
  "\r\nr %04X %04X")、`db00/db01` (寄存器 dump, 0x6303C-0x630xx/0x630D8)、`test`、以及
  无名模式命令 (即 c4fm/gmsk/afsk/voice)。

### 4.2 w/r 原语 = DSP 共享寄存器堆 (关键)

```
文件 0x62638  w(reg,val): addr = 0x20070000 + reg*2; if addr<=0x2007FFFF: *(u16*)addr = val
文件 0x6261C  r(reg):     return *(u16*)(0x20070000 + reg*2)  (同界检查)
```
即 CLI 的 'w 4006 1' = *(u16*)0x2007800C = 1。reg 0x4006..0x400F 属于 0x20078000 bank。

### 4.3 模式调度器 (文件 0x62D54) 与各模式寄存器脚本

```
"c4fm"      (argc==2): w(0x4006,1) w(6,0x1AAA) w(8,0x71) w(0x400E,0) w(0x400F,1)
"gmsk"                : w(0x4006,1) w(6,0x0E99) w(0x3D,0x14) w(0x19,0x1000) w(8,0x71)
                        w(0x400E,5) w(0x400F,argc)
"afsk"                : w(0x4006,1) w(6,0x0F99) w(0x3D,0x14) w(0x19,0x1000) w(8,0x71)
                        w(0x400E,3) w(0x400F,3)
"c4fm voice" (argc==3): w(0x4006,1) w(6,0x1AAA) w(8,0x31) w(0x400E,0) w(0x400F,0)
```
每步随后把命令文本 ("\r\nw 4006 1" 等) puts 到 CLI (回显)。寄存器语义推断 (低置信):
- reg 0x4006: 模式块使能; reg 0x400E: 模式选择 (0=voice/c4fm, 3=afsk, 5=gmsk);
  reg 0x400F: 子模式/源选择; reg 6: 音调/NCO 分频 (0x1AAA=语音带宽, 0xE99/0xF99=gmsk/afsk 频偏);
  reg 8: 增益/滤波 (0x71/0x31); reg 0x3D=0x14、reg 0x19=0x1000: afsk/gmsk 专用 (波特/定时)。

### 4.4 AFSK modem 位置

- **不在 M33**: region2 内无 1200/2200/ bäud 常量与调制循环; 'afsk' 只是上述寄存器脚本。
- **在 HiFi4 blob**: 模式寄存器被 Rx_C4FM/Tx_C4FM/Rx_Path 任务消费 (入口: Rx_C4FM 0x223E84/
  文件 0x45D0C, Tx_C4FM 0x2276C4/0x4954C)。APRS 1200bd AFSK 的调制解调函数应在这两个任务及其
  调用子图内, 需 Xtensa 反汇编定位 (下一步)。
- blob 文件 0x5B520-0x5B560 (Composite_SPI 描述符附近) 有浮点表 (0x3F7C508B≈0.987,
  0x3F79C6E7 等) 与 0x258/0x23B/0x22D... 递减序列 — 滤波器/窗系数候选。

---

## 5. 下一步建议 (面向"面板端解耦 16kHz 音频做 FT8")

1. **Xtensa(HiFi4) 反汇编 blob** (最高优先): 装载基址 0x200000, 文件映射 +0x1DE178。
   目标: Composite_SPI 主循环 (0x4F8EC 起) 提取 SPI 帧头/长度/校验字段; Rx_Audio (0x45C7C)
   确认采样块布局与 16kHz 时基来源。
2. 若不想碰 Xtensa: 从面板侧 (RZ/A1H, RSPI@0x3FEFA000) 已知每帧 8000B — 可先在面板固件侧
   验证帧内是否有命令字前导 (对比 SPI 首字节序列与 0x20070000 寄存器堆变化的对应关系)。
3. 半静态捷径: 通电后 dump 0x20020000/0x20030000 队列内容 (调试口 CLI 的 db00/db01 可读
   0x20070000 区), 观察 FT8 频段时 reg 变化, 可快速反推控制通道语义。

## 附: 关键地址速查

| 作用 | 文件偏移 | RAM/DSP 地址 |
|---|---|---|
| M33 Reset/引导 | 0x11A8 | 0x080011A8 |
| M33 scatter 表 | 0x1130 | 0x08001130 |
| M33 应用 start | 0x629B8→0x62CAC 系列 init | 0x0806187C→0x80000 |
| create(线程) | 0x63A3C | 0x821C0 |
| Command Task 入口 | 0x626EC | 0x80E70 |
| IPC Task 入口 | 0x629E8 | 0x8116C |
| DSP 启动函数 | 0x65E18 | 0x8459C |
| w()/r() 寄存器原语 | 0x62638 / 0x6261C | 0x84DBC / 0x84DA0 |
| 模式调度器 (c4fm/gmsk/afsk/voice) | 0x62D54 | 0x851D8 |
| CLI 解析器 | 0x631F4 | 0x85578 |
| DSP blob (HiFi4) | 0x21E88-0x5C3D0 | 0x200000-0x23A548 |
| Composite_SPI 任务入口 (Xtensa) | 0x4F8EC | 0x22DA64 |
| Rx_Audio 任务入口 (Xtensa) | 0x45C7C | 0x223DF4 |
| Rx_C4FM / Tx_C4FM 入口 | 0x45D0C / 0x4954C | 0x223E84 / 0x2276C4 |
| Rx_Path / Tx_Path 入口 | 0x512F4 / 0x514A4 | 0x22F46C / 0x22F61C |
| DSP 寄存器堆 (共享) | — | 0x20070000+2*reg |
| M33↔DSP 队列 | — | 0x20020000 / 0x20030000 (+0x8000 别名) |

置信度标注: §1 全部高置信 (向量表/scatter 双向验证+丝印); §2 M33 高置信, HiFi4 入口中高置信;
§3.1/3.2 高置信, §3.3 中置信, §3.4 帧格式未知待 Xtensa; §4 高置信 (寄存器语义为低置信推断)。
