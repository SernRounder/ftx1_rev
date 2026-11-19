# MAIN 固件语音发射/键控链逆向结论(main-map.bin,2026-11-11)

方法:Ghidra 12.0 + Ghidra-Rare RX 模块,7 批 headless 反编译(130+ 函数,见 `decomp/`、`index*.md`)。
本文件是"实机 FT8 TX"决策依据。DISPLAY 侧背景见 `../../report-display-tx-uart.md`,既有素材综合见 `../context/context-summary.md`。

## 1. 核心结论(全部静态实锤,高置信)

1. **E8(1) 单命令不能键控。** `ffed6966`(命令分派 `ffed6046` 的 0xE8 分支)只把 mode 写进语音事件槽:
   - mode=0→事件2(停止)、mode=1→**事件3**、mode=2→事件4、0xFF→事件5;
   - 事件消费者 `fff579c0`:事件 3 **只设 PCM_PLAY(+0x21d82)=1**(开音频通路),不碰任何键控字节。
2. **DISPLAY 可发的全部命令(12 个)都不设键控。** MAIN 收 DISPLAY 的命令表就是 `ffed6046`:0xE2/E3/E4/E5/E6/E7/E8/F0/F1/0x4F(+0xE4 清标志)。无一写 0x8013BC-CC 键控请求段。
3. **键控 = 18 个请求字节(0x8013BC-0x8013CC)之一非零**,VOICE_PTT(0x8013C5)→ 原因 0x0A。仲裁器 `ffed0e65` 按固定优先级(BC→…→C5→…→CC)取第一个非零。
4. **VOICE_PTT=1 的设置点全局只有 2 个**:
   - `fff5836e(slot)`——"语音启停开关"(toggle):空闲且 TX 允许(`ffeca60a`→`ffec7edc`)→ VOICE_ACTIVE(+0x21d3d)=1、PCM_SLOT(+0x21b20)=slot、**VOICE_PTT=1**。被 5 个 slot 入口(0xFFEF7973/79 99/79BF/79E5/7A0B,slot 1-5,间隔 0x26)调用;**全库无静态调用者、无函数表指针 → 引用在 RAM(运行时表/任务结构),静态不可达**。
   - `ffeb48dc(cmd,on)`——**CAT class 'D' 命令**处理器(巨型 CAT 分发器 `ffea9c5a` 的 'D' 分支):参数字节 '1'-'5' 选 slot,同样过 TX 允许后 VOICE_PTT=1。CAT 走 MAIN 自己的 USB/串口,**不经过 DISPLAY**。
5. **接受与执行(与 VOICE_PTT 独立于谁设置)**:
   - `ffed101f`(周期仲裁):新原因≠0 → 两周期防抖 → **TX_SEQUENCE(0x801324)=0、TX_ACCEPTED(0x822D62)=1**;
   - `ffed09e9`(TX_SEQUENCE 状态机,周期驱动):0→1(调 `ffec7edc(freq)` TX 允许;向 IFDSP 下发 cmd 0x55,1/0x56,5/0x57,1/0x58,3/0x59,功率/0x69/0x6a,波段)→2(等 0x59 完成)→3(**keyed**,SEND_A 置位经 `ffec08df`)→(请求消失/允许丢失)4→5(**ffec08df(0) SEND_A off** + IFDSP 收尾 0x5a/0x54/0x55-58)→6→7→8(idle)。
   - `ffec08df`:SEND_A = 端口 0x8C02B bit3;硬件条件(0x8C041 bit4==0 && 0x8C022 bit1!=0)时**强制写 0**(硬件级强制解键)。
6. **VOICE_PTT=0 的清理点(6 处)**:播放流结束沿 `fff576c7`(沿检测 `ffec0708`=端口 0x8C04B bit2)、CAT off `ffeb48dc`、语音释放 `ffef7add(0)`(主控制器 `ffefd18f` case 4 调)、E8(0)/E8(0xFF) 事件 2/5 `fff579c0`、**禁发 `ffec7edc`(0x822D63/65 命中时清 0x8013BC-CC 整段 18 字节)**、异常路径 `fff585a7`。
7. **E7(信标)与 E8 同型但独立**(事件槽 +0x22028 vs +0x2202c,APRS 音频由 MAIN/IFDSP 自己合成,不传音频)——FT8 必须走 E8/PCM 路径的判断再次确认。
8. **TX 允许总闸 `ffec7edc(freq)`**:带内查表(波段边界 0xffe96xxx 表)+ 禁发标志(DAT_0145e/04b0f/8013cf/8013d0/8013d1/8013d2 全零)+ 60m 通道限制 + DAT_801326/80131c 限量 + 0x822D63/65 中止 + 0x50f4/0x4b27 附加门。

## 2. 对"不改 MAIN 能否实机 TX"的判定

- **标准命令路径:不可能**(结论 1+2)。DISPLAY 无论发什么组合,MAIN 都不会设 VOICE_PTT。
- **唯一存活动口(动态假说)**:原厂语音播放发射确实工作,而它的键控必然经过 VOICE_PTT——slot 入口的 RAM 表触发者未知,可能由"音频流出现"(fff576c7 的 GPIO 沿)或其它内部事件链驱动。若该链可被"DISPLAY 送音频流"本身激活,则 DISPLAY-only 方案成立。
- **定案实验(频谱仪,零风险)**:原厂 MAIN + 只改 DISPLAY 的镜像,发 E8(1) 后向 CH3 送静音/FT8 PCM,频谱仪看载波。有载波 → 纯 DISPLAY 方案复活;无 → 必须 MAIN 补丁。
- **GPT 的 ft8_main.c 补丁被本逆向背书**:其复刻序列 PCM_SLOT→PCM_PLAY→VOICE_ACTIVE→VOICE_PTT 与原厂 fff5836e+事件 3 的净效果一致;其键控判定四元组(TX_ACCEPTED/原因 0x0A/TX_SEQUENCE==3/SEND_A)与状态机实况吻合。

## 3. 实机 TX bring-up 顺序建议(频谱仪辅助)

1. **实验 A(定案实验)**:原厂 MAIN,DISPLAY-only 镜像(现有 rx4 + 最小 TX 探针:E8(1)+N 块静音+E8(0))。频谱仪假负载看载波。
2. 若 A 无载波 → 刷 MAIN 补丁(ft8_main)走 E8 F8 'FT8' 租约路径;频谱仪验证:键控延迟、载波稳定性、FT8 波形带宽(≈50Hz GFSK)、E8(0)/超时解键。
3. 故障注入实测(README 38 行要求):PCM 欠载/任务卡死/串口拔线 → 频谱仪确认停发(硬上限+E8(0) 重发+看门狗)。
4. 时隙/时序实测:E8→SEND_A 置位延迟(前导 6 块静音是否足够)、块节奏 50ms 与 credit 0x607c4012 门槛实机值。

## 4. 产物清单

- `decomp/*.c` 130+ 函数(reason 标注命中线索)
- `index.md`/`index2.md`(调用图+数据 xref)、`scalar-hits.md`、`ptr-refs.md`、`wrapper-callers.md`、`cat-callsite.txt`、`wrapper-region-disasm.txt`
- `scripts/decomp_tx_addrs*.py`(7 批,可重跑)
- 关键函数速查:E8=ffed6966、事件=fff579c0、启停开关=fff5836e、slot 入口×5=0xFFEF7973 起、CAT 'D'=ffeb48dc、仲裁=ffed0e65/ffed101f、状态机=ffed09e9、SEND_A=ffec08df、TX 允许=ffec7edc、清理=ffeced3b、GPIO 流沿=fff576c7/ffec0708。
