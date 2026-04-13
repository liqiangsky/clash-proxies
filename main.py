import re, requests, yaml, time, subprocess, socket, os, urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

# 禁用警告
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 配置
URLS = [
    "https://165.154.105.225/clash/proxies",
    "https://pp.dcd.one/clash/proxies",
    "http://138.2.112.136:12580/clash/proxies",
    #"http://tmac.eu.org:12580/clash/proxies",
    #"http://ql.ethanyang.top:12580/clash/proxies",
    #"https://vahid.ehsandigik.ir/clash",
]

# 测试参数
TEST_URLS = ["https://www.google.com/generate_204", "https://1.1.1.1/generate_204", "https://gemini.google.com/", "https://youtube.com"]
TIMEOUT = 3000 # 3秒超时，Actions 环境网络快，要求可以严一点
CONCURRENCY = 30 # Actions 上可以跑很高的并发

def clean_node(p, index):
    """深度清洗并标准化节点配置"""
    if not isinstance(p, dict) or 'type' not in p: return None
    
    # 基础重命名，避免特殊字符导致 API 调用失败
    p['name'] = f"{p['type']}_{index:03d}_{p['server'][-4:]}"
    
    # 强制开启核心功能
    p['udp'] = True
    p['skip-cert-verify'] = True
    
    # 某些 Reality/Hysteria 节点必须有 SNI，如果源码没写，尝试补全
    if 'tls' in p and p['tls'] and not p.get('sni'):
        p['sni'] = p['server']
        
    return p

def save_run_config(proxies):
    """生成测试专用的 Mihomo 配置"""
    config = {
        "mixed-port": 7890,
        "external-controller": "127.0.0.1:9090",
        "mode": "rule",
        "log-level": "silent",
        "proxies": proxies,
        "proxy-groups": [{"name": "GLOBAL", "type": "select", "proxies": [p['name'] for p in proxies]}],
        "rules": ["MATCH,GLOBAL"]
    }
    with open("run.yaml", "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, sort_keys=False)

def check_node_via_api(p):
    """通过 Mihomo API 进行并发测速"""
    name_encoded = urllib.parse.quote(p['name'])
    api_url = f"http://127.0.0.1:9090/proxies/{name_encoded}/delay"
    
    try:
        # 必须通过两个 URL 的验证才算真有效
        for t_url in TEST_URLS:
            r = requests.get(api_url, params={"url": t_url, "timeout": TIMEOUT}, timeout=5)
            if r.status_code != 200:
                return None
        
        delay = r.json().get('delay', 0)
        return p, delay
    except:
        return None

def main():
    print(">>> 正在抓取订阅源...")
    all_raw = []
    for url in URLS:
        try:
            r = requests.get(url, timeout=10, verify=False)
            data = yaml.safe_load(r.text)
            if data and 'proxies' in data:
                all_raw.extend(data['proxies'])
        except: continue

    # 清洗去重
    cleaned = []
    seen_ips = set()
    for i, p in enumerate(all_raw):
        node = clean_node(p, i)
        if node:
            key = f"{node['server']}:{node['port']}"
            if key not in seen_ips:
                seen_ips.add(key)
                cleaned.append(node)

    print(f">>> 共有 {len(cleaned)} 个节点进入测试阶段")
    save_run_config(cleaned)

    # 启动 Mihomo
    print(">>> 启动内核测试...")
    proc = subprocess.Popen(["./clash", "-f", "run.yaml"])
    
    # 等待内核初始化和端口开放
    for _ in range(10):
        try:
            socket.create_connection(("127.0.0.1", 9090), timeout=1)
            break
        except: time.sleep(1)

    # 并发测试
    passed = []
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
        futures = [executor.submit(check_node_via_api, p) for p in cleaned]
        for f in as_completed(futures):
            res = f.result()
            if res:
                p, delay = res
                passed.append(p)
                print(f"  [PASS] {p['name']} - {delay}ms")

    # 善后处理
    proc.terminate()
    print(f">>> 测试完成，最终可用节点: {len(passed)}")

    if passed:
        os.makedirs("output", exist_ok=True)
        # 再次处理最终导出的格式，确保兼容性
        with open("output/proxies.yaml", "w", encoding="utf-8") as f:
            yaml.dump({"proxies": passed}, f, allow_unicode=True, sort_keys=False)
        
        # 生成一个通用的 config.yaml 供客户端直接订阅
        final_cfg = {
            "mixed-port": 7890,
            "external-controller": "127.0.0.1:9090",
            "mode": "rule",
            "proxies": passed,
            "proxy-groups": [
                {"name": "🚀 自动选择", "type": "url-test", "proxies": [p['name'] for p in passed], "url": "http://www.gstatic.com/generate_204", "interval": 300},
                {"name": "手动切换", "type": "select", "proxies": [p['name'] for p in passed]}
            ],
            "rules": ["MATCH,🚀 自动选择"]
        }
        with open("output/config.yaml", "w", encoding="utf-8") as f:
            yaml.dump(final_cfg, f, allow_unicode=True, sort_keys=False)

if __name__ == "__main__":
    main()
