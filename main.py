import requests
import yaml
import time
import subprocess
import socket
import os
import urllib3
from concurrent.futures import ThreadPoolExecutor

urllib3.disable_warnings()

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

HEADERS = {"User-Agent": "Mozilla/5.0"}

# ✅ 唯一名称
def make_unique_name(name, used):
    name = str(name).strip() or "node"

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
    seen = set()
    name_used = set()

    for url in URLS:
        try:
            print(f"获取: {url}")
            resp = requests.get(url, headers=HEADERS, timeout=15, verify=False)
            data = yaml.safe_load(resp.text)

            for p in data.get("proxies", []):
                server = p.get("server")
                port = p.get("port")

                if not server or not port:
                    continue

                key = f"{server}:{port}"
                if key in seen:
                    continue
                seen.add(key)

                name = str(p.get("name", "")).lower()

                # ❌ 垃圾过滤
                if name.startswith("_"):
                    continue
                if "test" in name:
                    continue
                if p.get("cipher") == "none":
                    continue

                # ❌ 过滤低质量 ss（可选但推荐）
                if p.get("type") == "ss" and p.get("cipher") in ["aes-128-gcm"]:
                    continue

                # ✅ 唯一名称
                base_name = p.get("name") or f"{server}:{port}"
                p["name"] = make_unique_name(base_name, name_used)

                all_proxies.append(p)

        except:
            print(f"跳过: {url}")

    print(f"抓取完成: {len(all_proxies)}")
    return all_proxies


def save_for_clash(proxies):
    config = yaml.safe_load(open("clash.yaml", encoding="utf-8"))

    config["proxies"] = proxies
    config["proxy-groups"][0]["proxies"] = [p["name"] for p in proxies]

    with open("run.yaml", "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True)


def start_clash():
    print("启动 Clash...")
    return subprocess.Popen(["./clash", "-f", "run.yaml"])


def wait_clash():
    for _ in range(20):
        try:
            s = socket.create_connection(("127.0.0.1", 9090), timeout=1)
            s.close()
            print("Clash 已启动")
            return True
        except:
            time.sleep(1)
    return False


# 🚀 核心：多次测速过滤
def test_delay(name):
    delays = []

    for _ in range(3):  # 测3次
        try:
            url = f"http://127.0.0.1:9090/proxies/{name}/delay"
            params = {
                "url": "https://www.google.com/generate_204",
                "timeout": 5000
            }
            r = requests.get(url, params=params, timeout=6)
            delay = r.json().get("delay", -1)

            if delay > 0:
                delays.append(delay)
        except:
            pass

    # ❌ 成功次数太少
    if len(delays) < 2:
        print(f"❌ {name} 不稳定")
        return None

    avg = sum(delays) / len(delays)

    # ❌ 延迟太高
    if avg > 800:
        print(f"❌ {name} {int(avg)}ms")
        return None

    print(f"✅ {name} 平均 {int(avg)}ms")
    return (name, avg)


def filter_proxies(proxies):
    if not wait_clash():
        print("Clash 启动失败")
        return []

    names = [p["name"] for p in proxies]

    results = []
    with ThreadPoolExecutor(max_workers=20) as ex:
        for r in ex.map(test_delay, names):
            if r:
                results.append(r)

    # ✅ 按延迟排序
    results.sort(key=lambda x: x[1])

    good_names = [name for name, _ in results]

    good = [p for p in proxies if p["name"] in good_names]

    print(f"最终可用节点: {len(good)}")
    return good


def save_output(proxies):
    os.makedirs("output", exist_ok=True)

    with open("output/proxies.yaml", "w", encoding="utf-8") as f:
        yaml.dump({"proxies": proxies}, f, allow_unicode=True)

    config = yaml.safe_load(open("clash.yaml", encoding="utf-8"))
    config["proxies"] = proxies
    config["proxy-groups"][0]["proxies"] = [p["name"] for p in proxies]

    with open("output/config.yaml", "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True)


if __name__ == "__main__":
    proxies = fetch_proxies()

    if not proxies:
        print("没有节点")
        exit(1)

    save_for_clash(proxies)

    clash = start_clash()

    good = filter_proxies(proxies)

    save_output(good)

    clash.kill()

    print("完成 ✅")
