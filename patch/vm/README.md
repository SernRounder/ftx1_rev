# ftx1vm — FTX-1 DISPLAY full-system virtual machine

> 本页记录虚拟机结构和早期镜像。当前联合版的构建和整机回归命令见 [复现指南](../../docs/reproduce.md)。

从 reset 向量启动的整机模拟器:固件自带的 µITRON 内核、scatter loader、
中断系统和所有任务**真实执行**,VM 只提供硬件。与 `patch/preview_ft8.py`
(调用级 harness)互补,覆盖了它没有的东西:中断时序、OSTM tick、
GIC 投递、任务调度、真实字体渲染、SVC/syscall 全路径。

## 状态(2026-11-10)

| 能力 | 状态 |
|---|---|
| stock display.bin 从 reset 启动到调度器 | ✅ 全部 12 个里程碑在 10 ms 虚拟时间内 |
| µITRON tick(OSTM0 10.0 ms / OSTM1 1.0 ms @ P0φ=32 MHz; 若 P0φ=33.33 MHz 则为 9.6 / 0.96 ms) | ✅ GIC IAR/EOIR 中断全通 |
| SVC syscall(svc #0 + r0=服务号) | ✅ 300 ms 内 4200+ 次 |
| SCIF5 UART + MainSim 对端(0x65 时钟) | ✅ 双向;面板命令 ACK/频率应答为静态默认 |
| UI 渲染(字体从 flash 元数据真实创建) | ✅ FT8 菜单 fill/text/bitmap 上屏 |
| FT8 端到端(bind→sync→WAV→DMA 路径→解码) | ✅ 121 帧 8 条消息,与调用级 harness 一致 |
| 触摸/按键链(0x41D4/0x232E0→ft8_hit) | ✅ 调试后门注入 |

## 用法

```bash
cd patch/vm
python test_boot.py                      # stock 启动测试(~7 s)
python test_ft8_session.py               # FT8 全流程测试(~25 s)
python run_vm.py --boot-ms 500           # 跑 500 ms 并打印统计
python run_vm.py --sfl ../../outputs/FTX-1_DISPLAY_V0110-ft8menu-TEST.sfl \
                 --show-mode --screenshots ../../outputs/ftx1vm
python run_vm.py --sfl ../../outputs/FTX-1_DISPLAY_V0110-ft8live-LAB.sfl \
                 --wav ../../downloads/210703_133430.wav --screenshots ../../outputs/ftx1vm
```

Board API:`boot` 由 `Board(image)` + `reg_write(RESET_ENTRY)` + `run(ms)` 完成;
`call_debug(offset,*args,stack=,end=,budget=)`(借用上下文调 stock 函数)、
`tap_debug(x,y)`、`show_mode_debug()`、`screen()`、`main.frames`、`irq_stats()`。

## 结构

```
ftx1vm/addrs.py        地址常量(全部带 work/an 出处)
ftx1vm/core.py         ArmCore:异常注入(SVC/UNDEF/IRQ 银行寄存器切换)、
                       切片执行、时钟推进、unicorn 绕过(见下)
ftx1vm/clock.py        虚拟时钟 + 事件堆(ns 精度)
ftx1vm/bus.py          MMIO 总线(per-device 读值替换/写捕获,未映射兜底)
ftx1vm/devices/gic.py  PL390/GICv1(优先级/PMR/嵌套 active 栈)
ftx1vm/devices/ostm.py OSTM0/1(OCR 周期,tick→GIC,默认 P0φ=32 MHz)
ftx1vm/devices/scif.py SCIF5(FIFO/RDF/TDRE/RXI/TXI)
ftx1vm/devices/stubs.py RIIC 最小模型/SPIBSC(QSPI)/CPG/PL310/SDHI/通道完成标志
ftx1vm/main_sim.py     MAIN 协议对端(AA 00 组帧解析、ACK、0x65 时间推送)
ftx1vm/board.py        组装 + 主循环 + 里程碑追踪 + 调试后门
run_vm.py / test_boot.py / test_ft8_session.py
probe_unicorn*.py, diag_*.py   M0 探针与调试脚本(保留作文档)
```

## unicorn 2.1.x 绕过(重要,全部经最小复现实锤)

1. **Thumb IT 状态机 bug**:IT 块含 32 位条件指令时(ITTT HS+stmhs.w+bhs.w,
   如 stock `__aeabi_memset` 0xBDD64)翻译错乱(Bcc.W 被误译 BL/invalid)。
   绕过:`PYLIB` 用 Python 重实现 memset;boot 头其余 IT 在"条件成立路径"
   语义等价。干净环境不可复现——只在长执行流出现。
2. **WFI 不解码**(UC_ERR_INSN_INVALID):跳过并置 `sleeping`,主循环快进
   虚拟时间到下一事件。
3. **CP15 cache 维护循环**(0x3058 set/way,~百万指令):stub 跳过(TCG 无 cache)。
4. **`svc #0` 语义**:固件 syscall 是 `svc #0` + r0=服务函数地址(dispatcher
   0x60400160 `bx r0`);内核内部另有一处 UNDEF trap(0x60416510 的
   0xE7DF151F,自相矛盾编码,真机 UNDEF/QEMU 宽松解码为 bfc)——单点
   CODE hook 注入 UNDEF 异常。
5. 模式切换(SVC/UNDEF/IRQ)直接写 CPSR+银行寄存器(探针验证往返正确)。

## 音频注入层次

与计划一致:虚拟时间每 125 ms 一帧(`u16 count, u16 metadata, 2ch×s16`),
以 `call_debug(0x45170, frame, end=0x45174)` 走 stock DMA 完成路径(即
真机 RSPI4+DMAC 中断最终抵达的 stock 调用点,调用级 harness 已验证等价)。
RSPI/DMAC 寄存器级留待后续;`SilenceSource` 静音/`WavSource` 已由
`run_vm.py --wav`/测试覆盖;**FT8 合成信号源接口即此处替换**(用户预留项)。

## 已知限制 / 下一步

- **stock UI 任务 parked**:FUN_0004367C 等 MAIN 握手(生产模式 gate
  0x607C0594=1 已过,卡在更深的等待,推测等 MAIN boot 命令序列)。
  现用 `call_debug` 驱动 worker/直绘绕过。**下一步:抓真机 MAIN→panel
  boot 命令流填进 MainSim**,UI 任务自转后 worker 上屏(RX 页)即通。
- RIIC 为最小模型(触摸 IC 坐标数据未模拟;tap 走 0x41D4 后门)。
- RTC S-35190A 位操作级、PORT 按键线:未做(MainSim 0x65 已喂时钟)。
- unicorn TB 缓存对运行时改码不失效(SMC)——避免运行时 patch。

## 性能

~16 MIPS(boot 300 ms ≈ 7 s wall);FT8 槽解码(FFT+LDPC,~8 亿指令预算)
单帧 poll 最重约 1 分钟内。对 15 s 槽全流程 ~25 s wall(无解码的帧很快)。
