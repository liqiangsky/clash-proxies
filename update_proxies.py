import requests
import yaml
import time
import subprocess
from concurrent.futures import ThreadPoolExecutor

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

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

def fetch_proxies():
    all_proxies = []
    seen = set()

    for url in URLS:
        try:
            print(f"获取: {url}")
            resp = requests.get(url, headers=HEADERS, timeout=15, verify=False)
            data = yaml.safe_load(resp.text)

            for p in data.get("proxies", []):
                key = f"{p.get('server')}:{p.get('port')}"
                if key not in seen:
                    seen.add(key)

                    # 简单过滤垃圾节点
                    if p.get("cipher") == "none":
                        continue
                    if "test" in p.get("name", "").lower():
                        continue

                    all_proxies.append(p)

        except:
            print(f"跳过: {url}")

    print(f"抓取完成: {len(all_proxies)} 个节点")
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


def test_delay(name):
    try:
        url = f"http://127.0.0.1:9090/proxies/{name}/delay"
        params = {
            "url": "https://www.google.com/generate_204",
            "timeout": 5000
        }
        r = requests.get(url, params=params, timeout=6)
        data = r.json()
        delay = data.get("delay", -1)

        if delay > 0 and delay < 2000:
            print(f"✅ {name} {delay}ms")
            return name
        else:
            print(f"❌ {name}")
            return None
    except:
        print(f"❌ {name}")
        return None


def filter_proxies(proxies):
    print("等待 Clash 启动...")
    time.sleep(5)

    names = [p["name"] for p in proxies]

    good = []
    with ThreadPoolExecutor(max_workers=20) as ex:
        results = ex.map(test_delay, names)

    good_names = set(filter(None, results))

    for p in proxies:
        if p["name"] in good_names:
            good.append(p)

    print(f"可用节点: {len(good)}")
    return good


def save_output(proxies):
    with open("output/proxies.yaml", "w", encoding="utf-8") as f:
        yaml.dump({"proxies": proxies}, f, allow_unicode=True)

    config = yaml.safe_load(open("clash.yaml", encoding="utf-8"))
    config["proxies"] = proxies
    config["proxy-groups"][0]["proxies"] = [p["name"] for p in proxies]

    with open("output/config.yaml", "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True)


if __name__ == "__main__":
    proxies = fetch_proxies()

    save_for_clash(proxies)

    clash = start_clash()

    good = filter_proxies(proxies)

    save_output(good)

    clash.kill()

    print("完成 ✅")
