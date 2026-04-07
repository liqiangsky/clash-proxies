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
    "https://165.154.105.225/clash/proxies?speed=15,30",
    #"http://161.33.151.88:12580/clash/proxies",
    #"http://158.180.234.237:12580/clash/proxies",
    #"http://140.238.31.152:12580/clash/proxies",
    "https://pp.dcd.one/clash/proxies?speed=15,30",
    #"http://h3.g01.work:12580/clash/proxies",
    "https://vc.majunfei.club:51/clash/proxies?speed=15,30",
    "http://138.2.112.136:12580/clash/proxies?speed=15,30",
    #"http://176.126.114.231:12580/clash/proxies",
    "https://fp.ethanyang.top/clash/proxies?speed=15,30",
    "http://ql.ethanyang.top:12580/clash/proxies?speed=15,30",
    "https://open.tidnotes.top:2083/clash/proxies?speed=15,30",
    #"http://132.226.224.85:56852/clash/proxies",
    "http://xqz0.vip:15580/clash/proxies?speed=15,30"
]

HEADERS = {
    "User-Agent": "Clash/1.0.0",
    "Accept": "*/*"
}

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

def fetch_proxies():
    all_proxies = []
    seen_addr = set()
    name_used = set()

    for url in URLS:
        print(f"正在获取: {url}")
        success = False
        for _ in range(3):  # 增加重试逻辑，解决 HTTPS 跳过问题
            try:
                resp = requests.get(url, headers=HEADERS, timeout=15, verify=False)
                if resp.status_code == 200:
                    data = yaml.safe_load(resp.text)
                    if not data or "proxies" not in data:
                        break
                    
                    for p in data["proxies"]:
                        server = p.get("server")
                        port = p.get("port")
                        if not server or not port: continue

                        addr = f"{server}:{port}"
                        if addr in seen_addr: continue
                        
                        # 过滤过时加密（这些加密会导致 Clash 报错或连不上）
                        cipher = str(p.get("cipher", "")).lower()
                        if cipher in ['rc4-md5', 'chacha20', 'aes-128-cfb', 'none']:
                            continue

                        # 设置唯一名称
                        old_name = p.get("name") or f"{server}_{port}"
                        p["name"] = make_unique_name(old_name, name_used)
                        
                        seen_addr.add(addr)
                        all_proxies.append(p)
                    success = True
                    break
            except Exception as e:
                time.sleep(1)
        if not success:
            print(f"跳过源: {url}")

    print(f"抓取完成，去重后共 {len(all_proxies)} 个节点")
    return all_proxies

def save_for_clash(proxies):
    # 强制写入基础配置，确保 API 端口可用
    base_config = {
        "mode": "rule",
        "port": 7890,
        "socks-port": 7891,
        "external-controller": "127.0.0.1:9090",
        "proxies": proxies,
        "proxy-groups": [
            {"name": "Proxy", "type": "select", "proxies": [p["name"] for p in proxies]}
        ],
        "rules": ["MATCH,Proxy"]
    }
    with open("run.yaml", "w", encoding="utf-8") as f:
        yaml.dump(base_config, f, allow_unicode=True, sort_keys=False)

def start_clash():
    print("启动 Clash 核心进行测试...")
    if os.name != 'nt': # Linux/Mac 增加权限
        os.chmod("./clash", 0o755)
    return subprocess.Popen(["./clash", "-f", "run.yaml"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def wait_clash():
    for _ in range(15):
        try:
            s = socket.create_connection(("127.0.0.1", 9090), timeout=1)
            s.close()
            return True
        except:
            time.sleep(1)
    return False

def test_delay(name):
    # 关键：URL 编码解决特殊字符导致的 Timeout
    safe_name = urllib.parse.quote(name)
    api_url = f"http://127.0.0.1:9090/proxies/{safe_name}/delay"
    test_target = "http://cp.cloudflare.com/generate_204"
    
    delays = []
    for _ in range(2): # 测2次，只要有1次通就行
        try:
            r = requests.get(api_url, params={"url": test_target, "timeout": 3000}, timeout=5)
            if r.status_code == 200:
                d = r.json().get("delay", 0)
                if d > 0: delays.append(d)
        except:
            continue
    
    if delays:
        avg = sum(delays) / len(delays)
        print(f"✅ {name} - {int(avg)}ms")
        return (name, avg)
    return None

def filter_proxies(proxies):
    if not wait_clash():
        print("Clash 核心未响应，退出")
        return []

    print("正在多线程测速...")
    results = []
    names = [p["name"] for p in proxies]
    
    with ThreadPoolExecutor(max_workers=30) as executor:
        for res in executor.map(test_delay, names):
            if res: results.append(res)

    results.sort(key=lambda x: x[1]) # 按延迟排序
    valid_names = [r[0] for r in results]
    return [p for p in proxies if p["name"] in valid_names]

def final_save(proxies):
    os.makedirs("output", exist_ok=True)
    # 纯节点列表文件
    with open("output/proxies.yaml", "w", encoding="utf-8") as f:
        yaml.dump({"proxies": proxies}, f, allow_unicode=True, default_flow_style=False)
    
    # 完整配置文件（带自动选择组）
    config = {
        "port": 7890,
        "socks-port": 7891,
        "external-controller": "127.0.0.1:9090",
        "proxies": proxies,
        "proxy-groups": [
            {
                "name": "🚀 自动选择",
                "type": "url-test",
                "url": "http://cp.cloudflare.com/generate_204",
                "interval": 300,
                "proxies": [p["name"] for p in proxies]
            },
            {
                "name": "🔰 节点选择",
                "type": "select",
                "proxies": ["🚀 自动选择"] + [p["name"] for p in proxies]
            }
        ],
        "rules": ["MATCH,🔰 节点选择"]
    }
    with open("output/config.yaml", "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

if __name__ == "__main__":
    raw_proxies = fetch_proxies()
    if not raw_proxies:
        print("未获取到任何节点，任务结束")
        exit()

    save_for_clash(raw_proxies)
    clash_process = start_clash()
    
    try:
        good_proxies = filter_proxies(raw_proxies)
        final_save(good_proxies)
        print(f"✅ 任务完成！筛选出 {len(good_proxies)} 个优质节点。")
    finally:
        clash_process.terminate() # 确保 Clash 进程被杀掉
        print("Clash 已关闭")
