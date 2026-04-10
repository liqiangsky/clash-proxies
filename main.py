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
]

HEADERS = {"User-Agent": "Clash/1.0.0"}

# ========== 组合测试配置：提高中国大陆可用性 ==========

# 测试目标：只测试访问外网能力
FOREIGN_TEST_URL = "https://www.google.com/generate_204"

# 出口 IP 检测：查询节点的真实出口 IP，判断是否被 GFW 封锁
# 原理：GFW 会封锁某些 IP 段，即使是海外节点，如果 IP 在被封锁段内也无法使用
ENABLE_IP_CHECK = True  # 是否启用出口 IP 检测
IP_CHECK_URL = "https://api.ip.sb/ip"  # 返回纯文本 IP 地址
# IP_CHECK_URL = "https://api.ipify.org"  # 备选

# 过滤规则：以下情况会被过滤
BLOCKED_CN_IP_PREFIXES = []  # 中国大陆 IP 段前缀（如果被节点出口 IP 匹配则过滤）
# 示例：["103.", "104."] 等可根据实际情况添加

# 优选地区（基于出口 IP 的 GeoIP 信息）
PREFERRED_REGIONS = ["HK", "TW", "SG", "JP", "KR"]  # 留空则不过滤，可填 ["HK", "TW", "SG", "JP", "KR"]

# 优选协议列表
PREFERRED_PROTOCOLS = ["reality", "hysteria2", "tuic", "ss", "trojan"]  # 留空则不过滤，可填 ["reality", "hysteria2", "tuic", "ss", "trojan"]

# 连续测试次数 - 检测稳定性（设置为 1 则只测一次）
CONTINUOUS_TEST_COUNT = 3  # 提高到 3，连续 3 次请求都成功才算通过，确保稳定性

# 延迟阈值 (ms)
MAX_DELAY = 5000

# 5 轮过滤延迟阈值 (ms) - 逐步收紧
MAX_DELAY_ROUNDS = [5000, 3000, 2000, 1000, 500]  # 从宽松到严格

# 线程池配置
FETCH_WORKERS = 10
FETCH_TIMEOUT = 8
TEST_WORKERS = 1  # 降低到 1，避免多线程切换节点时结果互相污染（"张冠李戴"）

# 批次大小配置
BATCH_SIZE = 500  # 每批次节点数

# ========== Cloudflare Trace 检测：免费无限制 ==========

# 启用 Cloudflare Trace 检测（推荐启用）
# 原理：让节点访问 1.1.1.1/cdn-cgi/trace，根据返回的机场代码（colo）判断节点位置
# 亚洲近岸节点（HKG/SGP/NRT 等）通常比美西节点（LAX/SJC）在中国大陆可用性更高
# 完全免费，无频率限制，走节点自己流量
ENABLE_CF_TRACE = True

# 优选机场代码列表（留空则不过滤）
# 常见机场代码：
#   亚洲近岸：HKG(香港), TPE(台北), SIN(新加坡), NRT(东京), KIX(大阪), ICN(首尔), MNL(马尼拉)
#   美西（相对较好）：LAX(洛杉矶), SJC(圣何塞), SEA(西雅图), YVR(温哥华), SFO(旧金山)
#   美东（通常较差）：JFK(纽约), EWR(纽瓦克), IAD(华盛顿), ORD(芝加哥)
# 建议只保留亚洲近岸，因为美西节点虽然有时能用但不稳定
PREFERRED_COLOS = ["HKG", "TPE", "SIN", "NRT", "KIX", "ICN"]

# Cloudflare Trace 检测 URL
# 如果 1.1.1.1 被当地网络封锁，可改用 cloudflare.com
CF_TRACE_URL = "https://1.1.1.1/cdn-cgi/trace"
# CF_TRACE_URL = "https://cloudflare.com/cdn-cgi/trace"

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

def validate_reality_opts(p):
    """验证 reality-opts 配置格式"""
    reality_opts = p.get("reality-opts")
    if not reality_opts or not isinstance(reality_opts, dict):
        return False

    # 验证 sid 格式：必须是 8 字节十六进制字符串（16 个字符）
    sid = reality_opts.get("sid", "")
    if not sid or not isinstance(sid, str) or len(sid) != 16:
        return False
    if not all(c in "0123456789abcdefABCDEF" for c in sid):
        return False

    # 验证 public-key 格式：必须是有效的 base64 公钥
    pbk = reality_opts.get("public-key", "")
    if not pbk or not isinstance(pbk, str) or len(pbk) < 32:
        return False

    return True


def validate_hysteria_opts(p):
    """验证 hysteria/hysteria2 配置格式"""
    # Hysteria 节点需要验证 port-hopping、hop-interval 等字段
    # TODO: 根据实际需求添加验证逻辑
    pass


def validate_tuic_opts(p):
    """验证 TUIC 配置格式"""
    # TUIC 节点需要验证 uuid、alpn 等字段
    # TODO: 根据实际需求添加验证逻辑
    pass


def get_node_colo_single(p, group_name="test"):
    """
    单节点 CF Trace 检测，用于线程池并发调用

    Args:
        p: 节点配置字典
        group_name: Clash 中的代理组名称

    Returns:
        tuple: (name, colo) 节点名和机场代码，检测失败返回 (name, None)
    """
    name = p.get("name")
    if not name:
        return name, None

    try:
        # 1. 切换到目标节点
        safe_name = urllib.parse.quote(name)
        selector_url = f"http://127.0.0.1:9090/proxies/{urllib.parse.quote(group_name)}"
        requests.put(selector_url, json={"name": name}, timeout=3)
        time.sleep(0.2)  # 等待切换生效

        # 2. 通过 Clash 代理访问 CF Trace
        proxies_req = {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}
        r = requests.get(CF_TRACE_URL, proxies=proxies_req, timeout=5)

        if r.status_code == 200:
            # 解析 colo
            for line in r.text.split("\n"):
                if line.startswith("colo="):
                    colo = line.split("=")[1].strip().upper()
                    return name, colo

        return name, None

    except Exception as e:
        return name, None


def filter_by_colo_round(proxies):
    """
    CF Trace 检测轮次（在第 1 轮 Clash 测试后执行）
    使用并发检测提高效率
    """
    if not ENABLE_CF_TRACE or not PREFERRED_COLOS:
        return proxies

    print(f"\n========== Cloudflare Trace: 检测节点出口位置 ==========")
    print(f"优选机场：{PREFERRED_COLOS}")
    print(f"待测节点数：{len(proxies)}，并发数：1（串行避免干扰）")

    # 生成测试配置（组名为 "节点选择"）
    print("生成测试配置...")
    save_for_clash(proxies, for_testing=True)
    group_name = "节点选择"

    # 启动 Clash
    print("启动 Clash...")
    clash_proc = start_clash()
    if not wait_clash(clash_proc):
        print("Clash 启动失败，跳过 CF Trace 检测")
        return proxies

    # 并发检测（并发数设为 1，确保节点切换不互相干扰）
    detected_map = {}
    print(f"开始检测 {len(proxies)} 个节点的出口位置...")

    with ThreadPoolExecutor(max_workers=1) as executor:
        futures = [executor.submit(get_node_colo_single, p, group_name) for p in proxies]
        for i, future in enumerate(as_completed(futures), 1):
            try:
                name, colo = future.result()
                detected_map[name] = colo
                if colo:
                    status = "✓" if colo in PREFERRED_COLOS else "✗"
                    print(f"  [{i}/{len(proxies)}] {name} -> {colo} {status}")
                else:
                    print(f"  [{i}/{len(proxies)}] {name} -> 检测失败")
            except Exception as e:
                pass

    # 统计机场分布
    colo_count = {}
    for name, colo in detected_map.items():
        if colo:
            colo_count[colo] = colo_count.get(colo, 0) + 1

    if colo_count:
        print(f"\n机场分布统计：{dict(sorted(colo_count.items(), key=lambda x: -x[1]))}")

    # 过滤节点：优选机场 + 检测失败（保留避免误删）
    filtered = []
    skipped = 0
    for p in proxies:
        name = p["name"]
        colo = detected_map.get(name)
        if colo:
            if colo in PREFERRED_COLOS:
                filtered.append(p)
            else:
                skipped += 1
        else:
            # 检测失败也保留
            filtered.append(p)

    print(f"\nCF Trace 过滤：{len(filtered)}/{len(proxies)} 个节点（跳过 {skipped} 个非优选机场）")

    # 关闭 Clash
    clash_proc.terminate()
    kill_clash()

    return filtered


def clean_proxy(p):
    """清洗单个节点配置"""
    proxy_type = p.get("type", "")

    # 清洗 ALPN 格式
    if "alpn" in p:
        val = p["alpn"]
        if isinstance(val, str):
            p["alpn"] = [x.strip() for x in val.split(',') if x.strip()]
        elif not isinstance(val, list):
            p.pop("alpn")

    # 深度清理空配置项
    for opt_key in ["ws-opts", "grpc-opts", "http-opts", "plugin-opts"]:
        if opt_key in p:
            if not p[opt_key] or not isinstance(p[opt_key], dict):
                p.pop(opt_key)
            else:
                # 特殊处理 plugin-opts 中的 mux 字段（必须是布尔值）
                if opt_key == "plugin-opts" and "mux" in p[opt_key]:
                    mux_val = p[opt_key]["mux"]
                    # 将数字 0/1 转换为 false/true
                    if isinstance(mux_val, int):
                        p[opt_key]["mux"] = mux_val != 0
                    elif not isinstance(mux_val, bool):
                        p[opt_key].pop("mux", None)

                if "headers" in p[opt_key]:
                    headers = p[opt_key]["headers"]
                    if not headers or not isinstance(headers, dict):
                        p[opt_key].pop("headers")
                    else:
                        # 清理 headers 中非字符串的值
                        for k in list(headers.keys()):
                            v = headers[k]
                            if not v or not isinstance(v, str):
                                headers.pop(k)
                        if not headers:
                            p[opt_key].pop("headers")
                if not p[opt_key]:
                    p.pop(opt_key)

    # 按协议类型验证配置
    if proxy_type == "reality" or "reality-opts" in p:
        if not validate_reality_opts(p):
            p.pop("reality-opts", None)

    elif proxy_type in ["hysteria", "hysteria2"]:
        validate_hysteria_opts(p)

    elif proxy_type == "tuic":
        validate_tuic_opts(p)

    # 清理无意义字段（顶层）
    for useless_key in ["fp", "pbk", "headerType", "sid"]:
        p.pop(useless_key, None)

    # 强制端口为整数
    if "port" in p:
        try:
            p["port"] = int(p["port"])
        except (ValueError, TypeError):
            return None

    server = p.get("server")
    port = p.get("port")
    if not server or not port:
        return None

    return p

def fetch_proxies():
    """第一步：获取并清洗节点，统一重命名"""
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

    # 清洗 + 去重 + 统一重命名
    cleaned_proxies = []
    name_counter = {}  # 记录每个基础名称的出现次数

    for p in all_proxies:
        p = clean_proxy(p)
        if not p:
            continue
        addr = f"{p['server']}:{p['port']}"
        if addr in seen_addr:
            continue
        seen_addr.add(addr)

        # 统一重命名：基于原始名称 + 序号
        original_name = p.get("name", "Unnamed")
        if original_name in name_counter:
            name_counter[original_name] += 1
            p["name"] = f"{original_name}_{name_counter[original_name]}"
        else:
            name_counter[original_name] = 0

        cleaned_proxies.append(p)

    print(f"清洗去重后：{len(cleaned_proxies)} 个节点")
    return cleaned_proxies

def test_proxy_continuous(name, test_url=FOREIGN_TEST_URL, count=CONTINUOUS_TEST_COUNT, max_delay=MAX_DELAY):
    """
    连续连通性测试 - 通过节点发起真实 HTTP 请求，避免 ICMP 假延迟

    原理：
    1. 通过 Clash API 切换到目标节点
    2. 通过 Clash 代理访问 Google 204，根据实际 HTTP 响应时间判断
    这比 ICMP Ping 更准确，因为测试的是真实 TCP 连接 + HTTP 响应
    """
    safe_name = urllib.parse.quote(name)
    selector_url = "http://127.0.0.1:9090/proxies/节点选择"
    proxies_req = {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}

    success_count = 0
    total_delay = 0

    for attempt in range(count):
        try:
            # 1. 切换到目标节点
            requests.put(selector_url, json={"name": name}, timeout=3)
            time.sleep(0.1)  # 等待切换生效

            # 2. 通过 Clash 代理发起真实 HTTP 请求
            start_time = time.time()
            r = requests.get(test_url, proxies=proxies_req, timeout=5, verify=False)
            elapsed = int((time.time() - start_time) * 1000)  # 转换为毫秒

            # 检查响应状态（Google 204 返回 204 或 200 都算成功）
            if r.status_code in [200, 204, 301, 302]:
                if elapsed > 0 and elapsed <= max_delay:
                    success_count += 1
                    total_delay += elapsed
                else:
                    return None  # 延迟超标
            else:
                return None  # 状态码异常
        except Exception as e:
            return None  # 请求失败

        if attempt < count - 1:
            time.sleep(0.5)  # 缩短间隔

    # 返回平均延迟
    avg_delay = total_delay // success_count if success_count > 0 else 9999
    return (name, avg_delay)


def get_proxy_exit_ip(name):
    """查询节点的出口 IP"""
    safe_name = urllib.parse.quote(name)
    url = f"http://127.0.0.1:9090/proxies/{safe_name}/delay"

    try:
        # 通过节点访问 IP 查询服务
        params = {"url": IP_CHECK_URL, "timeout": 5000}
        r = requests.get(url, params=params, timeout=8)
        result = r.json()
        delay = result.get("delay", 0)
        if delay > 0 and delay <= MAX_DELAY:
            # 如果成功返回，说明节点可用
            return True, delay
        return False, 0
    except:
        return False, 0


def is_ip_blocked(ip):
    """检查 IP 是否在被封锁的段内"""
    if not BLOCKED_CN_IP_PREFIXES:
        return False
    for prefix in BLOCKED_CN_IP_PREFIXES:
        if ip.startswith(prefix):
            return True
    return False


def filter_by_protocol_and_region(proxies):
    """按协议和地区过滤节点"""
    if not PREFERRED_PROTOCOLS and not PREFERRED_REGIONS:
        return proxies

    filtered = []
    for p in proxies:
        proxy_type = p.get("type", "")
        country = p.get("country", "")

        if PREFERRED_PROTOCOLS:
            type_match = False
            for proto in PREFERRED_PROTOCOLS:
                if proto in proxy_type.lower():
                    type_match = True
                    break
            if not type_match:
                continue

        if PREFERRED_REGIONS:
            region_match = False
            name = p.get("name", "").upper()
            country_upper = country.upper()
            for region in PREFERRED_REGIONS:
                if region in country_upper or region in name:
                    region_match = True
                    break
            if not region_match:
                continue

        filtered.append(p)

    print(f"协议/地区过滤后：{len(filtered)} 个节点")
    return filtered


def filter_proxies_round(proxies, batch_size=None, max_delay=MAX_DELAY_ROUNDS[0], round_num=1):
    """通用单轮筛选函数"""
    # 第 1 轮前先做协议和地区过滤
    if round_num == 1:
        print(f"\n优选协议：{PREFERRED_PROTOCOLS if PREFERRED_PROTOCOLS else '不过滤'}")
        print(f"优选地区：{PREFERRED_REGIONS if PREFERRED_REGIONS else '不过滤'}")
        proxies = filter_by_protocol_and_region(proxies)
        if not proxies:
            print("没有节点符合协议/地区要求")
            return []

    if batch_size is None:
        batch_size = BATCH_SIZE
    results = []
    total = len(proxies)
    batches = (total + batch_size - 1) // batch_size

    print(f"\n第{round_num}轮筛选（延迟 ≤ {max_delay}ms，连续{CONTINUOUS_TEST_COUNT}次），共 {batches} 批次...")

    for batch_idx in range(batches):
        start = batch_idx * batch_size
        end = min(start + batch_size, total)
        batch = proxies[start:end]
        print(f"\n>>> 第 {batch_idx + 1}/{batches} 批次 [{start}:{end}]")

        # 为当前批次生成精简配置
        save_batch_for_clash(batch)

        # 启动 Clash 加载新配置
        print("启动 Clash...")
        clash_proc = start_clash()
        if not wait_clash(clash_proc):
            print("Clash 启动失败")
            return []

        batch_results = []
        with ThreadPoolExecutor(max_workers=TEST_WORKERS) as ex:
            futures = {ex.submit(test_proxy_continuous, p["name"]): p["name"] for p in batch}
            for i, future in enumerate(as_completed(futures), 1):
                try:
                    r = future.result()
                    if r:
                        batch_results.append(r)
                except:
                    pass

        results.extend(batch_results)
        print(f"本批次通过：{len(batch_results)}/{len(batch)} 个节点")

        # 测试完当前批次后关闭 Clash - 使用强力清理
        if clash_proc:
            clash_proc.terminate()
        kill_clash()

    valid_names = {r[0] for r in results}
    out = [p for p in proxies if p["name"] in valid_names]
    print(f"\n第{round_num}轮总计通过：{len(out)}/{total} 个节点")
    return out


def save_for_clash(proxies, for_testing=False):
    """生成 Clash 配置"""
    if for_testing:
        # 测试模式：所有节点放在一个组里
        config = {
            "mixed-port": 7890,
            "allow-lan": False,
            "mode": "rule",
            "external-controller": "127.0.0.1:9090",
            "proxies": proxies,
            "proxy-groups": [
                {
                    "name": "节点选择",
                    "type": "select",
                    "proxies": [p["name"] for p in proxies]
                }
            ],
            "rules": ["MATCH，节点选择"]
        }
    else:
        # 最终输出模式：添加 url-test 自动选择组
        config = {
            "mixed-port": 7890,
            "allow-lan": False,
            "mode": "rule",
            "external-controller": "127.0.0.1:9090",
            "proxies": proxies,
            "proxy-groups": [
                {
                    "name": "AUTO",
                    "type": "url-test",
                    "proxies": [p["name"] for p in proxies],
                    "url": "https://www.google.com/generate_204",
                    "interval": 300,
                    "tolerance": 50
                },
                {
                    "name": "手动选择",
                    "type": "select",
                    "proxies": [p["name"] for p in proxies]
                }
            ],
            "rules": ["MATCH,AUTO"]
        }
    with open("run.yaml", "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

def save_batch_for_clash(batch):
    """为当前批次生成精简的 Clash 配置"""
    # 过滤掉无效节点（名称已在 fetch_proxies 中统一处理，保证唯一）
    valid_batch = [p for p in batch if p.get("server") and p.get("port")]
    save_for_clash(valid_batch)
    file_size = os.path.getsize("run.yaml") / 1024
    skipped = len(batch) - len(valid_batch)
    print(f"已生成 run.yaml，{len(valid_batch)} 个节点{' (跳过 ' + str(skipped) + ' 个无效节点)' if skipped else ''}，大小：{file_size:.1f} KB")


def save_final_config(proxies):
    """生成带 url-test 自动选择的完整配置文件"""
    config = {
        "mixed-port": 7890,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "info",
        "external-controller": "127.0.0.1:9090",
        "proxies": proxies,
        "proxy-groups": [
            {
                "name": "节点选择",
                "type": "select",
                "proxies": ["AUTO", "手动选择"] + [p["name"] for p in proxies[:20]]
            },
            {
                "name": "AUTO",
                "type": "url-test",
                "proxies": [p["name"] for p in proxies],
                "url": "https://www.google.com/generate_204",
                "interval": 300,
                "tolerance": 50
            },
            {
                "name": "手动选择",
                "type": "select",
                "proxies": [p["name"] for p in proxies]
            }
        ],
        "rules": [
            "GEOIP,CN,DIRECT",
            "MATCH,节点选择"
        ]
    }
    with open("output/config.yaml", "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    print(f"已生成完整配置文件：output/config.yaml")


def kill_clash():
    """强力清理 Clash 进程"""
    try:
        if os.name == 'nt':
            subprocess.run(["taskkill", "/F", "/IM", "clash.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(0.5)
            subprocess.run(["taskkill", "/F", "/IM", "clash.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            # Linux 环境下更彻底的清理
            subprocess.run(["pkill", "-9", "clash"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(0.5)
            subprocess.run(["pkill", "-9", "mihomo"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(0.5)
            # 使用 fuser 释放端口（如果可用）
            subprocess.run(["fuser", "-k", "9090/tcp"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["fuser", "-k", "7890/tcp"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except:
        pass

    # 等待并确保端口完全释放
    for _ in range(5):
        time.sleep(1)
        port_9090_free = not is_port_in_use(9090)
        port_7890_free = not is_port_in_use(7890)
        if port_9090_free and port_7890_free:
            break
        print("等待端口释放...")

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
    # 启动前先确保 9090 和 7890 端口可用
    for port in [9090, 7890]:
        if is_port_in_use(port):
            print(f"{port} 端口被占用，清理旧 Clash 进程...")
            kill_clash()

    # 强制等待确保端口完全释放
    time.sleep(1)

    if os.name != 'nt':
        subprocess.run(["chmod", "+x", "./clash"])
    try:
        # 捕获 Clash 启动日志以便调试
        process = subprocess.Popen(
            ["./clash", "-f", "run.yaml"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        return process
    except Exception as e:
        print(f"❌ 无法执行 Clash 命令：{e}")
        return None

def wait_clash(process):
    """等待 Clash 启动，最多等待 30 秒"""
    print("等待 Clash 启动...")
    for i in range(30):
        try:
            socket.create_connection(("127.0.0.1", 9090), timeout=1)
            print(f"Clash 启动成功，耗时 {i+1} 秒")
            return True
        except Exception as e:
            # 每 2 秒检查一次进程状态，更快发现问题
            if (i + 1) % 2 == 0:
                if process and process.poll() is not None:
                    stdout, stderr = process.communicate()
                    print(f"Clash 进程已退出 (返回码：{process.returncode})")
                    if stderr:
                        print(f"错误输出：{stderr[:800]}")
                    if stdout:
                        print(f"标准输出：{stdout[:800]}")
                    return False
            if (i + 1) % 5 == 0:
                print(f"已等待 {i+1} 秒... (异常：{e})")
            time.sleep(1)
    print("Clash 启动超时")
    return False

if __name__ == "__main__":
    # 第一步：获取并清洗节点
    raw = fetch_proxies()
    if not raw:
        print("未找到符合条件的节点")
        exit()

    try:
        # 第二步：5 轮递进筛选（延迟要求逐步收紧）
        current_proxies = raw
        for round_idx, max_delay in enumerate(MAX_DELAY_ROUNDS, 1):
            passed = filter_proxies_round(current_proxies, max_delay=max_delay, round_num=round_idx)
            if not passed:
                print(f"第{round_idx}轮筛选无节点通过，退出")
                exit()
            current_proxies = passed

            # ========== Cloudflare Trace: 检测节点出口位置（第 1 轮后） ==========
            # 原因：先通过 Clash 粗筛（测通 Google），再对通过的节点做 CF Trace，节省时间
            # 优势：免费无限制，走节点真实流量，结果准确
            if round_idx == 1 and ENABLE_CF_TRACE and current_proxies:
                current_proxies = filter_by_colo_round(current_proxies)
                if not current_proxies:
                    print("CF Trace 过滤后无节点剩余，退出")
                    exit()
            # ================================================================

        # 第三步：保存结果
        os.makedirs("output", exist_ok=True)
        final_data = {"proxies": current_proxies}

        with open("output/proxies.yaml", "w", encoding="utf-8") as f:
            yaml.dump(final_data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

        # 同时生成一个带 url-test 的完整配置文件
        save_final_config(current_proxies)

        print(f"\n成功筛选出 {len(current_proxies)} 个节点并保存。")
        print("已生成 output/proxies.yaml（原始节点）和 output/config.yaml（完整配置）")
    except Exception as e:
        print(f"运行出错：{e}")
        kill_clash()
