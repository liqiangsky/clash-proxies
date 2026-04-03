import requests
import yaml
import base64

# 你刚才提取出来的原始 URL 列表
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

def main():
    all_proxies = []
    seen = set()  # 用于去重

    for url in urls:
        try:
            print(f"正在抓取: {url}")
            resp = requests.get(url, timeout=15)
            data = yaml.safe_load(resp.text)
            
            if data and 'proxies' in data:
                for p in data['proxies']:
                    # 根据服务器地址和端口去重，防止改名白嫖
                    fingerprint = f"{p.get('server')}:{p.get('port')}"
                    if fingerprint not in seen:
                        seen.add(fingerprint)
                        all_proxies.append(p)
        except Exception as e:
            print(f"抓取失败 {url}: {e}")

    # 构造 Clash 格式
    output = {"proxies": all_proxies}
    
    with open("sub.yaml", "w", encoding="utf-8") as f:
        yaml.dump(output, f, allow_unicode=True)
    print(f"同步完成，共 {len(all_proxies)} 个唯一节点")

if __name__ == "__main__":
    main()
