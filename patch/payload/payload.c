// payload.c — FT8 Stage1 胶水模块(骨架)
// 无源码打包: 本模块是我们唯一的自有源码, 通过 stock_api.h 以绝对地址调用原厂函数。
// 编译: ARMv7-A ARM 模式, freestanding, 链接到 Stage1 空洞 0x6052C66C。
// 挂钩: 由外部周期调用方(原厂任务循环中改写的 BL, 见 merge_display.py 的 hooks 表)
//       或 M1 后续选定的钩子调用 ft8_tick()。
#include "stock_api.h"

// ---- Stage2 数据区(镜像尾, NOLOAD; 由 ft8_init 首次清零) ----
#define S2 ((volatile u32 *)STAGE2_RUN)

static u32 s_ticks;
static u32 s_frames_seen;
static u32 s_init_done;

void *memset(void *d, int c, unsigned long n) {
    u8 *p = (u8 *)d;
    while (n--) *p++ = (u8)c;
    return d;
}

// 周期入口(挂钩方以 ~10ms 级节拍调用)
void ft8_tick(void) {
    if (!s_init_done) {
        memset((void *)STAGE2_RUN, 0, 0x40);
        S2[0] = 0x46543821u; // "FT8!" 上电签名(验证 Stage2 可写)
        s_init_done = 1;
    }
    s_ticks++;

    // M1 骨架: 非录音态时轮询音频帧并立即归还(只计数, 证明数据面连通)
    if (AUDCTX_STATE != 2 && AUDCTX_STATE != 4) {
        for (int i = 0; i < 4; ++i) {
            void *frame = P_audio_poll();
            if (!frame) break;
            s_frames_seen++;
            // 真实 M1: P_cache_invalidate(frame, 8000); ft8_feed(frame);
            P_audio_release(1);
        }
    }
    S2[1] = s_ticks;
    S2[2] = s_frames_seen;
    S2[3] = AUDCTX_STATE;
}

// M2 预留: PTT 键控(报文与发送入口已验证)
void ft8_ptt(u8 on) {
    static const u8 msg[9] = {0xE8, 1, 0, 0, 0, 1, 0, 0, 0};
    u8 m[9];
    memset(m, 0, 9);
    for (int i = 0; i < 9; ++i) m[i] = msg[i];
    m[5] = on ? 1 : 0;
    P_proto_send(m, 9);
}
