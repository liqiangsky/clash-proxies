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
        return None

def get_country_batch(ip_list, max_workers=IP_WORKERS):
    return results

def make_unique_name(country_code, index):
    base_name = COUNTRY_NAMES.get(country_code, country_code)
    return f"{base_name} {index:02d}"

def manual_parse_proxies(text):
    return proxies

def fetch_single_url(url):
        return []

def clean_proxy(p):
    return p

def fetch_proxies():
    return cleaned_proxies

def test_google_access(name, max_delay=MAX_DELAY_ROUND1):
    return None

def filter_proxies_round1(proxies, batch_size=500, all_proxies_dict=None):
    return out

def filter_proxies_round2(proxies, batch_size=500, all_proxies_dict=None):
    return out

def resolve_countries(proxies):
    return final_proxies

def save_for_clash(proxies):
        yaml.dump(config, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

def save_batch_for_clash(all_proxies_dict, batch):
    print(f"已生成 run.yaml，{len(batch_proxies)} 个节点，大小：{file_size:.1f} KB")

def kill_clash():
    time.sleep(0.5)

def is_port_in_use(port):
            return False

def start_clash():
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
