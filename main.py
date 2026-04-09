import re
import requests
import yaml
import time
import subprocess
import socket
import os
import urllib3
import urllib.parse
import psutil
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 基础配置 ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

URLS = [
    "https://165.154.105.225/clash/proxies",
    "https://pp.dcd.one/clash/proxies",
    "http://138.2.112.136:12580/clash/proxies",
    "http://tmac.eu.org:12580/clash/proxies",
    "http://ql.ethanyang.top:12580/clash/proxies",
    "https://open.tidnotes.top:2083/clash/proxies",
    "http://xqz0.vip:15580/clash/proxies",
    "https://vahid.ehsandigik.ir/clash",
    "https://chromego-sub.netlify.app/sub/merged_proxies_new.yaml",
    "https://raw.githubusercontent.com/shaoyouvip/free/refs/heads/main/all.yaml",
    "https://raw.githubusercontent.com/free18/v2ray/refs/heads/main/c.yaml",
    "https://raw.githubusercontent.com/go4sharing/sub/main/sub.yaml",
    "https://raw.githubusercontent.com/qjlxg/aggregator/main/data/clash.yaml",
    "https://raw.githubusercontent.com/Ruk1ng001/freeSub/main/clash.yaml",
    "https://raw.githubusercontent.com/snakem982/proxypool/main/source/clash-meta.yaml",
    "https://raw.githubusercontent.com/mfbpn/tg_mfbpn_sub/main/trial.yaml",
    "https://raw.githubusercontent.com/Barabama/FreeNodes/main/nodes/yudou66.yaml",
    "https://raw.githubusercontent.com/dongchengjie/airport/refs/heads/main/subs/merged/tested_within.yaml",
    "https://raw.githubusercontent.com/chengaopan/AutoMergePublicNodes/refs/heads/master/list.meta.yml",
]

HEADERS = {"User-Agent": "Clash/1.0.0"}
COUNTRY_NAMES = {
    "HK": "香港", "JP": "日本", "KR": "韩国", "TW": "台湾", "US": "美国",
    "GB": "英国", "DE": "德国", "SG": "新加坡", "FR": "法国", "NL": "荷兰",
    "RU": "俄罗斯", "IT": "意大利", "CA": "加拿大", "AU": "澳大利亚",
    "TR": "土耳其", "IN": "印度", "TH": "泰国", "MY": "马来西亚", "VN": "越南", "PH": "菲律宾"
}
ALLOW_COUNTRIES = set(COUNTRY_NAMES.keys())
TEST_URL = "https://www.google.com/generate_204"
MAX_DELAY_ROUND1 = 5000  # 第一轮最大延迟 (ms)
MAX_DELAY_ROUND2 = 3000  # 第二轮最大延迟 (ms)
TEST_WORKERS = 100  # 热更新模式下可以提高并发

# 线程池配置
FETCH_WORKERS = 10
FETCH_TIMEOUT = 8
IP_WORKERS = 15

# 线程安全的 IP 缓存
import threading
ip_cache = {}
ip_cache_lock = threading.Lock()

# --- 进程与端口管理 ---

def kill_clash():
    """强制清理残留进程 - 使用 psutil"""
    for proc in psutil.process_iter(['name']):
        try:
            if "clash" in proc.info['name'].lower():
                proc.kill()
        except:
            pass
    time.sleep(1)

def wait_clash():
    """检测 API 端口是否就绪"""
    print("等待 Clash 启动...")
    for i in range(30):
        try:
            with socket.create_connection(("127.0.0.1", 9090), timeout=1):
                print(f"Clash 启动成功，耗时 {i+1} 秒")
                return True
        except:
            if (i + 1) % 5 == 0:
                print(f"已等待 {i+1} 秒...")
            time.sleep(1)
    print("Clash 启动超时")
    return False

def start_clash():
    """启动 Clash - 先生成极简配置"""
    kill_clash()

    # 预生成一个极简配置用于启动
    init_config = {
        "mixed-port": 7890,
        "external-controller": "127.0.0.1:9090",
        "proxies": [{
            "name": "init",
            "type": "ss",
            "server": "1.1.1.1",
            "port": 443,
            "cipher": "aead-aes-128-gcm",
            "password": "test"
        }],
        "rules": ["MATCH,DIRECT"]
    }
    with open("run.yaml", "w", encoding="utf-8") as f:
        yaml.dump(init_config, f, allow_unicode=True, sort_keys=False)

    if os.name != 'nt':
        subprocess.run(["chmod", "+x", "./clash"], check=False)

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

# --- API 交互 ---

def update_config_api(proxies):
    """核心：通过 API 热更新节点列表"""
    url = "http://127.0.0.1:9090/configs"
    payload = {
        "proxies": proxies,
        "proxy-groups": [{
            "name": "test",
            "type": "select",
            "proxies": [p["name"] for p in proxies]
        }],
        "rules": ["MATCH,test"]
    }
    try:
        r = requests.put(url, json=payload, timeout=10)
        return r.status_code in [200, 204]
    except Exception as e:
        print(f"API 更新失败：{e}")
        return False

def test_delay(name, max_delay=MAX_DELAY_ROUND1):
    """测试节点延迟"""
    safe_name = urllib.parse.quote(name)
    url = f"http://127.0.0.1:9090/proxies/{safe_name}/delay"
    try:
        r = requests.get(url, params={"url": TEST_URL, "timeout": max_delay}, timeout=7)
        delay = r.json().get("delay", 0)
        if 0 < delay <= max_delay:
            return (name, delay)
    except:
        pass
    return None

# --- 节点获取与清洗 ---

def get_country(ip):
    """获取 IP 所属国家代码"""
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
    """批量获取 IP 国家代码"""
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
    """生成唯一节点名"""
    base_name = COUNTRY_NAMES.get(country_code, country_code)
    return f"{base_name} {index:02d}"

def manual_parse_proxies(text):
    """暴力提取 VMess 节点"""
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
    """从单个 URL 获取节点"""
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

def clean_proxy(p):
    """清洗单个节点配置"""
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
            return None

    # 清理无意义字段
    for useless_key in ["fp", "pbk", "headerType", "sid"]:
        p.pop(useless_key, None)

    server = p.get("server")
    port = p.get("port")
    if not server or not port:
        return None

    return p

def fetch_proxies():
    """第一步：获取并清洗节点"""
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

    # 清洗 + 去重
    cleaned_proxies = []
    for p in all_proxies:
        p = clean_proxy(p)
        if not p:
            continue
        addr = f"{p['server']}:{p['port']}"
        if addr in seen_addr:
            continue
        seen_addr.add(addr)
        cleaned_proxies.append(p)

    print(f"清洗去重后：{len(cleaned_proxies)} 个节点（待连通性测试）")
    return cleaned_proxies

def resolve_countries(proxies):
    """查询通过测试的节点 IP 地理位置"""
    if not proxies:
        return []

    server_to_resolve = list(set(p["server"] for p in proxies))
    print(f"正在查询 {len(server_to_resolve)} 个通过节点的 IP 地理位置...")
    server_country_map = get_country_batch(server_to_resolve, max_workers=IP_WORKERS)

    country_counters = {c: 1 for c in ALLOW_COUNTRIES}
    final_proxies = []
    for p in proxies:
        server = p.get("server")
        country = server_country_map.get(server)
        if not country or country not in ALLOW_COUNTRIES:
            continue
        p["name"] = make_unique_name(country, country_counters[country])
        country_counters[country] += 1
        final_proxies.append(p)

    print(f"地区筛选后剩余：{len(final_proxies)} 个节点")
    return final_proxies

# --- 筛选逻辑 ---

def run_filter(proxies, max_delay, batch_size=500, all_proxies_dict=None):
    """分批热更新配置并测试"""
    passed = []
    total = len(proxies)
    batches = (total + batch_size - 1) // batch_size

    for i in range(batches):
        batch = proxies[i*batch_size : (i+1)*batch_size]
        print(f">>> 批次 {i+1}/{batches} [{len(batch)} 节点] 更新中...")

        if update_config_api(batch):
            time.sleep(1)  # 给 Clash 预留解析时间
            batch_results = []
            with ThreadPoolExecutor(max_workers=TEST_WORKERS) as ex:
                futures = {ex.submit(test_delay, p["name"], max_delay): p["name"] for p in batch}
                for f in as_completed(futures):
                    res = f.result()
                    if res and res[0] in all_proxies_dict:
                        passed.append(all_proxies_dict[res[0]])
            print(f"当前累计通过：{len(passed)}")
        else:
            print("API 更新失败，跳过该批次")

    return passed

# --- 主程序 ---

if __name__ == "__main__":
    # 第一步：获取并清洗节点
    raw_nodes = fetch_proxies()
    if not raw_nodes:
        print("未找到符合条件的节点")
        exit()

    # 临时命名用于测试
    for idx, p in enumerate(raw_nodes):
        p["name"] = f"tmp_{idx}"

    # 保存全部节点用于后续查询
    all_proxies_dict = {p["name"]: p for p in raw_nodes}

    clash_p = None
    try:
        print(f"启动测试环境...")
        clash_p = start_clash()
        if not wait_clash():
            print("Clash 启动失败，退出")
            exit()

        # 第一轮：快速筛选
        print("\n--- 开始第一轮筛选（宽松条件） ---")
        round1_nodes = run_filter(raw_nodes, MAX_DELAY_ROUND1, batch_size=500, all_proxies_dict=all_proxies_dict)

        if not round1_nodes:
            print("无节点通过第一轮测试")
            exit()

        # 第二轮：严格筛选
        print("\n--- 开始第二轮筛选（严格条件） ---")
        round2_nodes = run_filter(round1_nodes, MAX_DELAY_ROUND2, batch_size=300, all_proxies_dict=all_proxies_dict)

        if not round2_nodes:
            print("无节点通过第二轮测试")
            exit()

        # 第三步：识别地区并保存
        final_nodes = resolve_countries(round2_nodes)

        os.makedirs("output", exist_ok=True)
        with open("output/proxies.yaml", "w", encoding="utf-8") as f:
            yaml.dump({"proxies": final_nodes}, f, allow_unicode=True, sort_keys=False)

        print(f"\n任务完成！最终保留节点：{len(final_nodes)}")

    finally:
        if clash_p:
            clash_p.terminate()
        kill_clash()
        print("测试环境已关闭")
