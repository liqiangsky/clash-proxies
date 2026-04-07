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

# 订阅地址列表
URLS = [
    "https://165.154.105.225/clash/proxies",
    "https://pp.dcd.one/clash/proxies",
    "https://vc.majunfei.club:51/clash/proxies",
    "http://138.2.112.136:12580/clash/proxies",
    "http://tmac.eu.org:12580/clash/proxies",
    "http://ql.ethanyang.top:12580/clash/proxies",
    "https://open.tidnotes.top:2083/clash/proxies",
    "http://xqz0.vip:15580/clash/proxies"
]

HEADERS = {"User-Agent": "Clash/1.0.0"}

# ================= 核心过滤配置 =================
# 仅保留地区过滤
ALLOW_COUNTRIES = {"HK", "JP", "SG", "KR", "TW", "US", "GB", "DE"}
TEST_URL = "https://www.google.com" # 目标修改为 Google

ip_cache = {}

def get_country(ip):
    if ip in ip_cache: return ip_cache[ip]
    try:
        r = requests.get(f"http://ip-api.com/json/{ip}", timeout=5)
        code = r.json().get("countryCode")
        ip_cache[ip] = code
        return code
    except:
        return None

def make_unique_name(name, used):
    name = str(name).strip() or "Node"
    if name not in used:
        used.add(name)
        return name
    i = 1
    while f"{name}_{i}" in used: i += 1
    new_name = f"{name}_{i}"
    used.add(new_name)
    return new_name

# ================= 获取与初步筛选 =================
def fetch_proxies():
    all_proxies = []
    seen_addr = set()
    name_used = set()

    for url in URLS:
        print(f"正在获取: {url}")
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15, verify=False)
            data = yaml.safe_load(resp.text)
            if not data or "proxies" not in data: continue

            for p in data["proxies"]:
                server = p.get("server")
                port = p.get("port")
                if not server or not port: continue

                addr = f"{server}:{port}"
                if addr in seen_addr: continue

                # 1. 地区过滤
                try:
                    ip = socket.gethostbyname(server)
                    country = get_country(ip)
                except:
                    continue

                if country not in ALLOW_COUNTRIES:
                    continue

                # 2. 名字处理 (移除了协议和TCP检测，直接记录)
                old_name = p.get("name") or f"{server}_{port}"
                p["name"] = make_unique_name(f"{country}-{old_name}", name_used)

                seen_addr.add(addr)
                all_proxies.append(p)

        except Exception as e:
            print(f"获取失败: {url} -> {e}")

    print(f"地区筛选完成，待测试节点数: {len(all_proxies)}")
    return all_proxies

# ================= 连通性测试 (Google) =================
def test_google_access(name):
    """
    通过 Clash 外部控制 API 测试是否能访问 Google
    """
    safe_name = urllib.parse.quote(name)
    url = f"http://127.0.0.1:9090/proxies/{safe_name}/delay"
    
    try:
        # 使用 Google 作为测试地址，超时设为 8 秒（Google 响应通常比 204 慢）
        params = {"url": TEST_URL, "timeout": 8000}
        r = requests.get(url, params=params, timeout=10)
        
        # 如果返回了有效 delay，说明 Google 握手成功
        delay = r.json().get("delay", 0)
        if delay > 0:
            return (name, delay)
    except:
        pass
    return None

# ================= 工具函数 =================
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

def filter_proxies(proxies):
    if not wait_clash():
        print("错误: Clash 启动失败，请检查 ./clash 路径是否正确")
        return []

    results = []
    print("正在进行 Google 连通性测试...")
    with ThreadPoolExecutor(max_workers=20) as ex:
        for r in ex.map(test_google_access, [p["name"] for p in proxies]):
            if r:
                results.append(r)

    # 按延迟排序
    results.sort(key=lambda x: x[1])
    valid_names = {r[0]: r[1] for r in results}

    out = []
    for p in proxies:
        if p["name"] in valid_names:
            p["name"] += f" | {valid_names[p['name']]}ms"
            out.append(p)
    return out

if __name__ == "__main__":
    # 1. 抓取并按地区过滤
    raw = fetch_proxies()
    if not raw:
        print("未找到符合地区条件的节点")
        exit()

    # 2. 启动临时 Clash 进行真测
    save_for_clash(raw)
    clash_process = start_clash()
    
    try:
        # 3. 运行 Google 访问测试
        good_proxies = filter_proxies(raw)
        
        # 4. 保存结果
        os.makedirs("output", exist_ok=True)
        with open("output/proxies.yaml", "w", encoding="utf-8") as f:
            yaml.dump({"proxies": good_proxies}, f, allow_unicode=True)
        
        print(f"测试结束。共 {len(good_proxies)} 个节点可访问 Google。")
        print("结果已保存至: output/proxies.yaml")
    finally:
        clash_process.terminate()
