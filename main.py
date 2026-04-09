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

# 地区映射表 - 只保留需要的地区
COUNTRY_NAMES = {
    "HK": "香港", "JP": "日本", "KR": "韩国", "TW": "台湾", "US": "美国",
    "GB": "英国", "DE": "德国", "SG": "新加坡",
    "FR": "法国", "NL": "荷兰", "RU": "俄罗斯", "IT": "意大利",
    "CA": "加拿大", "AU": "澳大利亚", "TR": "土耳其", "IN": "印度",
    "TH": "泰国", "MY": "马来西亚", "VN": "越南", "PH": "菲律宾"
}

ALLOW_COUNTRIES = set(COUNTRY_NAMES.keys())
# 使用国内可访问的测试目标，更贴近实际使用场景
TEST_URL = "https://www.google.com/generate_204"  # Google 204 测试，更轻量
MAX_DELAY_ROUND1 = 5000  # 第一轮最大延迟 (ms) - 较宽松
MAX_DELAY_ROUND2 = 3000  # 第二轮最大延迟 (ms) - 更严格

# 线程池配置
FETCH_WORKERS = 10
FETCH_TIMEOUT = 8
IP_WORKERS = 15
TEST_WORKERS = 80

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
    """第一步：获取并清洗节点（不查 IP）"""
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

def test_google_access(name, max_delay=MAX_DELAY_ROUND1):
    """单次连通性测试"""
    safe_name = urllib.parse.quote(name)
    url = f"http://127.0.0.1:9090/proxies/{safe_name}/delay"
    try:
        params = {"url": TEST_URL, "timeout": 5000}
        r = requests.get(url, params=params, timeout=7)
        delay = r.json().get("delay", 0)
        if delay > 0 and delay <= max_delay:
            return (name, delay)
    except:
        pass
    return None

def reload_clash_config():
    """通知 Clash 重新加载配置文件"""
    try:
        # 使用 PUT /configs 热重载配置
        resp = requests.put(
            "http://127.0.0.1:9090/configs",
            json={"path": "run.yaml"},
            timeout=10
        )
        return resp.status_code == 204
    except Exception as e:
        print(f"重载配置失败：{e}")
        return False

def filter_proxies_round1(proxies, batch_size=500, all_proxies_dict=None):
    """第一轮：快速筛选，宽松条件 - 分批测试避免 Clash 过载"""
    results = []
    total = len(proxies)
    batches = (total + batch_size - 1) // batch_size

    print(f"第一轮筛选（快速测试），共 {batches} 批次...")

    # 启动 Clash（只启动一次）
    print("启动 Clash...")
    global clash_process
    clash_process = start_clash()
    if not wait_clash():
        print("Clash 启动失败，退出")
        return []
    print("Clash 启动成功，开始分批测试...\n")

    for batch_idx in range(batches):
        start = batch_idx * batch_size
        end = min(start + batch_size, total)
        batch = proxies[start:end]
        print(f">>> 第 {batch_idx + 1}/{batches} 批次 [{start}:{end}]")

        # 为当前批次生成精简配置
        save_batch_for_clash(all_proxies_dict, batch)

        # 重载配置（第一批不需要重载，因为启动时已经加载）
        if batch_idx > 0:
            print("重载配置...")
            if not reload_clash_config():
                print("重载失败，重试启动 Clash...")
                clash_process.terminate()
                kill_clash()
                clash_process = start_clash()
                if not wait_clash():
                    print("Clash 重启失败，跳过本批次")
                    continue
            print("配置重载完成")

        batch_results = []
        with ThreadPoolExecutor(max_workers=TEST_WORKERS) as ex:
            futures = {ex.submit(test_google_access, p["name"]): p["name"] for p in batch}
            for i, future in enumerate(as_completed(futures), 1):
                try:
                    r = future.result()
                    if r:
                        batch_results.append(r)
                except:
                    pass

        results.extend(batch_results)
        print(f"本批次通过：{len(batch_results)}/{len(batch)} 个节点\n")

    valid_names = {r[0] for r in results}
    out = [p for p in proxies if p["name"] in valid_names]
    print(f"\n第一轮总计通过：{len(out)}/{total} 个节点")
    return out

def filter_proxies_round2(proxies, batch_size=500, all_proxies_dict=None):
    """第二轮：严格筛选，确保质量 - 分批测试"""
    results = []
    total = len(proxies)
    batches = (total + batch_size - 1) // batch_size

    print(f"\n第二轮筛选（严格测试），共 {batches} 批次...")

    # 启动 Clash（只启动一次）
    print("启动 Clash...")
    global clash_process
    clash_process = start_clash()
    if not wait_clash():
        print("Clash 启动失败，退出")
        return []
    print("Clash 启动成功，开始分批测试...\n")

    for batch_idx in range(batches):
        start = batch_idx * batch_size
        end = min(start + batch_size, total)
        batch = proxies[start:end]
        print(f">>> 第 {batch_idx + 1}/{batches} 批次 [{start}:{end}]")

        # 为当前批次生成精简配置
        save_batch_for_clash(all_proxies_dict, batch)

        # 重载配置（第一批不需要重载，因为启动时已经加载）
        if batch_idx > 0:
            print("重载配置...")
            if not reload_clash_config():
                print("重载失败，重试启动 Clash...")
                clash_process.terminate()
                kill_clash()
                clash_process = start_clash()
                if not wait_clash():
                    print("Clash 重启失败，跳过本批次")
                    continue
            print("配置重载完成")

        batch_results = []
        with ThreadPoolExecutor(max_workers=TEST_WORKERS) as ex:
            futures = {ex.submit(test_google_access, p["name"], MAX_DELAY_ROUND2): p["name"] for p in batch}
            for i, future in enumerate(as_completed(futures), 1):
                try:
                    r = future.result()
                    if r:
                        batch_results.append(r)
                except:
                    pass

        results.extend(batch_results)
        print(f"本批次通过：{len(batch_results)}/{len(batch)} 个节点\n")

    valid_names = {r[0] for r in results}
    out = [p for p in proxies if p["name"] in valid_names]
    print(f"\n第二轮总计通过：{len(out)}/{total} 个节点")
    return out

def resolve_countries(proxies):
    """第三步：只查询通过测试的节点 IP"""
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

def save_for_clash(proxies):
    """生成 Clash 配置 - 只包含当前批次需要的节点"""
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

def save_batch_for_clash(all_proxies_dict, batch):
    """为当前批次生成精简的 Clash 配置"""
    batch_names = {p["name"] for p in batch}
    batch_proxies = [all_proxies_dict[name] for name in batch_names if name in all_proxies_dict]
    save_for_clash(batch_proxies)

    # 打印配置信息
    file_size = os.path.getsize("run.yaml") / 1024
    print(f"已生成 run.yaml，{len(batch_proxies)} 个节点，大小：{file_size:.1f} KB")

def kill_clash():
    """强力清理 Clash 进程"""
    try:
        if os.name == 'nt':
            # 执行两次确保清理
            subprocess.run(["taskkill", "/F", "/IM", "clash.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(0.5)
            subprocess.run(["taskkill", "/F", "/IM", "clash.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.run(["pkill", "-9", "clash"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(0.5)
            subprocess.run(["pkill", "-9", "clash"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except:
        pass
    time.sleep(0.5)

def is_port_in_use(port):
    """检查端口是否被占用"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.settimeout(1)
            result = s.connect_ex(('127.0.0.1', port))
            return result == 0
        except:
            return False

def start_clash():
    # 启动前先确保 9090 端口可用
    if is_port_in_use(9090):
        print("9090 端口被占用，清理旧 Clash 进程...")
        kill_clash()

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
    """等待 Clash 启动，最多等待 30 秒"""
    print("等待 Clash 启动...")
    for i in range(30):
        try:
            socket.create_connection(("127.0.0.1", 9090), timeout=1)
            print(f"Clash 启动成功，耗时 {i+1} 秒")
            return True
        except:
            if (i + 1) % 5 == 0:
                print(f"已等待 {i+1} 秒...")
            time.sleep(1)
    print("Clash 启动超时")
    return False

if __name__ == "__main__":
    # 第一步：获取并清洗节点
    raw = fetch_proxies()
    if not raw:
        print("未找到符合条件的节点")
        exit()

    # 临时命名用于测试
    for i, p in enumerate(raw):
        p["name"] = f"temp_{i}"

    global clash_process
    clash_process = None

    try:
        # 保存全部节点用于后续 IP 查询
        all_proxies_dict = {p["name"]: p for p in raw}

        # 第二步：第一轮快速筛选（宽松条件）- 每批 500 个
        passed_round1 = filter_proxies_round1(raw, batch_size=500, all_proxies_dict=all_proxies_dict)

        if not passed_round1:
            print("第一轮筛选无节点通过，退出")
            exit()

        # 关闭 Clash，准备第二轮
        if clash_process:
            clash_process.terminate()
        kill_clash()
        clash_process = None

        # 第三步：第二轮严格筛选（更严格条件）- 每批 500 个
        passed_round2 = filter_proxies_round2(passed_round1, batch_size=500, all_proxies_dict=all_proxies_dict)

        if not passed_round2:
            print("第二轮筛选无节点通过，退出")
            exit()

        # 第四步：只查询通过两轮测试的节点 IP
        good_proxies = resolve_countries(passed_round2)

        os.makedirs("output", exist_ok=True)
        final_data = {"proxies": good_proxies}

        with open("output/proxies.yaml", "w", encoding="utf-8") as f:
            yaml.dump(final_data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

        print(f"成功筛选出 {len(good_proxies)} 个节点并保存。")
    finally:
        if clash_process:
            clash_process.terminate()
