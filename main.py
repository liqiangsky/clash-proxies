import re
import requests
import yaml
import time
import subprocess
import socket
import os
import urllib3
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

# 禁用 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 订阅地址列表
URLS = [
    #"https://165.154.105.225/clash/proxies",
    #"https://pp.dcd.one/clash/proxies",
    #"http://138.2.112.136:12580/clash/proxies",
    #"http://tmac.eu.org:12580/clash/proxies",
    #"http://ql.ethanyang.top:12580/clash/proxies",
    #"https://open.tidnotes.top:2083/clash/proxies",
    #"http://xqz0.vip:15580/clash/proxies",
    #"https://vahid.ehsandigik.ir/clash",
    "https://chromego-sub.netlify.app/sub/merged_proxies_new.yaml",
    #"https://raw.githubusercontent.com/ripaojiedian/freenode/main/clash",
    #"https://raw.githubusercontent.com/shaoyouvip/free/refs/heads/main/all.yaml",
    #"https://raw.githubusercontent.com/free18/v2ray/refs/heads/main/c.yaml",
    #"https://raw.githubusercontent.com/go4sharing/sub/main/sub.yaml",
    #"https://raw.githubusercontent.com/qjlxg/aggregator/main/data/clash.yaml",
    #"https://raw.githubusercontent.com/Ruk1ng001/freeSub/main/clash.yaml",
    #"https://raw.githubusercontent.com/snakem982/proxypool/main/source/clash-meta.yaml",
    #"https://raw.githubusercontent.com/mfbpn/tg_mfbpn_sub/main/trial.yaml",
    #"https://raw.githubusercontent.com/Barabama/FreeNodes/main/nodes/yudou66.yaml",
    #"https://raw.githubusercontent.com/dongchengjie/airport/refs/heads/main/subs/merged/tested_within.yaml",
    #"https://raw.githubusercontent.com/chengaopan/AutoMergePublicNodes/refs/heads/master/list.meta.yml",
]

HEADERS = {"User-Agent": "Clash/1.0.0"}

# 地区映射表
COUNTRY_NAMES = {
    "HK": "香港", "JP": "日本", "KR": "韩国", "TW": "台湾", "US": "美国", 
    #"GB": "英国", "DE": "德国", "SG": "新加坡",
    #"FR": "法国", "NL": "荷兰", "RU": "俄罗斯", "IT": "意大利",
    #"CA": "加拿大", "AU": "澳大利亚", "TR": "土耳其", "IN": "印度",
    #"TH": "泰国", "MY": "马来西亚", "VN": "越南", "PH": "菲律宾"
}

ALLOW_COUNTRIES = set(COUNTRY_NAMES.keys())
TEST_URL = "https://gemini.google.com"
TEST_URL = "http://www.google.com/generate_204"
MAX_DELAY = 2000  # 最大可接受延迟 (ms)

# 线程池配置（激进提速版）
FETCH_WORKERS = 10
FETCH_TIMEOUT = 8
IP_WORKERS = 15       # 提高并发，接近 ip-api 45/min 限流边缘
TEST_WORKERS = 80     # 充分利用 GitHub Action 带宽

# 线程安全的 IP 缓存
import threading
ip_cache = {}
ip_cache_lock = threading.Lock()

def get_country(ip):
    with ip_cache_lock:
        if ip in ip_cache:
            return ip_cache[ip]
    try:
        r = requests.get(f"http://ip-api.com/json/{ip}", timeout=3)
        code = r.json().get("countryCode")
        with ip_cache_lock:
            ip_cache[ip] = code
        return code
    except:
        return None

def get_country_batch(ip_list, max_workers=IP_WORKERS):
    results = {}
    def query(ip):
        return (ip, get_country(ip))
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for future in as_completed(ex.submit(query, ip) for ip in ip_list):
            try:
                ip, country = future.result()
                if country:
                    results[ip] = country
            except:
                pass
    return results

def make_unique_name(country_code, index):
    base_name = COUNTRY_NAMES.get(country_code, country_code)
    return f"{base_name} {index:02d}"

def manual_parse_proxies(text):
    proxies = []
    pattern = re.compile(r'- name: (.*?)\n\s+server: (.*?)\n\s+port: (\d+)\n\s+type: vmess\n\s+uuid: (.*?)\n', re.S)
    matches = pattern.findall(text)
    for m in matches:
        try:
            name = m[0].strip()
            search_range = text[text.find(name):text.find(name)+500]
            path_match = re.search(r'path: (.*?)\n', search_range)
            host_match = re.search(r'host: (.*?)\n', search_range)
            p = {
                "name": name,
                "server": m[1].strip(),
                "port": int(m[2]),
                "type": "vmess",
                "uuid": m[3].strip(),
                "alterId": 0,
                "cipher": "auto",
                "tls": True,
                "network": "ws",
                "udp": True,
                "ws-opts": {
                    "path": path_match.group(1).strip() if path_match else "/",
                    "headers": {"Host": host_match.group(1).strip() if host_match else m[1].strip()}
                }
            }
            proxies.append(p)
        except:
            continue
    return proxies

def fetch_single_url(url):
    print(f"正在获取：{url}")
    try:
        resp = requests.get(url, headers=HEADERS, timeout=FETCH_TIMEOUT, verify=False)
        resp.encoding = 'utf-8'
        text = resp.text
        if "<html" in text.lower():
            print(f"跳过（HTML 页面）: {url}")
            return []
        current_source_proxies = []
        try:
            data = yaml.safe_load(text)
            if data and "proxies" in data:
                current_source_proxies = data["proxies"]
        except Exception as e:
            print(f"⚠️ YAML 解析失败，启动暴力提取：{url}")
            current_source_proxies = manual_parse_proxies(text)
        if not current_source_proxies:
            print(f"未能从源提取到任何节点：{url}")
            return []
        return current_source_proxies
    except Exception as e:
        print(f"获取失败：{url} -> {e}")
        return []

def fetch_proxies():
    all_proxies = []
    seen_addr = set()

    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as ex:
        futures = [ex.submit(fetch_single_url, url) for url in URLS]
        for future in as_completed(futures):
            try:
                proxies = future.result()
                all_proxies.extend(proxies)
            except:
                pass

    print(f"获取完成，原始节点总数：{len(all_proxies)}")

    cleaned_proxies = []
    country_counters = {c: 1 for c in ALLOW_COUNTRIES}
    server_to_resolve = []
    server_country_map = {}

    for p in all_proxies:
        # 清洗 ALPN 格式
        if "alpn" in p:
            val = p["alpn"]
            if isinstance(val, str):
                p["alpn"] = [x.strip() for x in val.split(',') if x.strip()]
            elif not isinstance(val, list):
                p.pop("alpn")

        # 深度清理空配置项
        for opt_key in ["ws-opts", "grpc-opts", "http-opts"]:
            if opt_key in p:
                if not p[opt_key] or not isinstance(p[opt_key], dict):
                    p.pop(opt_key)
                else:
                    if "headers" in p[opt_key] and not p[opt_key]["headers"]:
                        p[opt_key].pop("headers")
                    if not p[opt_key]:
                        p.pop(opt_key)

        # 强制端口为整数
        if "port" in p:
            try:
                p["port"] = int(p["port"])
            except:
                continue

        # 清理无意义字段
        for useless_key in ["fp", "pbk", "headerType", "sid"]:
            p.pop(useless_key, None)

        server = p.get("server")
        port = p.get("port")
        if not server or not port:
            continue

        addr = f"{server}:{port}"
        if addr in seen_addr:
            continue

        seen_addr.add(addr)

        if server not in server_country_map:
            server_to_resolve.append(server)

        cleaned_proxies.append(p)

    print(f"清洗去重后：{len(cleaned_proxies)} 个节点")
    print(f"正在查询 {len(server_to_resolve)} 个 IP 的地理位置...")

    server_country_map = get_country_batch(server_to_resolve, max_workers=IP_WORKERS)

    final_proxies = []
    for p in cleaned_proxies:
        server = p.get("server")
        country = server_country_map.get(server)
        if not country or country not in ALLOW_COUNTRIES:
            continue
        p["name"] = make_unique_name(country, country_counters[country])
        country_counters[country] += 1
        final_proxies.append(p)

    print(f"筛选后剩余：{len(final_proxies)} 个节点（待测试）")
    return final_proxies

def test_google_access(name):
    """单次连通性测试 - 提速核心"""
    safe_name = urllib.parse.quote(name)
    url = f"http://127.0.0.1:9090/proxies/{safe_name}/delay"
    try:
        params = {"url": TEST_URL, "timeout": 5000}
        r = requests.get(url, params=params, timeout=7)
        delay = r.json().get("delay", 0)
        if delay > 0 and delay <= MAX_DELAY:
            return (name, delay)
    except:
        pass
    return None

def save_for_clash(proxies):
    config = {
        "mixed-port": 7890,
        "allow-lan": False,
        "mode": "rule",
        "external-controller": "127.0.0.1:9090",
        "proxies": proxies,
        "proxy-groups": [
            {
                "name": "test",
                "type": "select",
                "proxies": [p["name"] for p in proxies]
            }
        ],
        "rules": ["MATCH,test"]
    }
    with open("run.yaml", "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

def start_clash():
    if os.name != 'nt':
        subprocess.run(["chmod", "+x", "./clash"])
    try:
        process = subprocess.Popen(
            ["./clash", "-f", "run.yaml"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return process
    except Exception as e:
        print(f"❌ 无法执行 Clash 命令：{e}")
        return None

def wait_clash():
    for _ in range(30):
        try:
            socket.create_connection(("127.0.0.1", 9090), timeout=1)
            return True
        except:
            time.sleep(1)
    return False

def filter_proxies(proxies):
    if not wait_clash():
        print("错误：Clash 启动失败")
        return []

    results = []
    print("正在进行 Google 连通性测试...")

    with ThreadPoolExecutor(max_workers=TEST_WORKERS) as ex:
        futures = {ex.submit(test_google_access, p["name"]): p["name"] for p in proxies}
        for i, future in enumerate(as_completed(futures), 1):
            try:
                r = future.result()
                if r:
                    results.append(r)
                if i % 50 == 0 or i == len(proxies):
                    print(f"已测试 {i}/{len(proxies)} 个节点，通过：{len(results)}")
            except:
                pass

    valid_names = {r[0] for r in results}
    out = [p for p in proxies if p["name"] in valid_names]

    print(f"测试完成，通过：{len(out)} 个节点")
    return out

if __name__ == "__main__":
    raw = fetch_proxies()
    if not raw:
        print("未找到符合条件的节点")
        exit()

    save_for_clash(raw)
    clash_process = start_clash()

    try:
        good_proxies = filter_proxies(raw)

        os.makedirs("output", exist_ok=True)
        final_data = {"proxies": good_proxies}

        with open("output/proxies.yaml", "w", encoding="utf-8") as f:
            yaml.dump(final_data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

        print(f"成功筛选出 {len(good_proxies)} 个 Google 节点并保存。")
    finally:
        if clash_process:
            clash_process.terminate()
