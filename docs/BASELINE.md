# 自有化基线复测记录

- 日期：2026-11-26
- 基线：fork dukangalex/ung220z-tool @ 4eb1b1f（上游 Hut-hzf/ung220z-tool）
- 环境：Python 3（云端沙箱），**无真机**。本记录的全部结论均为本地静态与
  冒烟验证，**未做任何真机验证**；机型验证状态仍以 README 与
  ontkit/README.md 的上游诚实标注为准（只有 UNG220Z 经上游作者真机验证，
  其余为社区公开案例或实验性，本仓库未将其升级为「已验证」）。
- 安全边界：测试只用回环地址 127.0.0.1 与占位口令，未连接任何真实设备，
  未使用任何真实口令。

## 冒烟结果

| 项目 | 结果 |
|---|---|
| `python3 -m compileall .` | 通过 |
| `python3 ung220z.py --help` | 通过 |
| `python3 -m ontkit --help` 及 probe/zte/fiberhome/huawei 子命令 `--help` | 通过 |
| `models/` 六个机型入口（b866l1/g7615/h3_2/hg6042a1/hs8145x6/ung853h）`--help` | 全部通过 |
| 模块导入（ung220z、ontkit.cli/core/zte_web/huawei/fiberhome、models._base） | 通过 |
| `ontkit.zte_factory` 直接导入 | 需第三方库 `cryptography`（中兴工厂模式专用），沙箱未装故导入失败；经 `ontkit` CLI 入口不受影响。此为上游既有可选依赖，非缺陷，不改。 |
| `models/_base.py` 直接运行 | 失败，但它不是入口脚本（是机型入口的公共基类，靠入口脚本注入路径），非缺陷，不改。 |

## 发现并修复的缺陷（2 处）

### 1. `enable_telnet()` 签名缺 `timeout` 参数（主流程必崩）

- 现象：`main()` 以 `enable_telnet(ip, user, pw, open_browser=..., timeout=a.timeout)`
  调用，但函数签名只有 `(ip, user, pw, open_browser=True)`。
  实证：按主流程的调用方式复现出
  `TypeError: enable_telnet() got an unexpected keyword argument 'timeout'`，
  该异常会被主流程总异常捕获，脚本在开启 Telnet 这一步直接退出——
  即主脚本对任何设备都跑不通。
- 修复：给 `enable_telnet` 增加 `timeout=8` 参数，并透传给内部
  `http_get(url, timeout=timeout)`，使 `--timeout` 的语义落到实处
  （不是简单删掉调用处的参数）。
- 复测：修复后以回环地址＋占位口令调用，三种 URL 变体均优雅失败
  （Connection refused → WARN 日志），函数返回 False，不再抛 TypeError。

### 2. `ung220z.py` 缺 `import base64`（Web 侧侦察静默失效）

- 现象：`WebSession.login()` 使用 `base64.b64encode(...)`，但文件头部
  未导入 base64。实证：模块无 `base64` 属性。该错误会被 `web_recon()`
  的宽泛异常捕获，只打一条 WARN 后返回空结果——主流程第 ④ 步
  「Web 侧侦察」（越权读管理员行、取 Telnet 口令）永远静默失效，
  用户只会看到 Telnet 登录更难成功，不会知道侦察没跑。
- 修复：头部补 `import base64`（与 ontkit/zte_web.py、huawei.py 的
  同类用法一致）。
- 复测：修复后 `base64` 编解码调用正常。

## 推广/引流扫描

全仓（.py + .md）扫描推广、返利、社群引流类关键词与全部外链：
未发现厂商推广、付费引流或返利链接。外链均为来源引用——上游仓库的
issue/PR 链接、贡献者主页、公开案例出处（cnblogs、阿凡博客、萝卜头论坛）
与文档中引用的外部工具 decrypt-lastgood，均属如实致谢与出处标注，
**全部保留，不作剥离**。

## 未验证事项（如实标注）

- 未连接任何光猫真机：Telnet 开启、sidbg 解密、凭据提取、中兴工厂模式、
  烽火与华为流程均未实跑，正确性仍以上游作者与社区案例的记录为准。
- 后续如做真机验证，须用自有设备与自有口令，并把结果回填本文件。
