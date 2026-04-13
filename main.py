import re, requests, yaml, time, subprocess, socket, os, urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 配置
URLS = [
    "https://165.154.105.225/clash/proxies",
    "https://pp.dcd.one/clash/proxies",
    "http://138.2.112.136:12580/clash/proxies",
    #"http://tmac.eu.org:12580/clash/proxies",
    #"http://ql.ethanyang.top:12580/clash/proxies",
    #"https://open.tidnotes.top:2083/clash/proxies",
    #"http://xqz0.vip:15580/clash/proxies",
    #"https://vahid.ehsandigik.ir/clash",
]

TEST_URLS = ["https://www.google.com/generate_204", "https://1.1.1.1/generate_204", "https://youtube.com", "https://www.baidu.com"]
TIMEOUT = 3000
CONCURRENCY = 30

PREFERRED_PROTOCOLS = ["reality", "hysteria2", "tuic", "ss", "trojan"]
PREFERRED_REGIONS = ["HK", "TW", "SG", "JP", "KR"]

def clean_node(p, index):
    if not isinstance(p, dict) or 'type' not in p: return None
    if not p.get('server') or not p.get('port'): return None

    # 先提取原始名称用于地区识别，再重命名
    old_name = p.get('name', '').upper()
    p['name'] = f"{p['type']}_{index:03d}_{p['server'].split('.')[-1]}"
    
    # 地区过滤逻辑移入清洗函数内部，确保能识别原始名称
    if PREFERRED_REGIONS:
        if not any(r in old_name for r in PREFERRED_REGIONS):
            return None
    
    if PREFERRED_PROTOCOLS:
        if not any(proto in p['type'].lower() for proto in PREFERRED_PROTOCOLS):
            return None

    p['udp'] = True
    p['skip-cert-verify'] = True
    for k in ['fp', 'pbk', 'headerType', 'sid']: p.pop(k, None)
    if p.get('tls') and not p.get('sni'): p['sni'] = p['server']
    
    if 'alpn' in p and isinstance(p['alpn'], str):
        p['alpn'] = [x.strip() for x in p['alpn'].split(',') if x.strip()]

    return p

def save_run_config(proxies, for_testing=True):
    # 核心修复：确保所有逗号都是英文半角
    group_name = "PROXY_GROUP"
    config = {
        "mixed-port": 7890,
        "external-controller": "127.0.0.1:9090",
        "mode": "rule",
        "log-level": "silent",
        "proxies": proxies,
        "proxy-groups": [{"name": group_name, "type": "select", "proxies": [p['name'] for p in proxies]}],
        "rules": [f"MATCH,{group_name}"]
    }
    with open("run.yaml", "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, sort_keys=False)

def check_node_via_api(p):
    name_encoded = urllib.parse.quote(p['name'])
    api_url = f"http://127.0.0.1:9090/proxies/{name_encoded}/delay"
    try:
        for test_url in TEST_URLS:
            r = requests.get(api_url, params={"url": test_url, "timeout": TIMEOUT}, timeout=5)
            if r.status_code != 200: return None
        return p
    except: return None

def kill_clash():
    if os.name == 'nt':
        subprocess.run("taskkill /F /IM clash.exe >nul 2>&1", shell=True)
    else:
        subprocess.run("pkill -9 clash >/dev/null 2>&1", shell=True)
        subprocess.run("pkill -9 mihomo >/dev/null 2>&1", shell=True)
    time.sleep(1)

def start_clash():
    kill_clash()
    if os.name != 'nt': subprocess.run(["chmod", "+x", "./clash"])
    return subprocess.Popen(["./clash", "-f", "run.yaml"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def main():
    print(">>> 正在获取订阅...")
    all_raw = []
    for url in URLS:
        try:
            r = requests.get(url, timeout=10, verify=False)
            data = yaml.safe_load(r.text)
            if data and "proxies" in data: all_raw.extend(data["proxies"])
        except: continue

    cleaned = []
    seen = set()
    for i, p in enumerate(all_raw):
        node = clean_node(p, i)
        if node:
            addr = f"{node['server']}:{node['port']}"
            if addr not in seen:
                seen.add(addr)
                cleaned.append(node)

    if not cleaned:
        print("无符合条件节点"); return

    print(f">>> 开始测试 {len(cleaned)} 个节点...")
    save_run_config(cleaned)
    proc = start_clash()
    
    # 等待端口
    for _ in range(10):
        try:
            socket.create_connection(("127.0.0.1", 9090), timeout=1); break
        except: time.sleep(1)

    passed = []
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        futures = [ex.submit(check_node_via_api, p) for p in cleaned]
        for f in as_completed(futures):
            res = f.result()
            if res: passed.append(res)

    proc.terminate()
    kill_clash()

    print(f">>> 测试完成，可用节点：{len(passed)}")
    if passed:
        os.makedirs("output", exist_ok=True)
        # 导出 proxies.yaml
        with open("output/proxies.yaml", "w", encoding="utf-8") as f:
            yaml.dump({"proxies": passed}, f, allow_unicode=True)
        
        # 导出最终订阅配置
        final_cfg = {
            "mixed-port": 7890,
            "external-controller": "127.0.0.1:9090",
            "mode": "rule",
            "proxies": passed,
            "proxy-groups": [
                {"name": "节点选择", "type": "select", "proxies": ["自动选优", "手动切换"]},
                {"name": "自动选优", "type": "url-test", "proxies": [p['name'] for p in passed], "url": "http://www.gstatic.com/generate_204", "interval": 300},
                {"name": "手动切换", "type": "select", "proxies": [p['name'] for p in passed]}
            ],
            "rules": ["MATCH,节点选择"]
        }
        with open("output/config.yaml", "w", encoding="utf-8") as f:
            yaml.dump(final_cfg, f, allow_unicode=True)

if __name__ == "__main__":
    main()
