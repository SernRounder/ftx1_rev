# FTX-1 DISPLAY V01-10 FT8

> 本页保留早期设计、开发镜像和实验命令。当前 JP 联合版的构建选项、测试与镜像哈希见 [复现指南](../docs/reproduce.md)。

基线为 Yaesu 20260828 日版的 DISPLAY V01-10。原厂 MODE 菜单提供 FT8 入口。

联合台架版使用 `outputs/ft8-cw-bench1` 的 DISPLAY V01-10 与 `outputs/ft8-cw-bench1-main-stream-fix` 的 MAIN V01-13。刷写步骤及哈希见 MAIN 目录的 README。

| 镜像 | 用途 |
|---|---|
| `ft8menu-TEST` | 同长度的菜单实验镜像，显示 `DECODER OFFLINE` |
| `ft8probe-TEST` | DMA 帧头和尾区标记实验镜像 |
| `ft8live-LAB` | 本地 ARM 模拟。没有原厂任务、工作区、时钟或发射适配器 |
| `outputs/ft8-bench-rx/FTX-1_DISPLAY_V0110.SFL` | 台架首刷候选。基于日版 DISPLAY V01-10，供验证启动、菜单和原生接收，界面显示 `TX OFFLINE` |
| `outputs/ft8-bench-rx2/FTX-1_DISPLAY_V0110.SFL` | 第二次台架测试。FT8 页面独立于原厂 MODE 弹窗，BACK 退出。接收使用与 RTC 无关的重叠窗口 |
| `outputs/ft8-bench-rx3/FTX-1_DISPLAY_V0110.SFL` | 修复接收队列停在 10 帧。解码任务优先级为 6，诊断增加 `OUT` |
| `outputs/ft8-bench-rx4/FTX-1_DISPLAY_V0110.SFL` | 保留最近一次成功的解码，短时队列溢出后继续扫描 |
| `outputs/ft8-bench-rx5/FTX-1_DISPLAY_V0110.sfl` | 第五次台架候选。24 条解码池、排序/分页、UTC 时间键盘、PO 功率显示、时隙一次锁定 + 按 slot 去重扫描（见下） |
| `outputs/cw-dec1/FTX-1_DISPLAY_V0110-cw.sfl` | 独立 CW 解码固件（见下节）。无 FT8 耦合 |

## 独立 CW 解码固件（cw-dec1）

`python patch/build_cw.py --build-dir patch/build_cw -o outputs/cw-dec1/FTX-1_DISPLAY_V0110-cw.sfl` 构建，`python patch/test_cw.py <镜像> --build-dir patch/build_cw` 验证（十组用例全过）。基线日版 DISPLAY V01-10，五个挂钩（MODE 弹窗绘制、触摸分发、命中测试、UI worker、DMA 捕获），载荷 8696/10970 B。此构建不含任何 FT8 代码，也没有 CUSTOM 二级菜单——MODE 弹窗中原 FT8 槽位直接改标 `CW_DEC`，单击即武装解码会话（`--custom-modes` 联合构建才会出现 CUSTOM 入口与 FT8/CW 二级选择屏）。

- **入口**：原厂 MODE 弹窗中原 FT8 槽位改标 `CW_DEC`，单击即武装解码会话。MODE 弹窗的显示状态由 MAIN 驱动（DISPLAY 0x232E0 只把触摸事件打包转发），所以武装后再用原厂方式关掉弹窗（点当前模式或弹窗外）即回主屏，停靠条出现在频谱下方（y 378–420）、原厂软键之上，不遮挡频谱调谐。
- **解码**：AFC 窄带跟踪——未锁定时全频段(300–1100 Hz)每第 4 个分析步选最强 Goertzel 音调；锁定后仅在 ±2 bin(±50 Hz)内跟随，速度自适应 12–45 WPM。只解最强音。
- **诊断**：caption `20WPM 625 R152` = 估计码速、锁定音调 Hz、已捕获音频帧数（`WAIT`=未锁定；`CW-U/L`=不在 CW-U/CW-L 含发射；`CW OFFLINE`=任务未起）。未出文本时第一行文本区显示 `F768 D0 P7 G9 L4900 S600`：F=每帧字数、D=声道判定（0 单声道 / 1 双声道同款 / 2 双声道异款）、P=捕获端实测峰值幅度、G=自适应输入增益(2^G)、L=解码器看到的音调包络峰值、S=最强 bin 频率。判读：P=0 → DMA 流静音；P>0 而 L=0 → worker 没喂数；P、L 都健康仍不锁定 → 看 S 是否在 300–1100 内。

### 已修问题：MODE 弹窗左上角(标题栏)按钮花屏（func_menu_tile）

现象曾是：进入 MODE 弹窗后，左上角第一个按钮(原厂标题栏瓦片)背景花屏。根因：原厂 FUNC 菜单的一处 110×50 位图调用(0x38868)其瓦片资产数据落在载荷洞附近，镜像塞入载荷后被读出花屏数据。修复：`func_menu_tile.S` 在 0x38868 以 BL 挂钩，用手绘瓦片（5488 白像素五段行程、仅四角透明）替代该次位图调用，`FUNC_TILE_HOOK` 已进入 build_cw.py 与 build_ft8_menu.py 的默认 hook 表。此前排查记录（按钮表 0x604dd814、RAM 偏移 0x607c0a12/16、字体上下文等嫌疑最终均排除）与按钮表/配置资产 RE 数据见 work/an/cwdec_export/。
- **自适应输入增益**：实测该音频口的电平贴近 16 位底（底噪峰 4–5、信号峰 7），音调在 Goertzel 的整数域功率仅 ~1.2，低于绝对门 4，且 300 Hz 初始 bin 恰在音调频率的 Dirichlet 零点。worker 按每帧实测峰值把流左移 2^G（目标峰值 1024–24576，饱和裁剪），码元比值尺度不变，解码判决不受影响。VM 复现峰值 8 的流完整解码 15 WPM；放大后的低电平噪声仍被比例门拒收。
- **码速范围**：10–45 WPM 自适应（下限 2026-11-12 从 12 降为 10，覆盖慢手法）。
- **双域时基**（2026-11-12，修"不稳码速解出一堆 e"）：点/划判定用 mark 域 `unit`，元素/字母/词间隔判定用独立的 `gap_unit`——音调门削短 mark 时会把间隔等量拉长，单一时基无法同时匹配两个域，间隔被误判为字母间隔即产生单点字母连刷（E）。两域各自按 ±50%/±75% 窗口跟踪（大偏差中点快拉、小偏差 1/8 细调）；元素间隔是最密的时序参考，间隔入跟踪后码速漂移在一两个字母内跟上。VM 覆盖：20→14→20 WPM 段内漂移、6/12 ms 键控边沿、22% 元素抖动均正确解码。
- **声道自适应**：捕获流可能是单声道，也可能是 L/R 交错（同款复制或两路不同）。按对内差/相邻相关自动判定（乘法比较，无 64 位除法），交错时只喂单声道（dup/mono 均在 VM 验证解码）。分类在 worker 任务里对已复制的帧进行；**DMA 完成路径只做与旧版完全相同的头校验+复制**——帧头 count 先验 `> MAX_PCM` 再碰任何载荷字（一次实机教训：count 未验先读会在坏帧上野生读越界，真机 DATA ABORT 整机冻死，unicorn 不仿真中止所以 VM 全绿）。

- **低置信度输出**：超长电码(>6 元素)输出 `?` 且不打断后续；时基崩塌时把未完成字母按小写最佳猜测输出（大写=可信，小写=低置信，`?`=非法码）。弱信号下输出降级文本而不是静默。
- **解调门限**：真实 AF 是带限有色噪声，纯宽带能量门会漏。现要求信号 bin 达到 33 bin 谱底噪（剔除最强两个）的 8 倍 + 窗口能量 >>17 + 包络迟滞 + 最短键控 15 ms。有色噪声 10 种子 ×12 s 零误码；信噪比 -4 dB 完全解码，-7 dB 降级输出。跟踪器仅在码元期间允许换 bin（间隙冻结），杜绝间隙期噪声拖走音调。


这三个镜像都没有经过实机启动和恢复验证。当前 LAB 未接入发射适配器时显示 `TX OFFLINE`，无法武装，不应刷进实机。旧版 LAB（SHA-256 前缀 `0aa9cf51c2be4158`）的发射与刷写审计结论已撤回。

## 本地复现

```powershell
python patch/build_ft8_menu.py --live
python patch/test_ft8_live.py
python patch/test_ft8_arm.py
python patch/test_ft8_tx.py
python patch/preview_ft8.py --live
```

预览用公开 WAV 回放接收。在 `MY GRID` 区域输入本台呼号，选择消息，再按 `TX NEXT` 可运行模拟发射。默认位置是演示坐标，`--position LAT LON` 或 `--grid LOCATOR` 可覆盖。

FT8L v6 只在显式提供适配器后处理发射。轮询先检查取消和页面会话，再处理队列。失步、提交失败和超时会请求释放。排空音频、确认解键后才写发射历史。Unicorn 提供虚拟时钟、音频和限时租约。这个租约验证的是接口契约，实机适配器必须在独立于 FT8 工作任务的路径上强制解键。

原生 FT8 在发完标准 `73`，或发完 `RRR` 后 90 秒内收到同一对呼号的 `73` / `RR73` 时，向 SD 卡的 `FTX-1/FT8LOG.ADI` 追加记录。记录包含电台时钟、可用的本台网格、发射拨盘频率加音频频偏所得的 `FREQ`（MHz），以及 MAIN 确认键控时回报的设定功率 `TX_PWR`（W）。两次连续收尾属于同一对方时只追加一次。

FT8 界面在网格输入下方提供 `TX Hz`，范围为 200–2800 Hz，默认 1000 Hz。点击 `TX NEXT` 时锁定该次发送使用的频偏。此功能的功率记录需要配套的 DISPLAY 与 MAIN。

MAIN 在 `0x20`、`0x60`、`0x62` 的公共状态头回报发射状态、功率和当前 FT8/CW 模式。偏移 33 低位指示功率单位，其余位携带模式和修订号。DISPLAY 在交还原厂处理前还原偏移 9、32、33 和整帧校验值。

接收先用 15 秒滚动窗寻找完整报文，每次向前推进 1.92 秒。第一次有效解码以 320 毫秒内报文最多的一组锁定时隙，本次打开 FT8 期间维持这个相位。锁定后将窗口尽量推进到每个时隙约第 13.6 秒，避免对同一组音频反复执行 FFT 候选搜索与 LDPC 解码。PCM 与频谱窗口有固定上限，退出 FT8 时释放工作区和关闭日志读句柄。ADIF 日期和 UTC 由电台时钟提供。

### 频道列表（rx5）

解码池从 8 条扩到 24（`FT8_LIST_RESULTS`），界面每页 8 条，点 BAND ACTIVITY 标题栏的排序按钮循环 RARE/dB/km 三种排序，翻页按钮换页。排序键为 `(2-group)<<28 | score`：回应本机的报文（group 0）最前，普通台（group 1）居中，已在 SD 卡 `FTX-1/FT8LOG.ADI` 通联过的台（group 2）最后；组内 RARE 按"DX 前缀在本次结果中出现越少、距离越远越靠前"，dB 按信噪比降序，km 按距离降序。已通联缓存在工作区后台分块读取（每 worker 循环 512 字节），不阻塞界面。

### UTC 时间与功率显示（rx5）

FT8 页顶部 `TIME OFFSET` 用原厂键盘输入独立的有符号秒数（范围 ±7.5 s）。TX1 选择 00/30 秒，TX2 选择 15/45 秒，实际发射边界是对应的本机 RTC 秒沿加偏移。`RX` 显示最近解码槽，`D` 是每条消息相对已应用偏移后的残差，`AVG D` 是同一槽的一批结果的平均值。偏移与奇偶槽都在 RAM 中，FT8 不写系统 RTC。SENT MESSAGES 标题右侧显示 `SET xx.xW`，使用 MAIN 状态帧的设定功率，回报过期时显示 `--`。SWR 沿用已移除的版本。

### 自动通联与 CW 重捕获

FT8 的 `AUTO` 默认关闭。启用后，点选 CQ 或发给本台的有效报文，固件在对方接收时隙发送下一条标准报文。后续只采纳同一对方对本台发来的对应阶段报文。完成、超时、STOP、关闭 AUTO 或退出页面时结束通联。默认使用当前 `TX Hz`，等待应答超时为 45 秒。

`FULL AUTO` 使用当前本机呼号、网格和 `TX Hz`，从下一有效时隙开始 CQ。每轮在 CQ 的应答时隙全频搜索，队列只收发给本机的有效网格或报告，最多 24 个候选。SD 日志核对结束后按距离从近到远接续，未知距离排最后，同距离优先强信号。对当前电台的解码窗口跟随其接收频偏，约 ±50 Hz。每个等待应答的步骤最多发送两次，发现当前电台正在回复别人便切换到下一台。每次启动共发送最多三次 CQ。右下角显示已完成 QSO 数、待通联数、剩余 CQ 数及接下来六台的频偏、报告和已知距离。按 `STOP`、再次按 `FULL AUTO` 或退出页面可取消。

VFP 台架版在原生命令 `--radio --tx-hooks --custom-modes` 上加 `--vfp`。首次进入 FT8 后由接收线程探测，拒绝访问或探针触发未定义指令时回退到软件 FFT。只有接收 FFT 执行硬件浮点，初始化、LDPC、UI、CW 和发射仍使用原实现。`test_ft8_arm.py --rolling --vfp-probe hardware|fallback|denied --payload <ft8_rx.bin>` 分别验证可用、异常和权限拒绝。真机权限及处理速度待验证。

原生 DISPLAY 的原厂入口通过 ARM `B` 或 `BL` 直达 `0x606C3040` 起的钩子向量表。每个槽是 4 字节 ARM `B`，保留原入口的调用约定。原生构建使用 `ft8_rx.elf` 同时链接两个区域，`ft8_radio.bin` 保留实时 PCM 收发、工作区接口和协议只读表，`ft8_rx.bin` 包含菜单、触摸分发、向量表和模式逻辑。`build_ft8_menu.py --radio` 负责完整打包。单独运行接收器模拟时，ABI 28/29 从同一目录读取这两个二进制。

默认原生 DISPLAY ABI 28/29 将完整队列显示编入固件，功能开发优先使用现有镜像空间。只有显式传 `--sd-plugin` 时才生成 ABI 30/31 的动态加载实验镜像。该镜像进入 FT8 后由空闲接收工作线程尝试读取 `FTX-1/FT8QUEUE.BIN`，成功后保留到下次开机。更新 `.BIN` 后重启即可加载新版。文件缺失或校验失败时，队列保留呼号与统计，下次进入 FT8 可重试。`python -B patch/build_ft8_plugin.py -o FT8QUEUE.BIN` 单独构建插件。文件头包含 `FT8P`、插件 ABI、代码长度、带 Thumb 位的入口偏移和覆盖前述字段及代码的 CRC32。代码段最多 16 KiB，插件用位置无关代码和宿主函数表。只放入可信来源的插件，CRC32 用于检查文件完整性。模拟验证使用 `test_ft8_radio_dma.py --plugin FT8QUEUE.BIN`。

CW 保留三个译文行。噪声造成的短暂跳变不会延长旧锁定，连续 2.5 秒没有可信码元时重搜音调和码速。元素间隔估计以码元时间为下限参考，避免 `-.-` 被过早分隔。

## 完整收发的实机验证

1. 在可恢复的测试机上先证明原厂 DISPLAY 的更新、冷启动和独立恢复。更新窗口大小、Stage 1 空洞和运行时内存是不同约束。打包器和链接脚本把尾区限制在原厂启动搬运终点 `0x606D0000` 以内。
2. 核实真实 RX 帧、RAM 和栈归属、浮点上下文以及 UTC 时隙对齐。测试固件没有注册这套任务。
3. 原生发射以 RAM 中的 FT8 PCM 直接接入 SPI DMA。原厂播放链只作为帧格式和寄存器的证据。实现见 `payload/ft8_dma_tx.c`，它支持 800/1600 采样帧及独立的 DMA 缓冲区生命周期。实机适配器仍须连接并验证 CH3 提交、完成和取消。
4. 验证适配器能确认实际 TX 所有权、模式、波段和已排空音频，并在 PCM 欠载、退出、失步、任务卡死或串口异常时强制解键。正常波形和故障停发都需要实际测量。

## 直接 DMA 的本地验证

- 原厂 DISPLAY 在 `0x604452B4` 设置 DMAC CH3 的 N0SA。原厂每次传输 `0x2260` 字节，写入端必须清理整段缓存。CH3 完成回调 `0x60463DB4` 与 CH4 接收完成分开。候选适配器只有在原厂选择静音、无录放、收到音频 credit 且 CH3 空闲无未处理完成时才可替换源。归还必须匹配实际完成的帧。
- MAIN 的 E8 请求由 `0xFFED6966` 入队。`0xFFF579C0` 的开启分支只设置播放音频通路 `+0x21D82`。原厂播放菜单在 `0xFFF584A1` 另行设置键控原因 `0x008013C5`。CAT 的收发状态从 `0x00017B54` 读取。DISPLAY 收到的红灯状态在 MAIN 禁发时也可能被置位。原生开发镜像因此禁止发射租约。
- `python patch/vm/test_stock_scheduler.py` 在 RAM 中从原厂复位指令起跑，验证建任务 `0x60478FB0`、延时 `0x604797C8` 和 10 ms OSTM 节拍。测试使用 VM 专用栈，不分配实机地址。
- `python patch/test_ft8_tx.py` 验证打包字节、缓存清理范围、队列满、结束前禁止重用，以及禁止选择后如何归还在途帧。
- `--radio --tx-hooks` 编译与 FT8 MAIN 配套的 DISPLAY。ARM 测试模拟 MAIN 回报及 DMA 寄存器，验证一帧 202,240 个有效采样按原厂帧格式交付，取消后由完成回调归还在途缓冲。MAIN 用 `build_ft8_main.py` 构建，`test_ft8_main_rx.py` 在 RX 指令模拟中执行打包后的挂钩。
- MAIN SFL 正文使用连续编码。原厂 DISPLAY 的 `0x13C74` 跨读取缓冲保留密钥位置。`test_ft8_main_updater.py` 执行原厂 `0xABC4` 的 CRC 与 S-record 读取路径，可用 `--reject` 验证两版错误封包在通过 CRC 后被拒绝。

```powershell
$tx = Join-Path $env:TEMP 'ftx1-ft8-tx-hooks'
python patch/build_ft8_menu.py --radio --tx-hooks --build-dir $tx -o (Join-Path $tx 'ft8-tx-hooks-vm.sfl')
python patch/test_ft8_radio_dma.py (Join-Path $tx 'ft8-tx-hooks-vm.sfl') --build-dir $tx
```
- 16 kHz 接收器的实际分配量是 269,816 B。接收器预留现为 272 KiB，工作任务栈为 40 KiB。FFT 前向变换在读完输入后复用同一缓冲区写频谱，保持 2× 时间和频率过采样。
- 启动模拟在初始化 LCD 之前已观察到原厂内核分配 `0x50000` 字节和其它任务内存。图形库另有 384 KiB 内存池。两者都必须计入同一块 SRAM 的预算。模拟器尚未覆盖所有原厂任务和 DMA 行为，不能据此划定实机空闲区。

构建不依赖 VFP 的 Thumb-2 测试载荷。此命令生成裸载荷，供下方模拟命令使用。该目标采用定点归一化 min-sum LDPC，普通 LAB 仍使用原求和乘积解码器。本地 25 段 WAV 对照中，普通解码器解出 293 条，定点版解出其中 292 条。标准测试录音的时隙收尾从超过 8 亿条模拟指令降到 8800 万至 9600 万条。该数值用于比较软件路径，实机耗时需要测量。

```powershell
python patch/build_ft8_rx.py --soft-float
python patch/test_ft8_arm.py --payload patch/build/soft-float/ft8_rx.bin --without-vfp
```

## 原生开发镜像

`--radio` 生成原生 SFL，要求显式指定输出路径。原厂调度器启动 FT8 解码任务，打开和退出菜单时申请和归还通用工作区。台架镜像的键控处于禁用状态。

`test_radio_boot.py --replay` 在原厂调度器下向实际捕获入口注入录音，已解出三条已知消息。模拟器为无 SD 卡和 LCD I/O 提供桩。真实 DSP DMA 时序待实机验证。

带 `--tx-hooks` 的 DISPLAY 从原厂 `0x60` 设置帧读取 `MY CALL`，进入 FT8 时预填。原厂 DISPLAY 的 GPS 任务先解析 NMEA，再构造发往 MAIN 的 `0xE3`。FT8 读取其中已接受的 RMC 定位，换算六位 Maidenhead 网格。失锁或超过 3 秒无有效定位时，使用 FT8 手动输入的网格，其次使用构建参数 `--grid`。`test_custom_modes.py` 在模拟器中运行原厂 NMEA 解析和 GPS 任务，覆盖两个半球、失锁和手动回退。

解码器的 269,816 B 分配分布在 `[0x603D0880,0x60400000)` 和 `[0x609EBE30,0x60A00000)`。模拟启动期间没有观察到原厂访问这两个窗口。32 KiB 工作栈和 4 KiB 看门狗栈位于启动搬运终点 `0x606D0000` 之后。通用堆工作区为 43,312 B，另需最多 31 B 对齐空间。发射期间两个 DMA 缓冲及管理字段复用 `[0x603D5880,0x603D9D60)`，归还在途缓冲后恢复接收，不增加通用堆用量。

第二版从第一块有效 PCM 开始缓存，约 15 秒后开始扫描，此后每 1.92 秒扫描一次。93 个完整符号窗口每次保留 81 个，覆盖 79 符号的完整 FT8 消息。测试录音人为错开 7.3 秒后仍解出四条已知消息。接收模式申请约 42.3 KiB 通用工作区，不分配发射 DMA 缓冲。

屏幕诊断中的 `RX` 是已入队帧数，`SKIP` 是零长度、非法长度或队列满时跳过的帧数，`N` 是最近一帧的采样数，`PK` 是该帧左通道抽样得到的 PCM 峰值，`SCAN` 是完成的解码扫描次数。

第三版增加 `OUT`，表示解码任务已从队列取走的帧数。旧版解码任务在优先级 8。原厂调度器模拟中，让优先级 7 的任务持续可运行，旧版在 10 帧时停止进队、出队为 0。新版解码任务优先级为 6，同样的测试进出队均为 24 帧。原厂 SPI 音频和触控任务仍可抢占解码任务。接收模式只启动解码任务。

第四版在空扫描、音频间断及重新积累期间保留最近一次成功的解码行。队列丢弃已知长度的 PCM 时，接收窗口最多补入 250 毫秒静音。未知长度或更长的间断重新积累音频。`DROP` 统计超长帧和队列满时丢掉的帧，零长度帧不计入。

```powershell
$dev = Join-Path $env:TEMP 'ftx1-radio-development'
python patch/build_ft8_menu.py --radio --build-dir $dev -o (Join-Path $dev 'radio-dev.sfl')
python patch/vm/test_radio_boot.py (Join-Path $dev 'radio-dev.sfl') --build-dir $dev
python patch/vm/test_radio_boot.py (Join-Path $dev 'radio-dev.sfl') --build-dir $dev --replay
python patch/vm/test_radio_boot.py (Join-Path $dev 'radio-dev.sfl') --build-dir $dev --contention
python patch/vm/test_radio_boot.py (Join-Path $dev 'radio-dev.sfl') --build-dir $dev --replay --gaps
python patch/test_ft8_arm.py --payload (Join-Path $dev 'ft8_rx.bin')
python patch/test_ft8_arm.py --rolling --payload (Join-Path $dev 'ft8_rx.bin')
```
