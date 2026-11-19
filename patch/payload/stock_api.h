// stock_api.h — FTX-1 DISPLAY V01-10 原厂固件 API 声明(逆向所得,运行时地址)
// 运行时地址 = 0x60400000 + 文件偏移(display.bin)
// 仅声明,不含实现 — 链接时以绝对地址引用
#ifndef STOCK_API_H
#define STOCK_API_H

typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;
typedef int s32;
typedef short s16;

#define STOCK_BASE 0x60400000u
#define STOCK(fn_off) ((u32)(STOCK_BASE) + (u32)(fn_off))

// ---- 原厂函数(函数指针包装) --------------------------------------------
// 协议发送: 把 msg(含命令字节)组帧后经 SCIF5 发给 MAIN, len 为字节数
// 0xE8 语音TX: {0xE8,1,0,0,0,mode,0,0,0} mode: 0=off 1=voice TX 2=record
typedef s32 (*proto_send_fn)(const void *msg, u32 len);
#define P_proto_send ((proto_send_fn)STOCK(0x14a1c))

// 音频帧轮询: 非阻塞取一帧(8000B, 2ch*2000*16bit @16kHz), 无帧返回 0
typedef void *(*audio_poll_fn)(void);
#define P_audio_poll ((audio_poll_fn)STOCK(0x88c8))

// 音频帧归还(引用计数减一, 必须与 poll 配对)
typedef void *(*audio_release_fn)(u32 which);
#define P_audio_release ((audio_release_fn)STOCK(0x7b8d4))

// DMA 缓冲 cache 失效(读帧内容前调用, ptr=帧, size=8000)
typedef void (*cache_inv_fn)(void *ptr, s32 size);
#define P_cache_invalidate ((cache_inv_fn)STOCK(0x3000))

// 消息帧收(带过滤/等待) / RTC 读(0xA6, 7B BCD) — M2/M3 再用
typedef s32 (*rtc_read_fn)(void *out7bcd);
#define P_rtc_read ((rtc_read_fn)STOCK(0x135d4))

// ---- 原厂全局变量 --------------------------------------------------------
#define AUDIO_CTX      ((void *)0x607C0090u)  // 音频上下文
#define AUDCTX_STATE   (*(volatile u32 *)((u8 *)AUDIO_CTX + 0x1c)) // 0空闲/2录音/4播放
#define AUDCTX_METER   (*((volatile u8 *)AUDIO_CTX + 1))           // 电平表启用标志
#define RADIO_TXSTATE  (*(volatile u8 *)0x60936522u)               // TX 态字节

// ---- 注入布局 ------------------------------------------------------------
#define STAGE1_RUN 0x6052C66Cu   // 文件 0x12c66c, 10,976B 空洞 (Stage1: 胶水+TX)
#define STAGE2_RUN 0x606C4000u   // 镜像尾之后 (Stage2: 解码器+数据) — 加载机制待验证

#endif // STOCK_API_H
