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

# 使用国内可访问的测试目标，更贴近实际使用场景
TEST_URL = "https://www.google.com/generate_204"  # Google 204 测试，更轻量

# 5 轮过滤延迟阈值 (ms) - 逐步收紧
MAX_DELAY_ROUNDS = [5000, 3000, 2000, 1000, 500]  # 从宽松到严格

# 线程池配置
FETCH_WORKERS = 10
FETCH_TIMEOUT = 8
TEST_WORKERS = 80

# 批次大小配置
BATCH_SIZE = 500  # 每批次节点数

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

def test_google_access(name, max_delay=MAX_DELAY_ROUNDS[0]):
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


def filter_proxies_round(proxies, batch_size=None, max_delay=MAX_DELAY_ROUNDS[0], round_num=1):
    """通用单轮筛选函数"""
    if batch_size is None:
        batch_size = BATCH_SIZE
    results = []
    total = len(proxies)
    batches = (total + batch_size - 1) // batch_size

    print(f"\n第{round_num}轮筛选（延迟 ≤ {max_delay}ms），共 {batches} 批次...")

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
            futures = {ex.submit(test_google_access, p["name"], max_delay): p["name"] for p in batch}
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


def save_for_clash(proxies):
    """生成 Clash 配置"""
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

def save_batch_for_clash(batch):
    """为当前批次生成精简的 Clash 配置"""
    # 过滤掉可能导致 Clash 解析失败的节点，并确保名称唯一
    valid_batch = []
    seen_names = {}  # name -> count
    for p in batch:
        # 跳过没有必要字段的节点
        if not p.get("server") or not p.get("port"):
            continue

        # 确保名称唯一，重复则添加后缀
        name = p.get("name")
        if name:
            if name in seen_names:
                seen_names[name] += 1
                p["name"] = f"{name}_{seen_names[name]}"
            else:
                seen_names[name] = 0
            valid_batch.append(p)

    save_for_clash(valid_batch)
    file_size = os.path.getsize("run.yaml") / 1024
    skipped = len(batch) - len(valid_batch)
    print(f"已生成 run.yaml，{len(valid_batch)} 个节点{' (跳过 ' + str(skipped) + ' 个无效节点)' if skipped else ''}，大小：{file_size:.1f} KB")

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

        # 第三步：保存结果
        os.makedirs("output", exist_ok=True)
        final_data = {"proxies": current_proxies}

        with open("output/proxies.yaml", "w", encoding="utf-8") as f:
            yaml.dump(final_data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

        print(f"\n成功筛选出 {len(current_proxies)} 个节点并保存。")
    except Exception as e:
        print(f"运行出错：{e}")
        kill_clash()
