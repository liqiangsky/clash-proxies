import requests
import yaml
import time
import subprocess
import socket
import os
import urllib3
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

# 禁用 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 你的所有原始订阅地址
URLS = [
    "https://165.154.105.225/clash/proxies",
    #"http://161.33.151.88:12580/clash/proxies",
    #"http://158.180.234.237:12580/clash/proxies",
    #"http://140.238.31.152:12580/clash/proxies",
    "https://pp.dcd.one/clash/proxies",
    #"http://h3.g01.work:12580/clash/proxies",
    "https://vc.majunfei.club:51/clash/proxies",
    "http://138.2.112.136:12580/clash/proxies",
    "http://tmac.eu.org:12580/clash/proxies"
    #"http://176.126.114.231:12580/clash/proxies",
    "http://ql.ethanyang.top:12580/clash/proxies",
    "https://open.tidnotes.top:2083/clash/proxies",
    #"http://132.226.224.85:56852/clash/proxies",
    "http://xqz0.vip:15580/clash/proxies"
]

HEADERS = {
    "User-Agent": "Clash/1.0.0",
    "Accept": "*/*"
}

# ================= TCP检测 =================
def tcp_check(server, port, timeout=3):
    try:
        s = socket.create_connection((server, port), timeout=timeout)
        s.close()
        return True
    except:
        return False

# ================= 名字去重 =================
def make_unique_name(name, used):
    name = str(name).strip() or "Node"
    if name not in used:
        used.add(name)
        return name
    i = 1
    while f"{name}_{i}" in used:
        i += 1
    new_name = f"{name}_{i}"
    used.add(new_name)
    return new_name

# ================= 获取节点 =================
def fetch_proxies():
    all_proxies = []
    seen_addr = set()
    name_used = set()

    for url in URLS:
        print(f"正在获取: {url}")
        success = False

        for _ in range(3):
            try:
                resp = requests.get(url, headers=HEADERS, timeout=15, verify=False)
                if resp.status_code == 200:
                    data = yaml.safe_load(resp.text)
                    if not data or "proxies" not in data:
                        break

                    for p in data["proxies"]:
                        server = p.get("server")
                        port = p.get("port")

                        if not server or not port:
                            continue

                        addr = f"{server}:{port}"
                        if addr in seen_addr:
                            continue

                        # ========= 协议过滤 =========
                        ptype = p.get("type")
                        if ptype not in ["ss", "trojan", "vmess"]:
                            continue

                        # ========= 端口过滤 =========
                        if not (80 <= int(port) <= 65535):
                            continue

                        # ========= 名字垃圾过滤 =========
                        bad_keywords = ["剩余", "过期", "流量", "测试", "官网"]
                        if any(k in str(p.get("name", "")) for k in bad_keywords):
                            continue

                        # ========= 协议细化 =========
                        if ptype == "ss":
                            cipher = str(p.get("cipher", "")).lower()
                            allow_ciphers = [
                                "aes-128-gcm",
                                "aes-256-gcm",
                                "chacha20-ietf-poly1305"
                            ]
                            if cipher not in allow_ciphers:
                                continue
                            if not p.get("password"):
                                continue

                        elif ptype == "trojan":
                            if not p.get("password"):
                                continue
                            if not p.get("tls", True):
                                continue

                        elif ptype == "vmess":
                            if not p.get("uuid"):
                                continue
                            network = p.get("network", "")
                            if network not in ["ws", "grpc"]:
                                continue

                        # ========= TCP检测 =========
                        if not tcp_check(server, port):
                            continue

                        # ========= 名字处理 =========
                        old_name = p.get("name") or f"{server}_{port}"
                        p["name"] = make_unique_name(old_name, name_used)

                        seen_addr.add(addr)
                        all_proxies.append(p)

                    success = True
                    break
            except:
                time.sleep(1)

        if not success:
            print(f"跳过源: {url}")

    print(f"抓取完成，共 {len(all_proxies)} 个节点")
    return all_proxies

# ================= 保存临时配置 =================
def save_for_clash(proxies):
    config = {
        "mode": "global",
        "port": 7890,
        "socks-port": 7891,
        "external-controller": "127.0.0.1:9090",
        "proxies": proxies,
        "proxy-groups": [
            {"name": "test", "type": "select", "proxies": [p["name"] for p in proxies]}
        ],
        "rules": ["MATCH,test"]
    }
    with open("run.yaml", "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, sort_keys=False)

# ================= 启动 Clash =================
def start_clash():
    print("启动 Clash...")
    if os.name != 'nt':
        os.chmod("./clash", 0o755)
    return subprocess.Popen(
        ["./clash", "-f", "run.yaml"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

# ================= 等待 Clash =================
def wait_clash():
    for _ in range(15):
        try:
            s = socket.create_connection(("127.0.0.1", 9090), timeout=1)
            s.close()
            return True
        except:
            time.sleep(1)
    return False

# ================= 延迟测试 =================
def test_delay(name):
    safe_name = urllib.parse.quote(name)
    api_url = f"http://127.0.0.1:9090/proxies/{safe_name}/delay"
    test_target = "https://www.gstatic.com/generate_204"

    delays = []
    for _ in range(3):
        try:
            r = requests.get(api_url, params={"url": test_target, "timeout": 5000}, timeout=6)
            if r.status_code == 200:
                d = r.json().get("delay", 0)
                if 0 < d < 2000:
                    delays.append(d)
        except:
            continue

    if len(delays) >= 2:
        avg = sum(delays) / len(delays)
        if avg > 1200:
            return None

        print(f"✅ {name} - {int(avg)}ms")
        return (name, avg)

    return None

# ================= 筛选 =================
def filter_proxies(proxies):
    if not wait_clash():
        print("Clash 未启动")
        return []

    print("开始测速...")
    results = []
    names = [p["name"] for p in proxies]

    with ThreadPoolExecutor(max_workers=30) as executor:
        for res in executor.map(test_delay, names):
            if res:
                results.append(res)

    results.sort(key=lambda x: x[1])

    delay_map = {name: int(delay) for name, delay in results}

    new_list = []
    for p in proxies:
        if p["name"] in delay_map:
            p["name"] = f"{p['name']} | {delay_map[p['name']]}ms"
            new_list.append(p)

    return new_list

# ================= 输出 =================
def final_save(proxies):
    os.makedirs("output", exist_ok=True)

    with open("output/proxies.yaml", "w", encoding="utf-8") as f:
        yaml.dump(
            {"proxies": proxies},
            f,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False
        )

    print(f"✅ 已输出 proxies.yaml，共 {len(proxies)} 个节点")

# ================= 主程序 =================
if __name__ == "__main__":
    raw = fetch_proxies()
    if not raw:
        print("没有节点")
        exit()

    save_for_clash(raw)
    clash = start_clash()

    try:
        good = filter_proxies(raw)
        final_save(good)
    finally:
        clash.terminate()
        print("Clash 已关闭")
