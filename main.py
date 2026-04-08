import re
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
    "http://xqz0.vip:15580/clash/proxies",
    "https://raw.githubusercontent.com/shaoyouvip/free/refs/heads/main/all.yaml",
    "https://raw.githubusercontent.com/free18/v2ray/refs/heads/main/c.yaml",
    "https://vahid.ehsandigik.ir/clash",
    #"https://dy.reiasu.jp",
    #"https://jd.zhujunlong.eu.org",
    #"https://proxy.525168.xyz",
]

HEADERS = {"User-Agent": "Clash/1.0.0"}

# 地区映射表：确保名字包含 ACL4SSR 识别的关键词
COUNTRY_NAMES = {
    "HK": "香港", "JP": "日本", "SG": "新加坡", "KR": "韩国",
    "TW": "台湾", "US": "美国", "GB": "英国", "DE": "德国"
}
ALLOW_COUNTRIES = set(COUNTRY_NAMES.keys())
# TEST_URL = "https://www.google.com"
TEST_URL = "https://gemini.google.com"

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

def make_unique_name(country_code, index, used_names):
    """
    生成符合 ACL4SSR 正则匹配的名字
    格式：香港 01, 日本 05 等
    """
    base_name = COUNTRY_NAMES.get(country_code, country_code)
    new_name = f"{base_name} {index:02d}"
    return new_name

def manual_parse_proxies(text):
    """
    手动暴力提取节点信息（当 YAML 解析失败时作为兜底）
    """
    proxies = []
    # 提取 vmess 核心字段
    pattern = re.compile(r'- name: (.*?)\n\s+server: (.*?)\n\s+port: (\d+)\n\s+type: vmess\n\s+uuid: (.*?)\n', re.S)
    
    matches = pattern.findall(text)
    for m in matches:
        try:
            name = m[0].strip()
            # 在该节点名字后的 500 字符内寻找 path 和 host
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

def fetch_proxies():
    all_proxies = []
    seen_addr = set()
    country_counters = {c: 1 for c in ALLOW_COUNTRIES}

    for url in URLS:
        print(f"正在获取: {url}")
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15, verify=False)
            resp.encoding = 'utf-8' # 强制 utf-8
            text = resp.text

            if "<html" in text.lower():
                print(f"跳过（HTML页面）: {url}")
                continue

            # 尝试标准 YAML 解析
            current_source_proxies = []
            try:
                # 先尝试清洗掉可能的 YAML 锚点错误
                data = yaml.safe_load(text)
                if data and "proxies" in data:
                    current_source_proxies = data["proxies"]
            except Exception as e:
                print(f"⚠️ YAML标准解析失败，启动暴力提取逻辑: {url}")
                current_source_proxies = manual_parse_proxies(text)

            if not current_source_proxies:
                print(f"未能从源提取到任何节点: {url}")
                continue

            for p in current_source_proxies:
                # --- 新增清洗逻辑 ---
                # --- 智能修复 ALPN 格式 ---
                if "alpn" in p:
                    val = p["alpn"]
                    if isinstance(val, str):
                        # 如果是字符串 "h2,http/1.1"，拆分为列表 ["h2", "http/1.1"]
                        p["alpn"] = [x.strip() for x in val.split(',') if x.strip()]
                    elif not isinstance(val, list):
                        # 如果是其他奇怪类型（如数字、None），直接删除确保不报错
                        p.pop("alpn")

                # --- 删除所有空的配置项 ---
                # --- 深度清理 ws-opts/grpc-opts ---
                for opt_key in ["ws-opts", "grpc-opts", "http-opts"]:
                    if opt_key in p:
                        # 如果该选项下没有任何实际内容，直接删掉整个大项
                        if not p[opt_key] or not isinstance(p[opt_key], dict):
                            p.pop(opt_key)
                        else:
                            # 清理选项内部的空 headers
                            if "headers" in p[opt_key] and not p[opt_key]["headers"]:
                                p[opt_key].pop("headers")
                            # 如果清理完 headers 后这个选项变空了，也删掉
                            if not p[opt_key]:
                                p.pop(opt_key)
                
                # --- 辅助修复：强制端口为整数 ---
                if "port" in p:
                    try:
                        p["port"] = int(p["port"])
                    except:
                        continue # 端口非法直接舍弃该节点

                # --- 辅助修复：清理无意义的空字段 ---
                # 很多乱抓的节点会带这些字段，导致特定版本的 Clash 解析失败
                for useless_key in ["fp", "pbk", "headerType", "sid"]:
                    p.pop(useless_key, None)
                # -------------------
                server = p.get("server")
                port = p.get("port")
                if not server or not port:
                    continue

                addr = f"{server}:{port}"
                if addr in seen_addr:
                    continue

                try:
                    ip = socket.gethostbyname(server)
                    country = get_country(ip)
                except:
                    continue

                if country not in ALLOW_COUNTRIES:
                    continue

                # 保持你原来的改名逻辑
                p["name"] = make_unique_name(country, country_counters[country], None)
                country_counters[country] += 1

                seen_addr.add(addr)
                all_proxies.append(p)

        except Exception as e:
            print(f"获取失败: {url} -> {e}")

    print(f"初步筛选完成，待测试节点数: {len(all_proxies)}")
    return all_proxies

def test_google_access(name):
    safe_name = urllib.parse.quote(name)
    url = f"http://127.0.0.1:9090/proxies/{safe_name}/delay"
    try:
        params = {"url": TEST_URL, "timeout": 5000} # 5秒超时足够了
        r = requests.get(url, params=params, timeout=7)
        delay = r.json().get("delay", 0)
        if delay > 0:
            return (name, delay)
    except:
        pass
    return None

def save_for_clash(proxies):
    """供脚本内部测试使用的临时配置"""
    config = {
        "mode": "global",
        "port": 7890,
        "external-controller": "127.0.0.1:9090",
        "proxies": proxies,
        "proxy-groups": [{"name": "test", "type": "select", "proxies": [p["name"] for p in proxies]}],
        "rules": ["MATCH,test"]
    }
    with open("run.yaml", "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, sort_keys=False, default_style='"')

#def start_clash():
    # 确保 clash 有执行权限
#    if os.name != 'nt':
#        subprocess.run(["chmod", "+x", "./clash"])
#    return subprocess.Popen(["./clash", "-f", "run.yaml"],
#                            stdout=subprocess.DEVNULL,
#                            stderr=subprocess.DEVNULL)

def start_clash():
    if os.name != 'nt':
        subprocess.run(["chmod", "+x", "./clash"])
    
    # 修改这里：捕获输出，方便在 Actions 日志里看到具体报错
    try:
        process = subprocess.Popen(
            ["./clash", "-f", "run.yaml"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        # 打印前几行日志看看有没有报错
        print("--- Clash 启动日志预览 ---")
        for _ in range(5):
            line = process.stdout.readline()
            if line:
                print(line.strip())
        return process
    except Exception as e:
        print(f"❌ 无法执行 Clash 命令: {e}")
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
        print("错误: Clash 启动失败")
        return []

    results = []
    print("正在进行 Google 连通性测试...")
    with ThreadPoolExecutor(max_workers=20) as ex:
        for r in ex.map(test_google_access, [p["name"] for p in proxies]):
            if r:
                results.append(r)

    # 仅保留测试通过的名字
    valid_names = {r[0] for r in results}

    # 过滤列表，保持原名（不把延迟写进名字里！）
    out = [p for p in proxies if p["name"] in valid_names]
    return out

if __name__ == "__main__":
    raw = fetch_proxies()
    if not raw:
        print("未找到符合条件的节点")
        exit()

    save_for_clash(raw)
    # 增加这一行，调试完可以删掉
    with open("run.yaml", "r", encoding="utf-8") as f:
        print("--- 生成的 run.yaml 内容 ---")
        print(f.read())
        print("--- 结束 ---")
    clash_process = start_clash()

    try:
        good_proxies = filter_proxies(raw)

        # 修改点 2: 规范化输出。SubConverter 只需要 proxies 这一层
        os.makedirs("output", exist_ok=True)
        # 这种格式最利于订阅转换器解析
        final_data = {"proxies": good_proxies}

        with open("output/proxies.yaml", "w", encoding="utf-8") as f:
            # 使用 sort_keys=False 保持国家顺序，不乱跳
            yaml.dump(final_data, f, allow_unicode=True, sort_keys=False, default_style='"')

        print(f"成功筛选出 {len(good_proxies)} 个 Google 节点并保存。")
    finally:
        clash_process.terminate()
