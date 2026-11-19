# Yaesu FTX-1 固件研究

本项目记录 Yaesu FTX-1 的固件逆向、补丁源码和离线验证。当前联合版面向 **日版 DISPLAY V01-10 与 MAIN V01-13 原厂底包**，实现机内 FT8 收发、CW 摩尔斯译码，以及基于 SQ9PD 改版的 SWR SCAN 和分页软键。

从 [复现指南](docs/reproduce.md) 开始。指南提供 PowerShell 命令、固定依赖、输入与输出的 SHA-256，以及可直接交给 AI 工具的任务说明。[AGENTS.md](AGENTS.md) 指向同一流程。

| 内容 | 入口 |
| --- | --- |
| 补丁源码、打包工具与回归测试 | [patch](patch/) |
| FT8、CW_DEC 和 SWR SCAN 操作 | [操作说明](docs/operation.md) |
| DISPLAY、MAIN 与 IFDSP 逆向 | [分析指南](docs/analysis.md) |
| 软键与 SWR 协议、绘制、状态机 | [SQ9PD 改版分析](docs/sq9pd-swr-custom-button-analysis.md) |
| Robot 36 SSTV 预研 | [SSTV 交接](docs/sstv/交接文档.md) |
| 依赖来源和许可 | [第三方说明](third_party/README.md) |

两份联合版镜像从原厂输入在本地生成，构建哈希与开发工作区的修复版一致。该修复版的实机刷写与射频测量仍待验证。SWR 扫描会发射射频。

本仓库原创代码和文档采用 [GPLv3](LICENSE)。Yaesu 固件、第三方固件差分、工具链和 Ghidra 工程由复现者在本地准备或生成。
