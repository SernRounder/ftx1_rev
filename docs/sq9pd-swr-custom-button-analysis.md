# `sq9pd/Yaesu-FTX-1-mod` 自定义按钮与 SWR 扫描机制分析

> 参考仓库：`https://github.com/sq9pd/Yaesu-FTX-1-mod`（commit `ee71225d`，版本标识 `MAIN V40 + DISPLAY V35`）
> 基线固件：Yaesu FTX-1 `MAIN V01-13` / `DISPLAY V01-10`（20260828 官方包）
> 分析目的：为 `rev_ftx1` 实现 R1–R4（将 `FT8` 与 `CW_DEC` 改为仅通过菜单自定义按钮触发，并评估及集成 SWR 扫描功能）提供完整、可核验的逆向依据与集成接口规范。

---

## 1. 仓库概览、版本与固件基线

### 1.1 仓库形态与纯二进制差分架构

`sq9pd/Yaesu-FTX-1-mod` 对外发布 **MAIN V40 + DISPLAY V35**（`README.md` 与 `TEST_RESULTS.json` 明确标注不含 `MAIN V41` 的 CW 音频修复）。仓库内共有 15 个受跟踪文件，核心包括：

- 清单与校验：`manifest.json`、`TEST_RESULTS.json`、`SHA256SUMS.txt`、`README.md`、`READMEPL.md`
- 离线/浏览器修补器：`patch.py`、`site/patch-core.js`、`site/patch-data.js`、`site/content.js`、`site/app.js`、`site/index.html`、`site/style.css`

该仓库**不包含任何 C/汇编源码、链接脚本或构建系统**（`SHA256SUMS.txt` 中提及的 `docs/CHANGELOG_FTX1*.txt` 与 `docs/INSTRUKCJA_SWR_SCAN.txt` 也未提交），仅在 `site/patch-data.js` 中预置解码后载荷与文件头的字节级差分块（`payload_patches` / `header_patches`），由 `patch.py` 或浏览器端 WebCrypto（`site/patch-core.js`）校验输入 SHA-256 后**严格就地修补**原厂固件。

### 1.2 固件基线与 SFL 容器格式

`sq9pd` 所依赖的原厂底包与 `rev_ftx1` 当前 `work/fw/` 完全一致（详见 [analysis.md](analysis.md)）：

| 组件 | 模组版本 | SFL 文件名 | SFL 大小 | SFL 标签 / 原 CRC -> 改后 CRC | 原厂 SFL SHA-256 | `sq9pd` 输出 SFL SHA-256 |
| --- | --- | --- | ---: | --- | --- | --- |
| **MAIN** | `V40`（基线 `V01-13`） | `FTX-1_MAIN_V0113.SFL` | `3,243,706 B` | `MC` / `BFE2AB37` -> `3E9CE208` | `de02ce415b37ca6621ed0bac2f8e7bd63d45f3022a62868598950502ed033f5c` | `a66308b8efefb868899bf015d685ceedc46767e2866baee404ec85a3e5edb2f8` |
| **DISPLAY** | `V35`（基线 `V01-10`） | `FTX-1_DISPLAY_V0110.SFL` | `2,896,380 B` | `PC` / `D45D0922` -> `C43EE84B` | `962fda27ae2f0a0deedb039b868a545ef0f6736b686c266e19f231dbe3973bba` | `82bee0eb41937819ec03be5a7528c595365850dad9cdf0582c9df7473849be7c` |

- **解码后载荷哈希**：`MAIN` 解码 S-Record 文本 SHA-256 `66ae62ac...` -> `1b7bd915...`；`DISPLAY` 解码裸镜像 SHA-256 `ba4a2fb2...` -> `8e5f624d...`。
- **SFL 容器结构与校验**（`patch.py:8-35`、`site/patch-core.js:14-48`）：
  1. **576 字节（`0x240`）ASCII 头**：以 `********` 开头，尾行含 `\r\n(MC|PC) +([0-9]+) +([0-9A-F]{8})`（文件大小与 CRC-32 位于偏移 `0x220`）。
  2. **CRC-32 算法**：先对 `raw[576:]`（加密后载荷）计算标准 IEEE CRC-32，再追加 4 字节小端常量 `0x35C6938F`（大端字节流 `8f 93 c6 35`）继续计算最终 CRC-32。
  3. **43 字节加性混淆密钥**（`key_hex`）：
     `1e271b12111619172425291c0d0b060403010205070c0e0f181d20222a2b08090a101314151a1f21282326`
     解码：`decoded[i] = (raw[576 + i] - key[i % 43]) & 0xFF`；重打包：加回 `key[i % 43]`。

### 1.3 就地补丁规模与代码空间回收手段

由于**不扩展文件长度、不新增 S-Record 行（MAIN）、不突破 `0x2C2FBC` 载荷上界（DISPLAY）**，`sq9pd` 通过深度去重与紧凑重编译在原厂镜像内部腾挪出全部代码空间：

- **MAIN（Renesas RX651 / RXv2，扁平 ROM `0xFFE80000..0xFFFFFFFF`）**：
  - `site/patch-data.js` 含 **910 条 S-Record 文本差分（23,118 字节 ASCII）**，解码为扁平 ROM 后对应 **322 段连续二进制差分，共 10,573 变更字节**（区间 `0xFFE8BBF6..0xFFF842BF`，未触及 `0xFFF87DC2` 尾段）。
  - **去重回收手段**：原厂 `0xfff0c74d..0xfff10fda` 区域存在大量结构重复、单函数约 128 字节的菜单回调（`FUN_fff0a64a..FUN_fff107aa` 内部）。`sq9pd` 将 64+ 处同类回调统一收拢至参数化公共函数 `0xfff0c763`（另有共用菜单/按键辅助 `0xfff0d02e`、`0xfff0d0ae`、`0xfff0d12e`），在 `0xfff07378..0xfff10fe0` 主集群及 `0xffeb797f..0xffeb7c80`、`0xfff35cbd..0xfff35d90`、`0xfff6004b..0xfff60120`、`0xfff84248..0xfff842b8` 等零散空隙中**回收约 5 KiB** 空间，且末尾仍留有约 `535 B` 的 `0x03`（`nop`）空闲余量。
- **DISPLAY（Renesas RZ/A1H ARMv7-A，基址 `0x60400000`，大小 `0x2C2FBC` = `2,895,804 B`）**：
  - `site/patch-data.js` 含 **47 段载荷差分**（跨度 `4,117 B`，实际异于原厂字节数 `4,031 B`，覆盖 `0x6040AA38..0x604CEF90`）与 1 处文件头 CRC 差分（偏移 `544 / 0x220`）。
  - **Thumb-2 压缩重写手段**：将原厂冗余较大的 ARM32 函数用高密度 **Thumb-2** 重写——从 ARM32 调用点通过 `BLX` 切入 Thumb，或在原函数入口 `+0..+3` 保留 4 字节 ARM32 `b <原厂分支>` 跳板而在 `+4..` 放入 Thumb-2 新函数（例如重写 `0x60440c84` 腾出 `0x60441038..0x604410b0`，以及重用/重写 `0x60492bf4`、`0x604b0bac`、`0x604b5f98`、`0x604c5c70`、`0x604c826c`、`0x604c85c4`、`0x604c86a8`、`0x604cecbc`、`0x604cee8c..0x604cef90` 等函数）。

---

## 2. 从菜单分配自定义按钮的完整交互机制

`sq9pd` 实现了一套由 **MAIN 控制配置与按键路由、DISPLAY 负责本地化标签解析与视觉渲染** 的 4 页 × 5 槽（共 20 个可配置软键 + 第 0 槽固定 `PAGE` 键）自定义按钮框架。

### 2.1 `DISPLAY SETTINGS -> BUTTON SETUP` 菜单树与 20 槽位动态注册

原厂设置菜单共有 `520 × 60 B` 的动态菜单描述符表（`0x8233e8`），由各模块在初始化时调用 `0xfff06ca6` 注册。`sq9pd` 挂钩了显示设置注册尾部的调用：

```text
FUN_fff1a51b (显示设置菜单初始化)
  └─ 0xfff1abd3: bsr.a 0xfff0d9a2        [原厂为 bsr.a 0xfff27b7a]
       ├─ 1. bsr.a 0xfff27b7a            (补调原最后一项菜单注册)
       ├─ 2. bsr.a 0xfff0c863            (校验/恢复 RAM 0x8427..0x8442 中的 BTN1 配置)
       ├─ 3. bra.a 0xfff0facc
       │     ├─ bsr.a 0xfff0e670         (清零 SWR SCAN 运行态 RAM 0x84c4..0x8517, 84 B)
       │     └─ jmp   0xfff0d9b2         (20 槽位菜单循环注册)
       │
       └─ 0xfff0d9b2 (r6 = 0 .. 19):
            ├─ 复制 60 B 模板 0xfff108c0 ("PAGE 1-1             ", group=20/0x14, sub=3) 到栈
            ├─ 写页/槽号: [r0+11] = '1' + r6/5, [r0+13] = '1' + r6%5  → "PAGE 1-1" .. "PAGE 4-5"
            ├─ display_cb [r0+28] ← 0xfff0d8a2[r6] (20 个 6B 桩 → r2=0..19 → 0xfff0d02e)
            ├─ step_cb    [r0+32] ← 0xfff0d922[r6] (20 个 6B 桩 → r2=0..19 → 0xfff0d0ae)
            ├─ default    [r0+44] ← 0xfff1023b[r6] (默认功能索引 0..69)
            ├─ storage    [r0+48] ← 0x842b + r6    (对应 slot[r6] RAM 字节)
            └─ bsr.a 0xfff06ca6                    (注册进 0x8233e8 菜单表)
```

关键配套挂钩如下：

1. **子菜单标题（`0xfff06a7c -> bra.a 0xfff0dc20`）**：当菜单组号 `group == 20`（`DISPLAY SETTINGS`）且子组号 `subgroup == 3` 时，返回字符串 `"BUTTON SETUP "`（`0xfff102bb`）。
2. **显示回调入口表 `0xfff0d8a2`（20 个函数指针）**：分别指向 `0xfff0d4ab..0xfff0d4f3` 与 `0xfff0d6f8..0xfff0d740` 共 20 个桩函数，统一装载槽号 `r2 = 0..19` 后跳转 `0xfff0d02e` 进行合法性钳位并格式化值字符串。
3. **步进调节入口表 `0xfff0d922`（20 个函数指针）**：分别指向 `0xfff0d7a2..0xfff0d86a` 共 20 个桩函数，装载 `r2 = 0..19` 后跳转 `0xfff0d0ae -> 0xfff0d12e`，调用原厂步进辅助将槽位索引限制在 **`0..69`** 之间循环（上限 `69`、`cmp #70`），写入 `[0x842b + r2]`，重算校验和并置脏标志 `0x84c3 = 1`。

### 2.2 RAM 布局、EEPROM 持久化（`0x6FD6`）与脏检测落盘

原厂启动函数 `FUN_ffea46ee`（`0xffea4763`）在开机时从 EEPROM 偏移 `0` 读取 **`0x70D6`（`28,886`）字节** 到 RAM `0x1451..0x8526`；而原厂全量保存路径（`0xffea4779..0xffea4793`）仅从偏移 `273`（`0x111`）起写入 `0x6FC5` 字节（范围 `0x0111..0x70D5`）。`sq9pd` 精准利用该读取窗口末端原厂未使用的最后 **28 字节（`0x6FD6..0x6FF1`）** 存放自定义按钮配置：

| 地址（MAIN RAM） | EEPROM 偏移 | 长度 | 字段含义 | 检验 / 维护逻辑 |
| --- | --- | ---: | --- | --- |
| `0x8427..0x842A` | `0x6FD6..0x6FD9` | 4 B | 魔数 `magic` | 固定为小端 `0x314E5442`（ASCII `"BTN1"`） |
| `0x842B..0x843E` | `0x6FDA..0x6FED` | 20 B | `slots[20]` | 20 个槽位功能索引，每字节必须 `< 70`（`0..69`） |
| `0x843F..0x8442` | `0x6FEE..0x6FF1` | 4 B | `checksum` | `0x46545831 ("FTX1") + sum(slots[0..19])`（见 `0xfff0c7e3`） |
| `0x84A7..0x84C2` | —（纯 RAM） | 28 B | `shadow[28]` | 上次已读取/落盘的 28 B 镜像副本 |
| `0x84C3` | —（纯 RAM） | 1 B | `dirty_flag` | `1` 表示用户在 `BUTTON SETUP` 中修改过槽位，待异步写入 |

全生命周期持久化挂钩如下：

- **开机加载与校验（`0xffea476d -> bra.a 0xffeb7ac0`）**：先执行原厂 `0x70D6` 字节 EEPROM 读取（`0xffea4ced`），随后调用 `0xfff0e670` 清零 `0x84c4..0x8517`（确保上电不残留 SWR 状态）。菜单注册时调用 `0xfff0c863` 检查 `magic == "BTN1"`、调用 `0xfff0c7e3` 检查每项 `< 70` 且累加和等于 `[0x843f]`；若失败则跳转到 `0xfff0cb19` 载入 `0xfff1023b` 默认配置，成功则由 `0xfff0cb99` 同步至镜像 `0x84a7`。
- **恢复出厂 / 复位挂钩（`0xffea4774 -> bra.a 0xfff0f60f`、`0xffea4794 -> bra.a 0xffeb7a87`）**：先校验 `0xffef46f7() == 1`，再执行默认重置与原厂写入。
- **后台脏检测与最小化落盘（`0xffed2f31 -> bra.a 0xfff0cc19`）**：主状态/保存任务执行到 `0xffed2f31` 时转入 `0xfff0cc19` -> `0xfff0cc22`（执行原指令后调 `0xfff0cc99`）。当 `[0x84c3] == 1`、`[0x80130c + 24] == 8`（系统空闲）、`memcmp(0x8427, 0x84a7, 28) != 0` 且 `0xfff0c7e3` 返回 `r2 == 1` 时，更新 `[0x843f]` 并调用 `0xfff0cd19` -> `0xffea4d42(eeprom_off=0x6fd6, ram=0x8427, len=28)`，仅写这 28 字节并刷新镜像 `0x84a7`（`0xfff0cb99`），避免全片擦写损耗。

### 2.3 70 功能映射表与跨 MCU `"~B1:XX     "` 标签解析协议

`MAIN` 固件内部没有 `DISPLAY` 侧的按钮名称字符串表（原厂功能名仅存在于 `DISPLAY` 的指针数组 `0x607C1938`）。因此 `sq9pd` 设计了一套极简的跨 MCU 占位标签协议 `"~B1:XX     "`：

1. **MAIN 70 功能映射表（`0xfff0e62a`，70 字节）**：将菜单索引 `0..69` 映射为实际内部功能/按钮 ID：
   ```text
   [0..10]  :  0,   1,   2,   3,   4,   5,  72,  66,  69,  54,  68
   [11..24] :  8,   9, 130,  43,  73,  74,  65,  45,  14,   7,  10,  71,  11,  12
   [25..36] : 15,  16,  17,  18,  19,  20,  75,  76,  22,  24,  23, 127
   [37..51] :108,  98,  99, 109, 110,  94, 101, 102, 131, 132, 128, 104, 103, 105, 106
   [52..58] :136, 129,  85,  93,  89,  90,  83
   [59..69] :224(0xE0)..232(0xE8), 100(0x64 SCAN), 233(0xE9 SWR SCAN)
   ```
   （注：20 槽位默认索引表 `0xfff1023b` 为 `[19, 20, 21, 12, 15, 16, 0, 14, 13, 17, 52, 43, 44, 45, 46, 53, 54, 55, 56, 57]`，查表后对应 `README.md` 的 4×5 默认布局：`[14(RF POWER), 7(MIC GAIN), 10(AMC LEVEL), 9(PROC LEVEL), 73(NB)]` / `[74(DNR), 0(D-LEVEL), 43(TUNER), 130(ANT TUNE), 65(ANT)]` / `[136(APRS), 101(APRS S.LIST), 102(APRS M.LIST), 131(APRS BEACON), 132(APRS BCN-TX)]` / `[129(D-MODE), 85(MULTI), 93(SCOPE), 89(SPAN), 90(SPEED)]`。另 `0xfff101bb` 处存有一份对应的辅助表。）

2. **MAIN 菜单值格式化（`0xfff0d02e -> 0xfff0d285`）**：
   `0xfff0d285` 先用 `sstr.b` 将 21 字节目标缓冲区填充为空格 `' '`（`0x20`），再向首 4 字节写入 `0x3a31427e`（`"~B1:"`），随后读取 `id = *(u8*)(0xfff0e62a + slot_val)` 并通过 `0xfff0d06c` 将高低半字节格式化为两位大写十六进制 ASCII 写入偏移 `+4..+5`（形成 `"~B1:XX               "`，经菜单值列截断为 11 字节 `"~B1:XX     "` 随 `0x40` 帧发往 DISPLAY）。

3. **DISPLAY 菜单标签拦截与解析（`0x604b3324` 等）**：
   `DISPLAY` 在 4 处原厂菜单值绘制点（`0x6042f124`、`0x6042f1e8`、`0x60430580`、`0x6043065c`）将 `bl 0x604bdc20` 改挂为 `blx 0x604b3324`（Thumb-2）：

```text
MENU 绘制点 (0x6042f124 / 0x6042f1e8 / 0x60430580 / 0x6043065c)
  └─ blx 0x604b3324 (Thumb-2)
       ├─ 先调用原厂 0x604bdc20
       ├─ 检查 r2 == 11 (0xb) 且 *(u32*)str == 0x3a31427e ("~B1:")，不符则退出
       └─ b.w 0x60499d6c (循环 r6 = 4..5 解析 2 位大写 Hex → r4 = id)
            └─ b.w 0x604c04c0
                 ├─ 校验 str[6..10] 全为 ' ' (0x20)
                 ├─ 校验 id <= 0xbc || (0xe0 <= id <= 0xe9)  [0x604c04d6: cmp r3, #9]
                 └─ b.w 0x60424644
                      ├─ r0 = 0x607c1938; bl 0x6041f3a4 → b.w 0x6040aa3c
                      │    ├─ id == 0xE9      → "SWR SCAN" (0x604cef54)
                      │    ├─ id in 0xEA..0xED → 0x6040aa64 表 ("BW", "START", "STOP", "EXIT")
                      │    ├─ id in 0xE0..0xE8 → 0x6041f3cc 表 (实测逆向:
                      │    │     FIL WIDTH / FIL SHIFT / NOTCH / NTCH FREQ /
                      │    │     NTCH WIDTH / CONTOUR / NB REJECT / NB WIDTH / AMC REL)
                      │    └─ 其余 id         → 回退原厂 [0x607C1938 + id*4]
                      └─ 将解析到的 C 字符串拷贝回 dst[0..10] 并以空格 ' ' 补齐至 11 字节
```

### 2.4 底部软键栏运行时渲染与按键分发

在主屏运行时，底部共有 6 个软键槽位（`slot 0..5`）：

1. **槽位到功能 ID 解析（`0xfff0cfae -> bra.a 0xfff0fe5d`，挂钩于 `0xffee4e72` 与 `0xfff004eb`）**：
   - 若 `[0x84c6] != 0`（SWR SCAN 窗口已打开）：直接查表 `0xfff0fe84` 返回固定软键条 `[234(0xEA BW), 255(空), 235(0xEB START), 236(0xEC STOP), 255(空), 237(0xED EXIT)]`。
   - 若 `[0x84c6] == 0`：槽 `0` 固定返回 `63`（`0x3F = "PAGE"`）；槽 `1..5` 读取当前页号 `page = [0x4b94]`（`0..3`），查 `0xfff0e62a[slots[page*5 + slot - 1]]` 返回实际 ID。
   - `0xfff0ce19`（挂钩于 `0xffee4e46`）将 6 字节现行 ID 缓存到 `0x1b8dd[0..5]`，原厂 `FUN_ffee4e46` 随后将其复制到 `0x5259`（`0x1451 + 15880`）。
2. **`PAGE` 按钮（`0x3F`）**：
   `0xffe96cd4` 将原按钮表项 `0x54` 改为 `0x3F`（`63`），对应回调指向 `0xfff00db6`：在按钮按下（`r1 == 0`）时轮转 `0x4b94 = (0x4b94 + 1) & 3`（同步写入 `0x525a`），并调用 `0xffea65fd(1)` 请求重绘界面。
3. **`FUN_fff003f0` 软键 UI 构建与点击分发链**：
   `0xfff004a8..0xfff016e8` 一系列挂钩将 6 格渲染/状态/事件导流至重构后的辅助函数：
   - **描述符解析**：`0xfff0c816..0xfff0c82b` -> `0xfff0ce40`（并处理 `0xE9` 在 `0xfff0fa81` 的 12 字节表项 -> `0xfff0f5ca` 打开 SWR 窗口）。
   - **状态文本与置灰检查**：`0xfff0e126` / `0xfff00ab5` / `0xfff0c810`（状态数值格式化）、`0xfff0e0b8`（上下文禁用判定）、`0xffed8cd1`（`FUN_ffed7a49` bit 7 置灰掩码调 `0xfff004f3`）。
   - **点击事件分发**：`0xfff00dd0 -> bra.a 0xfff0e1b8`（分流调节项至 `0xfff0116e` / `0xfff01621`）与 `0xfff0f1bf`（分发 `0xE9` -> `0xfff0f6ca` 启动/管理、`0x64` -> `0xfff0eca8` 原厂 SCAN、`0xEA..0xED` -> `0xfff0febb` SWR 软键、`0xE0..0xE8` -> `0xfff0e2ad` 绑定至 `FUNC` 旋钮快捷调节）。
4. **DISPLAY 底部软键标签渲染（`0x6043e280` 与 `0x6043e4c8`）**：
   `0x6043e280` 将原标签查询替换为 `blx 0x6041f3a4`（复用 `0x6040aa3c` 解析 `0xE0..0xED`）；`0x6043e4c8 -> blx 0x6043e4cc` 剥离首尾空格（`0x20`）、转为 UTF-16LE（`strh`），并按实际字符长度 `< 10`（`cmp r4, #0xa`）动态选择标准字体（`0x6043e5b8`）或紧凑字体（`0x6043e590`）。

---

## 3. SWR 扫描（SWR SCAN）完整实现机制

### 3.1 入口控制与 4 档扫描带宽

用户按压绑定为 `0xE9`（`SWR SCAN`）的自定义按钮后，触发 `0xfff0fa81 -> 0xfff0f5ca -> 0xfff0d076 -> 0xfff0f5de`：校验前置视图条件（`0xfff0f556`），置 `0x84c6 = 1`（`window_open`）、`0x84c7 = 0`（默认 `50 kHz` 档），关闭冲突弹层并刷新底栏为 `[BW(0xEA), 空(0xFF), START(0xEB), STOP(0xEC), 空(0xFF), EXIT(0xED)]`。此时并不发射射频，用户可通过主 VFO 旋钮设定中心频率，并通过 `BW` 在 4 档间切换（共 101 个采样点，步进 `BW / 100`，存放在 `0xfff10acd` 的 `uint16_t[4]` 表）：

| `bw_idx`（`0x84c7`） | 扫描总带宽 | 相对中心偏移 | 步进（`0xfff10acd`） | 点数 |
| ---: | --- | --- | ---: | ---: |
| `0` | `50 kHz` | `-25 ... +25 kHz` | `500 Hz` | 101 |
| `1` | `100 kHz` | `-50 ... +50 kHz` | `1,000 Hz` | 101 |
| `2` | `500 kHz` | `-250 ... +250 kHz` | `5,000 Hz` | 101 |
| `3` | `1 MHz` | `-500 ... +500 kHz` | `10,000 Hz` | 101 |

### 3.2 RAM 状态块（`0x84c4..0x8517`）、前置检查与全频段合法性校验

`0xfff0e670` 在启动及复位路径将 `0x84c4..0x8517` 共 **84 字节**清零，扫描主状态结构以 `r6 = 0x84c8` 为基址：

| 地址 / 偏移 | 类型 | 字段含义 |
| --- | --- | --- |
| `0x84C6` / `[r6-2]` | `u8` | `window_open`（`0`=关闭，`1`=SWR 扫描界面打开） |
| `0x84C7` / `[r6-1]` | `u8` | `bw_idx`（`0..3`） |
| `0x84C8` / `[r6+0]` | `u32` | `tick`（由 ISR `0xfff0cc47` 每拍自增） |
| `0x84D0` / `[r6+8]` | `u32` | `saved_freq`（扫描前中心频率，结束后恢复） |
| `0x84D4` / `[r6+12]` | `u32` | `cur_freq`（当前扫描点目标频率） |
| `0x84D8` / `[r6+16]` | `u32` | `step_hz`（`500 / 1000 / 5000 / 10000`） |
| `0x84DC` / `[r6+20]` | `u8` | `state`（`0=IDLE`，`1=RUNNING`，`2=STOPPING/DONE`，同时非零屏蔽用户输入） |
| `0x84DD` / `[r6+21]` | `u8` | `vfo_side`（当前活动 VFO 侧 `0/1`） |
| `0x84DE` / `[r6+22]` | `u8` | `point`（当前采样点索引 `0..100`） |
| `0x84DF` / `[r6+23]` | `u8` | `pending_close`（扫描过程中按 EXIT/BACK 时置 `1`，退回 RX 后关窗） |
| `0x84E0` / `[r6+24]` | `u8` | `freq_modified`（`1` 表示已改频，收尾时需恢复 `saved_freq`） |
| `0x84E1` / `[r6+25]` | `u8` | `seq`（会话/样本序列令牌 `1..255`，用于帧同步与回执比对） |
| `0x84E2` / `[r6+26]` | `u8` | `swr_val`（读取到的原始 SWR 表值） |
| `0x84E3` / `[r6+27]` | `u8` | `flags`（bit 0/1 有效样本标志 `0x83`，bit 2=`0x04` 错误标志，bit 7=`0x80`） |
| `0x84E8` / `[r6+32]` | `u16` | `tx_req_ok`（`0x0101`/`257` 表示已持有扫描 TX 租约，同步作发射互锁校验） |
| `0x84EA` / `[r6+34]` | `u8` | `tx_active`（`1` 表示扫描正在发射，`0xfff0cc47` 仍继续跑表） |
| `0x84EC..84ED` / `[r6+36..37]` | `u8[2]` | 保存的原工作模式与发射功率（扫描期间临时切为 AM、`1 W` Field / `5 W` SPA-1） |
| `0x84EE` / `[r6+38]` | `u8` | `error_code`（`0`=正常，非零映射至 `ERRx`） |
| `0x84F0` / `[r6+40]` | `u32` | `session_deadline`（`tick + 0x927c0` = `+600,000`，即 60 s 总超时） |
| `0x84F4` / `[r6+44]` | `u32` | `step_deadline`（`tick + 0x1388` = `+5,000`，单点/ACK 500 ms 超时） |
| `0x8504` / `[r6+60]` | `u8` | `substate`（`0=TUNE`, `1=WAIT_TX_CMD`, `2=WAIT_RF_SETTLE`, `3=WAIT_DISPLAY_ACK`） |
| `0x8505` / `[r6+61]` | `u8` | `ack_flags`（bit 1=`0x02` 表示 DISPLAY 已接收并渲染当前点） |
| `0x8506..8507` / `[r6+62..63]` | `u8[2]` | `ack_seq` / `ack_point`（DISPLAY `0xE9` 回传的令牌与点号） |
| `0x8508` / `[r6+64]` | `u32` | `tx_start_tick`（ISR 非停止态发射看门狗上限 `0x1388`） |

按下 `START` 进入 `0xfff84248`：
1. 检查 `state == 0 && window_open == 1`，调用 `0xfff10967`（要求 `[0x801324] == 8` 普通 RX、`[0x822d62] == 0` 且无 PTT）、`0xfff1b29b == 0`（无 SPLIT/发射禁止）、`0xffee510c == 1`（单 VFO DISP 且 TUNER OFF）、`0xfff35c9a == 1`（起点与 100 步终点无 32 位地址溢出）、`0xfff1b25d == 1`。
2. `0xfff35d26` 清零错误并设定 `40[r6] = tick + 0x927c0`、`44[r6] = tick + 0x1388`、`64[r6] = tick`。
3. `0xfff09c13` 检查机头/功放条件，随后 **`0xfff35d68` 对全扫频 101 个频点逐一调用原厂发射允许检查 `0xffec7edc(freq)`**；只要有任意一点不在允许发射频段内，立即设 `38[r6] = 6`（`ERR6`）、`27[r6] = 4`、`state = 2` 并退出，绝不在段外发射。
4. 全部通过后进入 `0xfff0d2be`：保存模式/功率/频率、调用 `0xffeb79a3` 申请 TX，并调用 `0xfff35cbd` 切至第 `0` 点起扫频率、置 `substate = 0`。

### 3.3 4 子状态闭环状态机、双层安全看门狗与互斥锁定

`sq9pd` 在 **定时器中断** 与 **主循环** 两侧同时挂载看门狗，保证任何通信丢失或状态偏离都会立刻撤掉发射：

```text
定时器 ISR (0xffea1e41 → bsr.a 0xfff0cc47)
  ├─ 先调用原厂 0xffea5030
  ├─ 若 window_open == 1 || tx_active == 1:
  │    ├─ tick (0x84c8) ++
  │    └─ bsr.a 0xfff0a4ef (ISR 看门狗)
  │         ├─ 校验 tx_active==1 && window_open==1 && error_code==0
  │         ├─ 检查 tick >= session_deadline (40[r6]) 或 tick >= step_deadline (44[r6])
  │         ├─ 检查 !(state & 2) 时 (tick - tx_start_tick) >= 0x1388
  │         └─ 任一超时/异常 → 0xfff35d47 → 0xffeb7b3c 写诊断 error_code
  │                            → 强制 state=2, flags=4, 0xffec08df(0) 立即停发!

主循环服务 (0xffea12a7 → bsr.a 0xfff0d4fb → 0xfff09c71)
  └─ 若 state == 1 && window_open == 1 && error == 0 → 0xfff07378 状态机:
       ├─ 校验 [0x50f4] == 35[r6] 且 [0x801328] == cur_freq (12[r6])
       ├─ substate 0 (TUNE, 0xfff6004b):   确认调谐稳定 → 0xfff35d03 → 0xfff081b1(1) 开 TX → substate=1
       ├─ substate 1 (WAIT_TX_CMD, 0xfff10aa8): 0xfff09cac 验证 [0x801324]==3, [0x822d62]==1, [0x8c02b] bit3 → substate=2
       ├─ substate 2 (WAIT_RF_SETTLE, 0xffeff3a5): Field 等 16 次更新 / SPA-1 等 >=3 帧且 >=80 ms (0xfff032b3, [0x33927]!=0)
       │                                           读取 SWR → 26[r6], 27[r6]=0x83, 61[r6]=0 → substate=3 (失败写 error_code=3 "ERR3")
       └─ substate 3 (WAIT_DISPLAY_ACK, 0xffeb7aad): 等待 ack_flags (61[r6]) & 2 == 2
                                                      → 0xfff0896f: 若 point < 100 则 point++, cur_freq += step_hz → 0xfff35cbd (substate=0)
                                                      → 若 point == 100 则 state=2, 停 TX → 0xfff0a53f 收尾
```

- **收尾与撤发安全逻辑（`0xfff0a53f`）**：必须等待 `0xfff0ead5`、`0xfff10967`（确认回到 RX）与 `0xfff03277` 均通过后，才调用 `0xffeb7c19` 恢复原中心频率（`saved_freq`）并将 `state` 置回 `0`；若曾设置 `pending_close (23[r6])`，则清 `0x84c6 = 0` 并调用 `0xffee4e46` 还原原厂自定义底栏。
- **错误码映射（`0xffeb7b3c` 与 DISPLAY `0x604ced48`）**：DISPLAY 固定构造 `"ERR"` 后将 `[r5, #0xa] + 0x30` 作为第 4 个字符显示：

| `error_code`（十进制 / 十六进制） | `code + 0x30` | 显示错误码 | 触发来源（依反汇编及 `README.md`） |
| --- | --- | --- | --- |
| `2` (`0x02`) | `'2'` | `ERR2` | 运行条件改变、TX 状态/请求冲突（`0xfff073be` 分支 `0xffeb7a2e`） |
| `3` (`0x03`) | `'3'` | `ERR3` | `0xffeff3a5` 未取得有效功率/SWR 读数 |
| `6` (`0x06`) | `'6'` | `ERR6` | `0xfff842a6` 101 点边界/启动条件/功放检查失败 |
| `17` / `24` (`0x11` / `0x18`) | `'A'` / `'H'` | `ERRA` / `ERRH` | `0xffeb7be0` / `0xffeb7bef`：DISPLAY 点确认超时 / DISPLAY 未就绪 |
| `32` (`0x20`) | `'P'` | `ERRP` | `0xffeb7bdb`：`substate 2` 有效测量刷新超时 |
| `35` (`0x23`) | `'S'` | `ERRS` | `0xffeb7bc2`：总会话 `60 s`（`0x927c0`）超时 |
| `40` (`0x28`) | `'X'` | `ERRX` | `0xffeb7bcc`：退回 RX 与恢复设置未在期限内完成 |

- **面板 / 触摸 / CAT 互斥锁定**：扫描打开期间，MAIN 通过 `0xfff0f250`、`0xfff0ecd1`、`0xfff0f1e1`、`0xfff3f082 -> 0xffeff3df`（CAT 仅允许读状态/频率/表头与 `TX0`，封锁改频/改模式/`TX1`）及 `0xffeb7c0f` 阻断无关动作；DISPLAY 通过 `0x6041464c -> b 0x604b5ffc` 在扫描中丢弃 6 字节 `E1 00` 拨盘帧，并通过 `0x60442160 -> 0x60440fa0`、`0x6044263c -> 0x6047fdd4`、`0x60443754 -> 0x604cef14` 屏蔽无关触摸与菜单跳转。

### 3.4 MAIN ↔ DISPLAY 闭环同步与曲线绘图协议

`sq9pd` 巧妙借用原厂底栏第 4 槽（`0x1b91d = 0x1b8e3 + 4*14 + 2`，SWR 窗口打开时强制设为 `0xFF` 空槽）的 12 字节描述符区域传递实时测量帧，无需向原厂串口调度表插入新指令号：

1. **MAIN -> DISPLAY 状态帧（`0xfff35ce0 -> 0xfff0ff3b`）**：
   当 `id == 0xFF && [0x84c6] == 1 && out_buf == 0x1b91d` 时，`0xfff0ff3b` 覆盖输出缓冲区（映射至 DISPLAY 的 `UI[0x5E..0x69]`）：
   - `+0..+1`：`0x0353`（魔数头 `0x53, 0x03`）
   - `+2`：`state`（`0x84dc`）
   - `+3`：`point`（`0..100`）
   - `+4..+8`：由 `0xfff0ce68 -> 0xffee48a7` 写入中心频率 BCD（5 字节）
   - `+9`：`seq`（`25[r6]`）
   - `+10`：`error_code != 0 ? error_code : swr_val`
   - `+11`：`error_code != 0 ? 4 : flags`（`flags` bit 2=`0x04` 指示错误，bit 0/1 指示有效样本）
2. **DISPLAY 曲线缓存与绘制**：
   - `0x604c85c4`（挂钩于 `0x60442ABC`）在 SWR 打开且 `UI[0x5E..0x60] == {0xFF, 'S', 3}` 时，通过 `0x604b7f7c`（使用 `svc #0` 临界区包裹原厂 `0x6047d9fc`）分配 **`0x70`（112）字节** 缓存区（含 `101 B` Y 坐标数组 `[0..100]`、中心频率与带宽字段及去重追踪 `[+0x6b..+0x6d]`），并将指针连同 `0xFF, 0xA7` 魔数/XOR 校验存于 `UI[0x34..0x3F]`（`0x604c8718`）。
   - `0x604c86a8` 将原始 `swr_val` 经 `0xcccd >> 16` 定点缩放写入 `buf[point]`（无效样本写入 `0xFF`）。
   - `0x604cecbc`（经 `0x60443AE8 -> 0x604b0bac` 触发）绘制 `x=0..800, y=216..420` 区域背景、Y 轴刻度 `"INF / 5 / 3 / 2 / 1.5 / 1"`（`0x604c826c`）、6 条网格线、右上角 `"SWR"` 或 `"ERRx"` 状态字样、中心频率（`0x6041db0c`）与 `-/+` 半跨度（`0x6041df40` / `0x60492d40`）、Bresenham 折线（`0x604c5c70` + `0x604b5f98`）及扫描游标（`0x60466cd4`）。
3. **DISPLAY -> MAIN 点确认握手（`0x6048f114 -> 0x604cee8c`）**：
   渲染/入队后，`0x604cee8c` 通过串口发送 **6 字节回执帧**：
   `[0xE9, 0x53 ('S'), seq, point, ack_bits, xor_checksum]`
   其中 `ack_bits` 综合了缓存有效标志（bit 0=`1`）与原帧 flags bit 1（`& 2`）。MAIN 侧串口分发 `0xffea2679 -> bra.a 0xffeb7ada` 识别 `0xE9` 后经 `0xffebfe65`（`0xffeb7b28 -> 0xfff0e4de -> 0xfff0cb45`）校核 XOR 与 `seq`/`point`，置位 `ack_flags (61[r6])` 驱动 `substate 3` 推进至下一点。

---

## 4. 对 `rev_ftx1` 项目的集成指导与兼容性结论

对照 `rev_ftx1` 当前代码基线（参见 [analysis.md](analysis.md) 与 [patch/README.md](../patch/README.md) 中的 `patch/build_ft8_main.py`、`patch/build_ft8_menu.py`、`patch/build_cw.py` 及工作区未跟踪原型 `patch/build_softkey_main.py`），逐项核查得如下集成结论与接口设计：

### 4.1 挂钩与资源冲突审计结论

- **DISPLAY（`build_ft8_menu.py` 13 个活跃挂钩 + Stage 1/2 + `P1..P5` + 43 个 `STOCK()` 调用）**：与 `sq9pd` 的 47 段补丁 **0 字节冲突**。`UI[]` 偏移亦完全正交（`sq9pd` 占用 `0x34..0x3F`、`0x5E..0x69`、`0x6C`；`rev_ftx1` 仅读 `0`、`0x1F`、`0xA4`、`0x13B`、`0x13C`）。`sq9pd` 的 `malloc(0x70)` 仅在 SWR 窗口打开时动态申请并在退出时释放，与 `ft8_radio_heap_hook`（`0x07C448`，提供 `0xE0000` 主堆）无竞争。
- **MAIN `softkey_main`（工作区未跟踪原型）**：与 `sq9pd` 在 `0xFFF1ABD3`、`0xFFEE4E46`、`0xFFEE4E72`、`0xFFF01906` **4 处直接冲突**。由于 `sq9pd` 的 `BUTTON SETUP` 功能更完备且已解决 EEPROM 持久化与跨 MCU 标签协议，应放弃合并 `softkey_main`，将整个 **`C2` 死代码洞（`0xFFF68BA0..0xFFF69165`，1,477 B）** 回收给 R2/R4。
- **MAIN `ft8_main` 唯一代码冲突点（`0xFFEA1E41` ISR 定时器挂钩）**：
  - 原厂 `0xFFEA1E41` 为 `05 ef 31 00`（`bsr.a 0xffea5030`）。`ft8_main_timer` 与 `sq9pd 0xfff0cc47` 均挂钩此处。
  - **推荐链式接法**：保持 `0xFFEA1E41` 为 `sq9pd` 的 `bsr.a 0xfff0cc47`，将 `0xfff0cc47` 开头原本调用原厂滴答的 4 字节 `bsr.a 0xffea5030` 改挂为 **`bsr.a _ft8_main_timer`**。由于中断入口 `0xFFEA1E3D` 仅压栈 `r1-r5, r14-r15`，让遵循 RX C ABI（自动保护 `r6-r13`）的 `_ft8_main_timer` 先执行并调用 `0xffea5030`，再返回 `0xfff0cc4b` 继续跑 SWR 滴答与 `0xfff0a4ef` 看门狗，可兼顾两边计时且绝对保证寄存器安全。

### 4.2 R2 / R3 / R4 集成方案与字节预算

1. **`BUTTON SETUP` 扩展（`70 -> 72` 项，R2）**：
   - 分配新按钮 ID：**`0xEE` = `FT8`**（槽位索引 `70`）、**`0xEF` = `CW_DEC`**（槽位索引 `71`）。
   - **MAIN（放入 `C2`）**：复制 70 字节表 `0xFFF0E62A` 并追加 `0xEE, 0xEF` 成 72 字节表，更新 `0xFFF0CFF5` 与 `0xFFF0D297` 两处表基址指针，并将 4 处边界常量由 `70/69` 改为 `72/71`（`0xFFF0C7F6`、`0xFFF0CFEE`、`0xFFF0D03E`、`0xFFF0D0B7`）；在 `0xFFF0E126`/`0xFFF0E0B8`/`0xFFF0F1BF`（或 `0xFFF0C816`）中允许 `0xEE`/`0xEF` 启用并响应按下事件（`arg == 0`，且仅在 `[0x84c6] == 0` 时有效）。保留原 20 槽默认值与 `"BTN1"`/`"FTX1"` 校验算法，100% 兼容现有 `sq9pd` EEPROM。
   - **DISPLAY**：将 `0x604C04D6`（`~B1:` 白名单范围）由 `cmp r3, #9` 改为 **`cmp r3, #15`**（`09 2b -> 0f 2b`，接受 `0xE0..0xEF`），并在 `0x6040AA3C` 增加 `0xEE -> "FT8"`、`0xEF -> "CW_DEC"` 分支。
2. **`MAIN -> DISPLAY` 触发信令（`0x20` 帧字节 `34`，R2）**：
   - 借用周期性 `0x20` 状态帧未用字节 `34`（RAM `0x1B49E`，`ft8_main_status_hook` 已在 `0xFFEE3FD6` 挂钩该帧，无串口发送队列丢包风险）。
   - **边沿触发编码**：`0` = 无事件；按下 `0xEE`/`0xEF` 时由 MAIN 递增 6 位序号 `seq = (seq % 63) + 1` 并写入 `(target << 6) | seq`（`target=1` 为 `FT8`，`2` 为 `CW_DEC`）。`DISPLAY` 在 `ft8_radio_report_packet`（`0x0C9D00`）读取 `cmd = packet[34]`、清零并从帧尾 `packet[len-1]` 精确减除 `cmd` 还原校验和后交给原厂 `0x604C965C`；首包仅初始化 `last_seq` 不触发，后续仅当 `seq != 0 && seq != last_seq` 时投递翻转事件。
3. **移除旧入口（R3）与空间预算（R4 可行性结论）**：
   - 移除 `0x03C51C`（`ft8_mode_draw` / `cw_mode_draw`）、`0x0C6BD8`（`ft8_hit`）、`MODE` 弹窗上的 `"CUSTM"`/`"FT8"`/`"CW_DEC"` 框体与 `EVENT_CUSTOM (0x1136)` / `EVENT_FT8 (0x1133)` / `EVENT_CW (0x1137)` / `EVENT_DISMISS (0x1139)` 路由（保留 `0x038868` `func_menu_tile` Stage 1 修复）。
   - 空间核算表明 **R2 + R3 + R4 完全可行**：`MAIN` `C2` 回收后有 **1,477 B**（新增逻辑仅需约 `150–250 B`，`C4` 尚有 `4,235 B` 备用）；`DISPLAY` Stage 2 原余 `92 B`，叠加 R3 移除 `CUSTM` UI 后净空出 **~1,100–1,300 B**（仅需约 `150–250 B` 实现边沿触发与互斥），无需触动生产版 `P1..P5` 或超限扩尾。
4. **三方互斥与实机边界**：
   - `FT8` 与 `CW_DEC` 共享 `0x603D0880` 低内存音频工作区：开启任一方前必须先彻底停止另一方（`cw_stop()` 或 `ft8 requested = 0`）。
   - 与 `SWR SCAN` 互斥：`MAIN` `ft8_main` 的 `key()` 须新增 `[0x84c6] == 0` 门控防止发射冲突；`DISPLAY` 在 `UI[0x6C] == 0xED`（SWR 窗口打开）时屏蔽 `0x20[34]` 触发，且 `cw_panel.c` 的 `scope_visible()` 需检测 `UI[0x6C] != 0xED` 防止 `y=378..420` 译码框覆盖 SWR 波形图。
   - **已知待实机验证边界**：`rev_ftx1` 先前因未定位 MAIN 测表来源（`0x20[29]` 恒零）而移除 SWR，而 `sq9pd` 在真实扫描中通过 `0xfff032b3` 与 `[0x33927]` 读取原厂 SWR 源并在 `TEST_RESULTS.json` 报告工作正常；该部分涉及 `MAIN` 射频发射与功放/SPA-1 硬件时序，合并后需在实机配合假负载核对 `ERR3`/`ERRP` 门限与扫频安全性。
