# angela-onu（问猫）

光猫（ONT）凭据自查工具箱：**UNG220Z 一键提取**，另含多厂商适配包 `ontkit`
（中兴 / 烽火 / 华为 / 九联），以及固件指纹识别与分家族排障建议。

> 本仓库中文别名「问猫」，自有化自上游 Hut-hzf/ung220z-tool（MIT），
> 原名 ung220z-tool，出处与致谢见 [CREDITS.md](CREDITS.md)。
> 主脚本名 `ung220z.py` 与机型名 UNG220Z 是设备型号命名，保留不变。

支持机型与验证状态见 [机型兼容性](#机型兼容性)，其中只有 UNG220Z 经过真机验证。

> ⚠️ 仅用于**你自己的设备**，用于找回自己忘记的管理密码、迁移宽带配置或安全自查。
> 未经授权对他人设备使用属于违法行为，作者不承担任何责任。

## 背景

这类光猫的 Web 管理页基于 `.gch` CGI 框架，登录口令由 TR-069 定期轮换，普通用户拿到的密码往往几天就失效。本工具走 Telnet 通道，直接读取设备配置库，拿到**当下有效**的全部凭据。

## 目录结构

```
ung220z.py          # 主脚本：UNG220Z 一键提权 + 提凭据
ontkit/             # 多厂商适配包
├── cli.py          #   probe / zte / huawei 三个子命令
├── zte_factory.py  #   中兴 webFac 工厂模式（AES-ECB 协议）
├── zte_web.py      #   中兴 .gch 登录、配置解密、凭据提取
├── huawei.py       #   华为 ssmp 登录、开 Telnet（实验性）
└── core.py         #   HTTP 会话 + Telnet 客户端
models/             # 按型号的入口脚本（自动补默认端口）
├── ung853h.py  h3_2.py  g7615.py  hs8145x6.py  b866l1.py
```

## 工作流程

```
用户输入账号密码
   ↓
拼出 http://<ip>/usr=<user>&psw=<pass>&cmd=1&telnet.gch 并打开浏览器（同时脚本直连兜底）
   ↓
Telnet 登录 → root shell
   ↓
sidbg 1 DB decry /userconfig/cfg/db_user_cfg.xml 解密配置
   ↓
提取 Web 账号 / Telnet 口令 / PPPoE / WiFi 密钥 / root 口令
   ↓
打印凭据表 + 落盘日志
```

## 用法

```bash
python3 ung220z.py
```

会依次询问：

```
※ 用户名和密码通常印在光猫【背面贴纸】上（S/N 标签）
  形如「用户名：user   密码：xxxxxxxx」，把光猫翻过来就能看到

① 光猫地址 [192.168.1.1]:
② 用户名 [user]:
③ 密码（输入时不显示）
   密码:
```

也可以全部走命令行：

```bash
python3 ung220z.py -i 192.168.1.1 -u user -p '你的密码'
python3 ung220z.py -i 192.168.1.1 -u user -p '你的密码' --no-browser
```

### 常用参数

| 参数 | 说明 |
|---|---|
| `-i, --ip` | 光猫地址，默认 `192.168.1.1` |
| `-u, --user` | 登录用户名，默认 `user` |
| `-p, --password` | 登录密码，不填则交互输入 |
| `--telnet-user` | Telnet 用户名，默认 `CMCCAdmin` |
| `--telnet-password` | Telnet 口令（部分机型与 Web 口令不同） |
| `--no-browser` | 不调用浏览器，纯 HTTP 请求 |
| `--unlock` | Web 被会话锁占住时重启 httpd 解锁 |
| `--no-release` | 不尝试释放残留 Web 会话 |
| `--telnet-port` | Telnet 端口，默认 23 |
| `--timeout` | 网络超时秒数，默认 8 |

## 输出示例

```
[22:15:00] INFO   会话开始  目标=192.168.1.1  账户=user
[22:15:00] HTTP   已发送给浏览器: http://192.168.1.1/usr=user&psw=***&cmd=1&telnet.gch
[22:15:00] HTTP   telnet.gch → TelnetSet Success!
[22:15:00] PROBE  nc -zv 192.168.1.1 23 → succeeded
[22:15:01] AUTH   Telnet CMCCAdmin / ****** → 登录成功（root）
[22:15:02] SHELL  sidbg 1 DB decry /userconfig/cfg/db_user_cfg.xml → /tmp/debug-decry-cfg
[22:15:03] DATA   DevAuthInfo  CMCCAdmin  / ******  Level=1
[22:15:04] CRACK  MATCH: ******  (/etc/shadow)
```

最后输出凭据汇总表，并写入 `ung220z_<时间戳>.log`。

## 依赖

- Python 3.8+
- 标准库即可，无需 pip 安装
- 设备已开启 Telnet（脚本会自动通过 `telnet.gch` 尝试开启）

## 原理说明

| 环节 | 说明 |
|---|---|
| 开 Telnet | `GET /usr=<user>&psw=<pass>&cmd=1&telnet.gch`，返回 `TelnetSet Success!` 即成功 |
| Web 登录 | 密码前端只做 base64，`Frm_Logintoken` 每次响应递增，必须回填实时值 |
| 配置解密 | `sidbg 1 DB decry` 无口令即可解密，得到明文 XML |
| root 口令 | `/etc/shadow` 中为 SHA-256 crypt，工具会用常见出厂口令比对 |

## 多厂商支持（ontkit）

主脚本只针对九联 `.gch` 体系。遇到其他固件时用 `ontkit`：

```bash
# 先识别固件家族
python3 -m ontkit probe -H 192.168.1.1

# 中兴系（G7615 / UNG853H / 吉比特等）：走 webFac 工厂模式开 Telnet
python3 -m ontkit zte -H 192.168.1.1 -p 8080 --mode factory --enable-telnet

# 华为系（HS8145X6 / B866-L1 等）
python3 -m ontkit huawei -H 192.168.1.1
```

按型号直接跑：

```bash
python3 models/g7615.py    -H 192.168.1.1 --mode factory
python3 models/ung853h.py  -H 192.168.1.1 -u user -P '贴纸密码' --extract
```

各型号的验证状态见 [ontkit/README.md](ontkit/README.md)：webFac 协议按公开实现移植并已自测，
其余型号未经真机验证。

## 排障

### `telnet.gch` 返回 404

说明该固件没有这个接口，**不是九联/吉比特的 `.gch` 体系**，本脚本的开启方式不适用。
脚本会打印设备指纹（`Server` 头 + 页面标题）帮助判断。下一步：

```bash
python3 -m ontkit probe -H 192.168.1.1          # 识别固件家族
python3 -m ontkit zte   -H 192.168.1.1 -p 8080  # 中兴系（webFac 工厂模式）
python3 -m ontkit huawei -H 192.168.1.1         # 华为系（ssmp）
```

### `telnet.gch` 成功但 23 端口未监听

- 设备可能在 Web 后台把 Telnet 服务关闭了，只留了开关接口
- 也可能需要几秒才起监听，等一下重试

### Telnet 能连上但登录被拒

Telnet 与 Web 是**两套账号库**。脚本会依次尝试：

1. 你填的 Web 账号（如 `useradmin`）
2. `CMCCAdmin` + 同一口令
3. `--telnet-password` 指定值
4. Web 侧侦察：`manager_aduser_conf_t.gch&IF_INDEX=0` 读管理员行 → 用其口令登录 → `tele_sec_tserver_t.gch` 取 `TS_UPwd`
5. 出厂默认组合

也可以手动在浏览器（已登录状态）打开：

```
http://<光猫IP>/getpage.gch?pid=1002&nextpage=tele_sec_tserver_t.gch
```

页面源码里 `TS_UName` / `TS_UPwd` 就是 Telnet 账号密码。

### 登录失败次数超限

设备通常 3 次失败进入延时校验，**停止重试**，静默等待 10~30 分钟。

## 修复记录

### 自有化基线（2026-11-26）

本仓库自有化自上游 Hut-hzf/ung220z-tool（MIT），出处与致谢见
[CREDITS.md](CREDITS.md)。基线复测（无真机，仅本地冒烟）修复 2 处缺陷，
完整记录见 [docs/BASELINE.md](docs/BASELINE.md)：

| 问题 | 影响 | 修复 |
|---|---|---|
| `main()` 给 `enable_telnet()` 传 `timeout` 参数，但函数签名没有 | 主流程一进开启 Telnet 就 TypeError 退出，对任何设备都跑不通 | 函数增加 `timeout=8` 参数并透传给 `http_get` |
| `ung220z.py` 缺 `import base64` | `WebSession.login()` 抛错被宽泛异常吞掉，Web 侧侦察（第 ④ 步）静默失效 | 头部补 `import base64` |

### v1.2

| 问题 | 修复 |
|---|---|
| 口令含 `%` 时 URL 被当成非法转义，服务器返回 400 | 检测 `% & # ? + 空格`，优先发送百分号编码版（`aDm8H%MdA` → `aDm8H%25MdA`） |
| 缺少烽火（FiberHome）支持 | 新增 `ontkit fiberhome` + `models/hg6042a1.py`，用 MAC 开 Telnet 并读 `show admin_pwd` |

### v1.1（合并社区反馈）

| 问题 | 影响 | 修复 |
|---|---|---|
| `ls` 的 stderr 也落在 pty 上 | 解密失败被判成功，最后打印一张空凭据表 | 改用 `test -s && echo __OK__` 判定 |
| `sed` 区间在单行 XML 上失效 | 所有表混在一起，PPPoE/WiFi 被当成 Web 账号 | 新增 `Cfg` 类，整份 `cat` 一次后本地按 `<Tbl>` 切表（顺带把 6 次往返压成 1 次） |
| Web 页为 GBK 时解码失败 | `其他用户` 匹配不到，`--unlock` 形同虚设 | `_decode` 优先取响应头 charset，再 utf-8→gbk→gb18030 回退 |
| 无 try/finally | 断线时裸 traceback，设备上残留明文配置 | `finally` 中 `rm -f /tmp/debug-decry-cfg`、关闭 Telnet 与日志；日志文件 0600 |
| 口令 `.strip()` | 首尾空格是口令一部分时被改坏 | 改为 `rstrip("\r\n")` |
| URL 明文写日志 | 口令泄漏到日志文件 | 日志中 `psw=***` |
| 固定 marker `__X__` | 配置内容恰好包含该串时输出被截断 | 每次随机 marker |
| `IAC IAC` 未处理 | 吃掉一个 0xFF 字节 | 按 telnet 规范输出字面量 |
| 缺 openssl 时静默 | root 比对无声失败 | 明确提示 |

退出码语义：`0` 成功 / `1` 参数或异常 / `2` 网关不可达 / `3` Telnet 端口未开 / `4` 登录失败 / `5` 配置解密失败 / `130` 用户中断。

## 致谢

这个工具的可靠性，很大程度上来自各位使用者愿意花时间把失败日志贴出来。
感谢每一位提交 issue、PR 的朋友：

**代码贡献**

- **蓝色大肥鱼**（GitHub [@yitan-xini](https://github.com/yitan-xini) 代为整理提交）——
  发现并修复了三处会导致「静默假失败」的关键缺陷：解密校验拿到 `ls` 的 stderr 就判成功、
  单行 XML 下 `sed` 区间失效导致串表、GBK 页面让会话锁检测永远失效。
  同时补上了异常清理、口令边界处理、日志脱敏等改进。原始补丁见
  [PR #6](https://github.com/Hut-hzf/ung220z-tool/pull/6)。

**问题反馈**

- [@YousCheng040727](https://github.com/YousCheng040727) —— [issue #7](https://github.com/Hut-hzf/ung220z-tool/issues/7)：
  首个报告 `telnet.gch` 返回 404 的案例，直接促成了「固件指纹识别 + 分家族建议」这组功能。
- [@jingffei](https://github.com/jingffei) —— [issue #3](https://github.com/Hut-hzf/ung220z-tool/issues/3)：
  HG6042A1 的日志里出现了 `get_factory_mode`，第一次让人看清「这是中兴工厂模式，不是 `.gch`」。
- [@Dragon307](https://github.com/Dragon307) —— issue #3：
  完整复现了「`telnet.gch` 成功但 Telnet 登录被拒」的场景，验证了 Web 与 Telnet 两套账号库的判断。
- [@kiddx01](https://github.com/kiddx01) —— issue #3：GM232（V1A0.A04.01）的 404/400 记录。
- [@meetinnet](https://github.com/meetinnet) —— issue #3：`[Mini web server]` 案例，确认了非 `.gch` 固件的边界。
- [@Cube-sugar258](https://github.com/Cube-sugar258) —— issue #3：SK-D740L 的 23 端口未开放案例。

如果上面的名单漏了你，或者你的报告还没被修复——欢迎继续开 issue，
附上脚本打印的 `指纹 Server=... title=... 特征=...` 那一行，定位会快很多。

## 机型兼容性

> **只有 UNG220Z 是作者真机验证的。** 其余型号来自社区公开案例或 issue 日志，
> 标注 📄 表示「有别人的成功记录，但我没有复现」。

| 型号 | 状态 | 关键方法 | 来源 |
|---|---|---|---|
| UNG220Z | ✅ 真机验证 | `telnet.gch` → 越权读账号 → `sidbg` 解密 | 本项目实测 |
| UNG953h1-S | 📄 公开案例 | Telnet 默认 `useradmin/useradmin`；配置解密用 `lastgood.xml` | [cnblogs](https://www.cnblogs.com/Prego/p/22631311) |
| HG6042A1 | 📄 公开案例 | **烽火**：`/cgi-bin/telnetenable.cgi?telnetenable=1&key=<MAC>`，登录 `admin/Fh@<MAC后6位>`，`load_cli factory` → `show admin_pwd` | [阿凡博客](https://blog.iafan.com/post-6.html) |
| GM232 | 📄 公开案例 | `telnet.gch` **必须把 `%` 编码成 `%25`**；Telnet 口令在 `config.bin` 备份里（RouterPassView 搜 `TS_UPwd`） | [萝卜头论坛](https://bbs.luobotou.org/forum.php?mod=viewthread&tid=49623) |
| UNP720Z | ⚠️ 未验证 | 仅知 `telnet.gch` 成功但 Telnet 账号不同 | issue 反馈 |
| SK-D740L | ❌ 无资料 | 仅知 23 端口未开 | issue 反馈 |

### 关于 `%` 的坑（重要）

早期版本直接把口令拼进 URL，`aDm8H%MdA` 会被当成非法百分号转义，服务器返回 **400 Bad Request**。
v1.2 起检测到 `% & # ? + 空格` 时优先发送编码版：

```
http://192.168.1.1/usr=CMCCAdmin&psw=aDm8H%25MdA&cmd=1&telnet.gch
```

### 烽火机型

```bash
python3 -m ontkit fiberhome -H 192.168.1.1 -m AA:BB:CC:DD:EE:FF
# 或
python3 models/hg6042a1.py -H 192.168.1.1 -m AA:BB:CC:DD:EE:FF
```

流程：用 MAC 开 Telnet → `admin/Fh@<MAC后6位>` 登录 → `load_cli factory` → `show admin_pwd`。

### GM232 这类「Telnet 选项时有时无」的机型

社区经验：Telnet 开关只在**恢复出厂、TR-069 下发配置之前**存在。所以顺序是：

1. 恢复出厂 → 用 `CMCCAdmin / aDm8H%MdA` 登录（此时是默认超密）
2. 立刻开 Telnet（`telnet.gch` 或「管理 → 设备管理」里的选项）
3. 再去「备份配置文件」下载 `config.bin`，用 RouterPassView 搜 `TS_UPwd`

## 免责声明

本项目仅用于教育与自有设备维护。使用者应确保对目标设备拥有合法管理权限。
