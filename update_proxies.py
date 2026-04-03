import requests
import yaml

# 你的所有原始订阅地址
urls = [
    "http://140.238.31.152:12580/clash/proxies",
    "https://pp.dcd.one/clash/proxies",
    "https://open.tidnotes.top/clash/proxies",
    "http://h3.g01.work:12580/clash/proxies",
    "https://vc.majunfei.club:51/clash/proxies",
    "http://138.2.112.136:12580/clash/proxies",
    "http://176.126.114.231:12580/clash/proxies",
    "https://fp.ethanyang.top/clash/proxies",
    "http://ql.ethanyang.top:12580/clash/proxies",
    "https://open.tidnotes.top:2083/clash/proxies",
    "http://107.172.0.114:12580/clash/proxies",
    "http://132.226.224.85:56852/clash/proxies",
    "http://xqz0.vip:15580/clash/proxies"
]

def merge_nodes():
    all_proxies = []
    seen = set()
    
    for url in urls:
        try:
            resp = requests.get(url, timeout=10)
            data = yaml.safe_load(resp.text)
            if data and 'proxies' in data:
                for p in data['proxies']:
                    # 关键去重：以服务器地址和端口作为唯一标识
                    fingerprint = f"{p.get('server')}:{p.get('port')}"
                    if fingerprint not in seen:
                        seen.add(fingerprint)
                        all_proxies.append(p)
        except: continue
        
    with open("all.yaml", "w", encoding="utf-8") as f:
        yaml.dump({"proxies": all_proxies}, f, allow_unicode=True)

if __name__ == "__main__":
    merge_nodes()
