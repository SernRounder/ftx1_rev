# 从公开检出复现联合版

本流程以 Windows x64、PowerShell 7 和 Python 3.11.9 为基准。从原厂日版输入重建 FT8 / CW_DEC / SWR SCAN 的 DISPLAY 与 MAIN，进行离线测试，并核对结果是否与开发工作区一致。从仓库根目录运行命令。

## 1. 克隆和准备环境

安装 Git、Python 3.11 和 PowerShell 7.4 或更新版本。宿主 C 回归需要可在 PATH 中调用的 Windows 原生 gcc，例如 [w64devkit](https://github.com/skeeto/w64devkit)。

~~~powershell
git clone https://github.com/SernRounder/ftx1_rev.git
Set-Location ftx1_rev
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
py -3.11 -m venv .venv
$py = (Resolve-Path '.venv/Scripts/python.exe').Path
& $py -m pip install -r requirements.txt

New-Item -ItemType Directory -Force work/tools,downloads | Out-Null
git clone https://github.com/kgoba/ft8_lib.git work/ft8_lib
git -C work/ft8_lib checkout --detach 9fec6ca39886edbf96f4f5e71edc76da5074e871
$ft8Patch = (Resolve-Path 'third_party/ft8_lib-ftx1.patch').Path
git -C work/ft8_lib apply --check $ft8Patch
git -C work/ft8_lib apply $ft8Patch
git clone https://github.com/Nikolay-Kha/ft710-internals.git work/tools/ft710-internals
git -C work/tools/ft710-internals checkout --detach c7b12bdb621109cbca6d4c2aa4334332421f74bf
git clone https://github.com/sq9pd/Yaesu-FTX-1-mod.git work/tools/Yaesu-FTX-1-mod
git -C work/tools/Yaesu-FTX-1-mod checkout --detach ee71225da9db6200a8098547f4f00b6caf438371
~~~

重复构建时沿用已准备的依赖。已应用的 FT8 补丁可以用 `git -C work/ft8_lib apply --reverse --check $ft8Patch` 确认。

- 下载 [Zig 0.14.1 Windows x86_64 ZIP](https://ziglang.org/download/0.14.1/zig-x86_64-windows-0.14.1.zip)，解压至 `work/tools/`。默认须能找到 `work/tools/zig-x86_64-windows-0.14.1/zig.exe`。ZIP 的 SHA-256 为 `554f5378228923ffd558eac35e21af020c73789d87afeabf4bfd16f2e6feed2c`。
- 下载 [RX GCC 13.2.0 Windows ZIP](https://github.com/ckormanyos/gcc-rx-elf/releases/download/v13.2.0/gcc-13.2.0-rx-elf_x86_64-w64-mingw32.zip)，解压完整目录。以下用 `$rx` 表示含 `rx-elf-gcc.exe`、`rx-elf-as.exe`、`rx-elf-ld.exe` 和 `rx-elf-objdump.exe` 的 `bin`。保留工具链旁的 `libexec`。

~~~powershell
$rx = 'C:\path\to\gcc-13.2.0-rx-elf\bin'
& work/tools/zig-x86_64-windows-0.14.1/zig.exe version
& (Join-Path $rx 'rx-elf-gcc.exe') --version
~~~

## 2. 准备原厂输入

取得 [Yaesu 2026-08-28 日版固件 ZIP](https://connect.yaesu.com/indivisual/wp-content/uploads/2026/08/FTX-1_JPN_Firmware_Update_20260828.zip)，放入 `downloads/`。准备脚本会校验各文件的 SHA-256，解包 DISPLAY，生成 MAIN 分析映射和本地的 `patch/sq9pd_mod_data.json`。

~~~powershell
& $py -B scripts/prepare_inputs.py --zip downloads/FTX-1_JPN_Firmware_Update_20260828.zip
~~~

若已单独提取原厂 SFL，将 DISPLAY、MAIN 和可选的 IFDSP 放到 `work/fw/` 后运行同一脚本，省去 `--zip`。同版本的其他地区固件可能有不同内容。

| 原厂输入 | SHA-256 |
| --- | --- |
| DISPLAY V01-10 | 962fda27ae2f0a0deedb039b868a545ef0f6736b686c266e19f231dbe3973bba |
| MAIN V01-13 | de02ce415b37ca6621ed0bac2f8e7bd63d45f3022a62868598950502ed033f5c |
| IFDSP V01-10，分析用 | 477afb2ae9f8d04ed5c7f1036eb7f84e23c98593edc9458db14be6351335f3e0 |
| 解包后的 DISPLAY | ba4a2fb2b1e7b00f3dd7353efd1548629caa339b77eab0900bed92204d57ceeb |

## 3. 构建 DISPLAY 和 MAIN

~~~powershell
$out = 'outputs/ft8-cw-swr-fix'
$display = "$out/FTX-1_DISPLAY_V0110.SFL"
$main = "$out/FTX-1_MAIN_V0113.SFL"
$displayBuild = "$out/display-build"
$mainBuild = "$out/main-build"

& $py -B patch/build_ft8_menu.py --radio --tx-hooks --custom-modes --vfp-only --cw-debounce --build-dir $displayBuild -o $display
& $py -B patch/build_ft8_main.py --toolchain $rx --build-dir $mainBuild -o $main
Get-FileHash -Algorithm SHA256 -LiteralPath $display,$main | Format-List
~~~

| 本地输出 | 字节数 | SHA-256 |
| --- | ---: | --- |
| FTX-1_DISPLAY_V0110.SFL | 2,949,688 | d869e0799add342c250e530775feaa8c223e1931c3f325d4d348e5d9fac3a40a |
| FTX-1_MAIN_V0113.SFL | 3,245,088 | ff0ebd9b4e81b83a1b7818469831cc1caa0749b8b6a8be243587e6cbb36863c3 |

DISPLAY 载荷为 10,904 / 10,970 B 与 53,304 / 53,312 B。MAIN 新载荷为 459 / 574 B 与 616 / 1,477 B。验证脚本需要同一次构建生成的 ELF。SFL 已经过 CRC 和回读校验。

## 4. 离线回归

~~~powershell
# 宿主 FT8 收发和底层协议
& $py -B patch/test_ft8_rx.py
& $py -B patch/test_ft8_tx.py

# MAIN 差分、RX objdump、DISPLAY 上的原厂 MAIN 更新读取代码
& $py -B patch/test_sq9pd_main_integration.py --toolchain $rx
& $py -B patch/test_ft8_main_updater.py $main

# DISPLAY 的音频 DMA、控件、整机启动和调度
& $py -B patch/test_ft8_radio_dma.py $display --build-dir $displayBuild
& $py -B patch/test_custom_modes.py $display --build-dir $displayBuild
& $py -B patch/vm/test_radio_boot.py $display --build-dir $displayBuild --replay --gaps
~~~

下载 [WSJT-X 的 210703_133430.wav 样本](https://downloads.sourceforge.net/project/wsjt/samples/FT8/210703_133430.wav) 并放入 `downloads/`。预期 SHA-256 为 `9feb99c275770a6618538026da7decc6b09eb6cf63121e5168fa86dcdf00c2f5`。以下回归使用其真实 PCM 验证接收、发射和恢复接收。

~~~powershell
Get-FileHash -LiteralPath downloads/210703_133430.wav
& $py -B patch/test_ft8_tx_rx_windows.py $display --build-dir $displayBuild --wav downloads/210703_133430.wav
~~~

两个完整接收窗实测各保留 215,200 个 PCM 样本，均译出同样的 8 条消息。中间窗含 253 个发射块、7,200 个接收样本及 0 条新译码。脚本完成时会打印 `exact match`。其他运行应出现各自的 PASS 行，所有进程应以状态 0 结束。这里的 TX 在仿真里执行。

独立 CW 目标可用同一套输入重建，覆盖合成弱信号、抖动、掉点、发射时暂停译码，以及原厂调度器上的启动。

~~~powershell
$cw = 'outputs/cw-local'
& $py -B patch/build_cw.py --build-dir "$cw/build" -o "$cw/FTX-1_DISPLAY_V0110.SFL"
& $py -B patch/test_cw.py "$cw/FTX-1_DISPLAY_V0110.SFL" --build-dir "$cw/build"
& $py -B patch/vm/test_cw_boot.py "$cw/FTX-1_DISPLAY_V0110.SFL" --build-dir "$cw/build"
~~~

## 5. 逆向、实验分支与实机状态

- [分析指南](analysis.md) 给出 Ghidra 导入参数、定点反编译及 RXv2 指令仿真入口。[操作说明](operation.md) 记录联合版按键与菜单行为。
- 四页软键的独立 MAIN 实验通过了更新器模拟及九处挂钩的反汇编检查。旧的 `--with-ft8` 组合与当前 MAIN 构建接口和 C2 布局不兼容，FT8/CW/SWR 使用第 3 节的联合构建。
- [SSTV 交接](sstv/交接文档.md) 是 Robot 36 调研和开发方案。
- 本次复现覆盖离线构建与模拟器。现场刷写、发射功率、TX FAULT 和射频质量需单独实测。设备持有者可查 [Yaesu 原厂更新手册](https://connect.yaesu.com/indivisual/wp-content/uploads/2025/05/Firmware_Ver_Up_Manual_JPN_FTX-1_2507-A.pdf)。

~~~powershell
$softkey = 'outputs/softkey-menu'
& $py -B patch/build_softkey_main.py --toolchain $rx --build-dir "$softkey/build" -o "$softkey/FTX-1_MAIN_V0113.SFL"
& $py -B patch/test_softkey_main.py --toolchain $rx "$softkey/FTX-1_MAIN_V0113.SFL"
~~~

## 6. 可直接交给 AI 工具的任务

> 阅读 AGENTS.md 和 docs/reproduce.md。在当前检出内使用第 1 至 4 节重建 JP 原厂底包上的 FT8/CW_DEC/SWR SCAN 联合版。先确认依赖提交、工具版本和输入哈希，再构建 DISPLAY 和 MAIN，并用同批次生成的 ELF 执行回归。输出两份 SFL 的 SHA-256、每项测试的退出码、预期和实测差异。发现失败时保留现场并报告失败的命令和首条错误。只做离线复现。若继续做逆向，按 docs/analysis.md 给出模块、固件版本、地址及反编译证据。
