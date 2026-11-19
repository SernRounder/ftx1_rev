# 固件逆向与指令仿真

先按 [复现指南](reproduce.md) 准备日版文件。原厂 DISPLAY 与 MAIN 分别拥有不同的 CPU、内存布局和职责。分析中记录的是版本绑定的地址，复核时同时记录 SFL 哈希。

| 模块 | 本地输入 | Ghidra 语言及装载方式 |
| --- | --- | --- |
| DISPLAY V01-10 | `work/dec/display/display.bin` | `ARM:LE:32:Cortex`，Raw Binary 基址 `0`。主体运行地址用 `0x60400000 + 文件偏移` 换算。 |
| MAIN V01-13 | `work/dec/main-map.bin` | `RX:LE:32:RXv2`，Raw Binary 基址 `0xFFE80000`。也可用 S-record 导入 `work/dec/main-map.srec` 查看各原厂记录地址。 |
| IFDSP V01-10 | `work/dec/FTX-1_IFDSP_V0110.SFL.bin` | Cortex-M33 与 HiFi 4 分开分析。地址、向量和装载候选以 [IFDSP 报告](../work/an/report-ifdsp.md) 为准。 |

MAIN 分析镜像为 1,572,864 B，SHA-256 为 `90a746ccde24476170543c1c4da0649fe1582501b409a83c37ba3dac63d24eea`。其中未被 S3 记录覆盖的 ROM 间隔填入 `0xFF`。

## Ghidra 环境

本地脚本用 [Ghidra 12.0](https://github.com/NationalSecurityAgency/ghidra/releases/tag/Ghidra_12.0_build)、JDK 21 与 PyGhidra 3.0.0。设置 `$env:JAVA_HOME`，把 `$ghidra` 替换为本机的安装目录。MAIN 还需要 [Ghidra-Rare 的 RX 模块](https://github.com/aleph-void/Ghidra-Rare/tree/876253cfdf7ad03a265e50335ae8964f53d7a202/RX)。

对于 Ghidra 12.0 的 raw binary 工作流，历史环境将该版本的 `RX` 模块目录复制至 `Ghidra/Processors/RX`，并用该安装的 `support/sleigh.bat -a` 编译 `Ghidra/Processors/RX/data/languages`。较新 Ghidra 也可安装同版本的 RX 扩展 ZIP，兼容性按 [上游说明](https://github.com/aleph-void/Ghidra-Rare#installing) 核对。运行 MAIN 命令前确认 Ghidra 能选择 `RX:LE:32:RXv2`。

~~~powershell
$ghidra = 'C:\path\to\ghidra_12.0_PUBLIC'
& $py -m pip install --no-index --find-links "$ghidra/Ghidra/Features/PyGhidra/pypkg/dist" pyghidra==3.0.0
New-Item -ItemType Directory -Force ghproj | Out-Null
$headless = @('-m', 'pyghidra.ghidra_launch', '-Xmx4G', '--install-dir', $ghidra,
              'ghidra.app.util.headless.AnalyzeHeadless', 'ghproj')
& $py @headless display -import work/dec/display/display.bin -loader BinaryLoader -loader-baseAddr 0 -processor 'ARM:LE:32:Cortex' -noanalysis
& $py @headless main -import work/dec/main-map.bin -loader BinaryLoader -loader-baseAddr 0xffe80000 -processor 'RX:LE:32:RXv2' -noanalysis
~~~

导入只做一次。上例用 `-noanalysis` 创建供定点脚本使用的项目。如需建立全局函数表和交叉引用，首次导入时去掉该选项，或在 Ghidra 中对已导入程序运行 Auto Analyze。后续脚本用 `-process <文件名> -noanalysis` 重用工程。

~~~powershell
$ghidraScripts = (Resolve-Path scripts).Path
& $py @headless display -process display.bin -noanalysis -scriptPath $ghidraScripts -postScript disas_arm.py work/dec/display-ui-disassembly.txt --a32 00043ae8 00043af4
& $py @headless display -process display.bin -noanalysis -scriptPath $ghidraScripts -postScript decomp_addr.py work/dec/display-ui-decomp.txt 000448b8
~~~

反编译以已识别的函数和指令上下文为基础。若新导入的工程里 `0x448B8` 的跳表出现坏指令或调用者缺失，先从原厂调用点建立 ARM/Thumb 上下文，运行 Auto Analyze，再对照汇编检查跳表。

DISPLAY 的 `0x43AE8` 对应运行地址 `0x60443AE8` 的交换前绘制挂钩。检查 `patch/payload/ft8_menu.c` 和 `patch/payload/cw_panel.c` 如何写入图层 5 后备缓冲，以及关闭或被原厂弹窗接管时如何清理。MAIN 的 `patch/payload/ft8_main.c` 和 `patch/payload/ft8_main_hooks.S` 维护模式修订与软键，并将状态附在 `0x20`、`0x60`、`0x62` 三种公共帧中。对照 [SWR 分析](sq9pd-swr-custom-button-analysis.md) 核对入口、绘制与退出路径。

## MAIN RXv2 执行验证

构建联合版 MAIN 后，用同一原厂 MAIN 工程运行脚本。脚本把构建产物中经过校验的记录写入模拟器，再验证模式切换、键控、计时、功率回报和 SWR 互斥。

~~~powershell
$patchScripts = (Resolve-Path patch).Path
$mainImage = (Resolve-Path 'outputs/ft8-cw-swr-fix/FTX-1_MAIN_V0113.SFL').Path
& $py @headless main -process main-map.bin -noanalysis -scriptPath $patchScripts -postScript test_ft8_main_rx.py $mainImage
~~~

日志应出现 `PASS: USB/DATA-U PTT, timers, power, button dispatch, close revision and SWR exclusion`。若出现 `SCRIPT ERROR` 或缺少 PASS，查看脚本回溯。静态验证可先运行复现指南中的 `test_sq9pd_main_integration.py`，用 RX objdump 和 DISPLAY 更新器模拟执行，不需要 Ghidra。

## 继续分析的入口

- [DISPLAY 到 MAIN 的 TX 与串口](../work/an/report-display-tx-uart.md) 与 [MAIN TX 链](../work/an/tx_study/main/main-tx-chain.md) 记录音频、状态包及发射路径。报告中的历史偏移需对照当前 build 和源码。
- [IFDSP 分析脚本](../work/an/) 中的 `sc_*.py` 从仓库根目录直接执行，如 `python -B work/an/sc_boot.py`。脚本读取准备后的 JP IFDSP 载荷。
- [DISPLAY 虚拟机](../patch/vm/README.md) 记录设备桩、IRQ 和回放层次。验证调度时保留基线与拟验证镜像的相同运行条件。
