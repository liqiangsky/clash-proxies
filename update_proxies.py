import requests
import yaml
import socket

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

def is_alive(server, port, timeout=3):
    """简单的 TCP 握手测试，判断节点是否在线"""
    try:
        # 如果是域名，会自动解析 IP
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((server, int(port)))
        sock.close()
        return True
    except:
        return False

def merge_and_filter():
    all_proxies = []
    seen = set()
    alive_count = 0
    dead_count = 0

    for url in urls:
        try:
            print(f"正在获取: {url}")
            resp = requests.get(url, timeout=10)
            data = yaml.safe_load(resp.text)
            
            if data and 'proxies' in data:
                for p in data['proxies']:
                    server = p.get('server')
                    port = p.get('port')
                    fingerprint = f"{server}:{port}"

                    if fingerprint not in seen:
                        seen.add(fingerprint)
                        # 执行连通性过滤
                        if is_alive(server, port):
                            all_proxies.append(p)
                            alive_count += 1
                        else:
                            dead_count += 1
        except Exception as e:
            print(f"跳过失效订阅源: {url}")

    # 写入结果
    with open("all.yaml", "w", encoding="utf-8") as f:
        yaml.dump({"proxies": all_proxies}, f, allow_unicode=True)
    
    print(f"处理完成！有效节点: {alive_count}, 过滤死节点: {dead_count}")

if __name__ == "__main__":
    merge_and_filter()
