# 交接(6-handoff.md)

只引用既有产物,不复制内容:

- 需求与决策:`docs/ai-workflow/ft8-tx/1-brainstorm.md`、`2-spec.md`
- 切片与完成判据:`3-plan.md`(四片全部完成,证据见 `4-verify-report.md`)
- 使用与实机清单:`patch/README.md`
- 发布与回滚:`5-release-plan.md`

## 本次范围外的已知缺口(按优先级)

1. **实机 bring-up 全部未做**(E8 语境、音频路由/handle、SD 三原语实测、
   worker tick 节拍、尾区加载)——见 README 清单。fread 原语定位后补
   已通联集合的跨会话载入。
2. RF 频率镜像 RE(ADIF BAND/FREQ 自动化):线索 = 0x20-0x33 命令应用函数
   (0xc8000-0xcd800 区域)xref 到 0x60935bb4 的写入偏移。
3. 自动应答序列、SNR 估计报告、呼号/文本持久化、按频段已通联区分:spec Out of Scope。
4. spec 偏差记录:手动 [LOG] 按钮因页面空间未实现(自动启发式覆盖标准流程;
   自由文本通联的补记入口留待下次布局迭代)。

## 关键地址速查(本次新增)

```
0x60427a8c  E8 PTT on/off(mode 1/0)       0x6046b5f0  音频块提交(800采样2ch)
0x6046995c  fopen(path, mode)             0x6046b51c  fwrite(buf,size,n,FILE)
0x60476694  fclose(FILE)                  0x60408237  "a" 模式串
0x604135d4  RTC 读(7B BCD)               尾部 ft8_arm_api v5 @0x606c2fc0
空洞 ft8_live_api v5 @0x6052c670(10,970B 内现用 9,928B)
```

## 验证后补充的缺口(4-verify-report.md 详述)

- watch_73(RRR 后收到 73 记录)路径无集成测试——需伪造解码产物注入,待 fread/注入手段就绪后补。
- decode_sfl `extract_continuous` 会剥密文尾部 0x0D/0x0A(概率性丢字节);merge_display
  已用补零重封绕开,根治需改 decode_sfl 按声明长度截取。

## 反复出现的教训(候选回流到规范)

- zig cc 隐式 `--gc-sections` + 链接脚本 `KEEP(*(.text*))` 会把整库 compiler_rt
  吸进定长空洞——用钩子根表(`.ft8_hooks`)替代 KEEP,并显式传 `--gc-sections`。
- 原厂 fill(0x625a0) 对 color==0 走 `FUN_00062504` 特殊路径(DMA 语境),模拟器里
  会破坏状态——清屏用本地循环。
- freestanding 目标(空洞)与 musl 目标(尾部)能力不同:空洞侧不能 `#include <string.h>`。
- 事件"release 时生效"的设计必须让分发函数对 pressed==0 也转发(原 ft8_local_touch 只看 press)。
