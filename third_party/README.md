# 第三方依赖

| 依赖 | 固定版本及用途 |
| --- | --- |
| [kgoba/ft8_lib](https://github.com/kgoba/ft8_lib/tree/9fec6ca39886edbf96f4f5e71edc76da5074e871) | 基线 9fec6ca。用 [本地移植差分](ft8_lib-ftx1.patch) 重建接收、发射和 FFT 构建使用的工作树。保留 [MIT 许可](ft8_lib-LICENSE.txt) 及上游源码中的第三方声明。 |
| [Nikolay-Kha/ft710-internals](https://github.com/Nikolay-Kha/ft710-internals/tree/c7b12bdb621109cbca6d4c2aa4334332421f74bf) | SFL 编解码脚本采用 Unlicense。历史工作区的后一提交只改了 .gitignore，公开基线的脚本内容相同。 |
| [sq9pd/Yaesu-FTX-1-mod](https://github.com/sq9pd/Yaesu-FTX-1-mod/tree/ee71225da9db6200a8098547f4f00b6caf438371) | MAIN V40 + DISPLAY V35 提供 SWR SCAN 与 BUTTON SETUP。准备脚本通过固定提交和原厂文件在本地生成集成数据。归属及使用条款见上游。 |
| [WSJT-X 样本](https://sourceforge.net/projects/wsjt/files/samples/FT8/) | 210703_133430.wav 用于 FT8 PCM 回放，下载来源与哈希见 [复现指南](../docs/reproduce.md)。 |
| [Yaesu FTX-1 官方页面](https://connect.yaesu.com/indivisual/items/ftx-1series/) | 2026-08-28 日版固件和设备文档。固件镜像由 Yaesu 提供。 |

编译器与分析工具的版本见 [复现指南](../docs/reproduce.md) 和 [分析指南](../docs/analysis.md)。
