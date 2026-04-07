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
    "https://165.154.105.225/clash/proxies?c=HK,TW,US,JP,SG,KR",
    #"http://161.33.151.88:12580/clash/proxies",
    #"http://158.180.234.237:12580/clash/proxies",
    #"http://140.238.31.152:12580/clash/proxies",
    "https://pp.dcd.one/clash/proxies?c=HK,TW,US,JP,SG,KR",
    #"http://h3.g01.work:12580/clash/proxies",
    "https://vc.majunfei.club:51/clash/proxies?c=HK,TW,US,JP,SG,KR",
    "http://138.2.112.136:12580/clash/proxies?c=HK,TW,US,JP,SG,KR",
    "http://tmac.eu.org:12580/clash/proxies?c=HK,TW,US,JP,SG,KR"
    #"http://176.126.114.231:12580/clash/proxies",
    "http://ql.ethanyang.top:12580/clash/proxies?c=HK,TW,US,JP,SG,KR",
    "https://open.tidnotes.top:2083/clash/proxies?c=HK,TW,US,JP,SG,KR",
    #"http://132.226.224.85:56852/clash/proxies",
    "http://xqz0.vip:15580/clash/proxies?c=HK,TW,US,JP,SG,KR"
]

HEADERS = {
    "User-Agent": "Clash/1.0.0",
    "Accept": "*/*"
}


# ================= 国家白名单 =================
ALLOW_COUNTRIES = {"HK", "JP", "SG", "KR", "TW", "US", "GB", "DE"}
# ================= IP缓存 =================

ip_cache = {}

def get_country(ip):
    if ip in ip_cache:
        return ip_cache[ip]

    try:
        r = requests.get(f"http://ip-api.com/json/{ip}", timeout=5)
        data = r.json()
        code = data.get("countryCode")
        ip_cache[ip] = code
        return code
    except:
        return None

# ================= TCP检测 =================
def tcp_check(server, port):
    try:
        s = socket.create_connection((server, port), timeout=3)
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
        print(f"获取: {url}")
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15, verify=False)
            data = yaml.safe_load(resp.text)
            if not data or "proxies" not in data:
                continue

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

                # ========= 协议细化 =========
                if ptype == "ss":
                    cipher = str(p.get("cipher", "")).lower()
                    if cipher not in ["aes-128-gcm", "aes-256-gcm", "chacha20-ietf-poly1305"]:
                        continue
                    if not p.get("password"):
                        continue

                elif ptype == "trojan":
                    if not p.get("password"):
                        continue

                elif ptype == "vmess":
                    if not p.get("uuid"):
                        continue

                # ========= TCP检测 =========
                if not tcp_check(server, port):
                    continue

                # ========= IP解析 =========
                try:
                    ip = socket.gethostbyname(server)
                except:
                    continue

                country = get_country(ip)
                if country not in ALLOW_COUNTRIES:
                    continue

                # ========= 名字处理 =========
                old_name = p.get("name") or f"{server}_{port}"
                p["name"] = make_unique_name(f"{country}-{old_name}", name_used)

                seen_addr.add(addr)
                all_proxies.append(p)

        except Exception as e:
            print("错误:", e)

    print(f"筛选后节点数: {len(all_proxies)}")
    return all_proxies

# ================= Clash测试 =================
def save_for_clash(proxies):
    config = {
        "mode": "global",
        "port": 7890,
        "external-controller": "127.0.0.1:9090",
        "proxies": proxies,
        "proxy-groups": [{"name": "test", "type": "select", "proxies": [p["name"] for p in proxies]}],
        "rules": ["MATCH,test"]
    }
    with open("run.yaml", "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True)

def start_clash():
    return subprocess.Popen(["./clash", "-f", "run.yaml"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)

def wait_clash():
    for _ in range(10):
        try:
            socket.create_connection(("127.0.0.1", 9090), timeout=1)
            return True
        except:
            time.sleep(1)
    return False

def test_delay(name):
    safe = urllib.parse.quote(name)
    url = f"http://127.0.0.1:9090/proxies/{safe}/delay"

    try:
        r = requests.get(url, params={"url": "https://www.gstatic.com/generate_204", "timeout": 5000}, timeout=5)
        d = r.json().get("delay", 0)
        if 0 < d < 1500:
            return (name, d)
    except:
        pass
    return None

def filter_proxies(proxies):
    if not wait_clash():
        return []

    results = []
    with ThreadPoolExecutor(max_workers=30) as ex:
        for r in ex.map(test_delay, [p["name"] for p in proxies]):
            if r:
                results.append(r)

    results.sort(key=lambda x: x[1])
    delay_map = dict(results)

    out = []
    for p in proxies:
        if p["name"] in delay_map:
            p["name"] += f" | {delay_map[p['name']]}ms"
            out.append(p)

    return out

# ================= 输出 =================
def final_save(proxies):
    os.makedirs("output", exist_ok=True)
    with open("output/proxies.yaml", "w", encoding="utf-8") as f:
        yaml.dump({"proxies": proxies}, f, allow_unicode=True)

# ================= 主程序 =================
if __name__ == "__main__":
    raw = fetch_proxies()
    save_for_clash(raw)

    clash = start_clash()
    try:
        good = filter_proxies(raw)
        final_save(good)
        print("完成:", len(good))
    finally:
        clash.terminate()
