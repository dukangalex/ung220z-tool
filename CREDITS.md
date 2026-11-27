# CREDITS

本仓库自有化自上游开源项目，原始出处与各部分来源如实记录如下。
许可证为 MIT，原文见 [LICENSE](LICENSE)（Copyright (c) 2026 Hut-hzf），保持不变。

## 原始项目

- **ung220z-tool** —— Hut-hzf（GitHub [@Hut-hzf](https://github.com/Hut-hzf)）
  上游仓库：https://github.com/Hut-hzf/ung220z-tool
  本仓库的全部基础代码（`ung220z.py`、`ontkit/`、`models/`）出自该项目，
  本仓库在此基础上独立维护，不再跟随上游节奏。

## 代码内已注明的移植来源

- **中兴 webFac 工厂模式协议**（`ontkit/zte_factory.py`）——
  对 zteOnu（github.com/idrnyu/zteOnu）公开实现的 Python 移植，
  原代码文件头已注明，本仓库保留该注记。

## 社区贡献（沿袭上游 README 致谢名单）

- **蓝色大肥鱼**（GitHub [@yitan-xini](https://github.com/yitan-xini) 代为整理提交）——
  修复解密校验、单行 XML 切表、GBK 会话锁检测三处缺陷，并补异常清理、
  口令边界处理与日志脱敏（上游 PR #6）。
- 问题反馈：@YousCheng040727（issue #7）、@jingffei、@Dragon307、
  @kiddx01、@meetinnet、@Cube-sugar258（issue #3）。

## 公开案例来源（机型方法出处，非代码）

- UNG953h1-S：cnblogs（Prego）公开案例
- HG6042A1（烽火）：阿凡博客公开流程
- GM232：萝卜头论坛公开帖

## 引用的外部工具（仅在文档/提示中提及，未并入代码）

- decrypt-lastgood（github.com/joestar817/decrypt-lastgood）——
  `lastgood.xml` 解密工具，主脚本在配置解密失败时以提示形式给出。

## 本仓库的改动

自有化基线修复见 [docs/BASELINE.md](docs/BASELINE.md) 的修复记录；
与上游的分界以 git 历史为准。
