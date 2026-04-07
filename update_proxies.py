import requests
import yaml
import socket
import concurrent.futures
import urllib3

# 禁用 SSL 警告（因为你用了 verify=False）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 你的所有原始订阅地址
urls = [
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

def is_alive(proxy_item, timeout=3):
    server = proxy_item.get('server')
    port = proxy_item.get('port')
    if not server or not port:
        return False
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        # connect_ex 返回 0 表示成功
        result = sock.connect_ex((str(server), int(port)))
        sock.close()
        return result == 0
    except:
        return False

def process_url(url):
    proxies = []
    headers = {'User-Agent': 'Clash/1.0'} 
    try:
        resp = requests.get(url, timeout=15, headers=headers, verify=False)
        # 增加一步检查，确保返回的是有效的 YAML
        data = yaml.safe_load(resp.text)
        if isinstance(data, dict) and 'proxies' in data:
            return data['proxies']
    except Exception as e:
        print(f"跳过失效源 {url}: {e}")
    return proxies

def merge_and_filter():
    all_raw_proxies = []
    seen_addr = set()
    
    # 1. 抓取并去重 (基于 IP:Port)
    for url in urls:
        raw_list = process_url(url)
        if not raw_list: continue
        for p in raw_list:
            addr = f"{p.get('server')}:{p.get('port')}"
            if addr not in seen_addr:
                seen_addr.add(addr)
                all_raw_proxies.append(p)

    print(f"抓取完成，唯一节点: {len(all_raw_proxies)}。开始多线程检测...")

    # 2. 多线程检测
    final_proxies = []
    # max_workers 建议在 50-100 之间，Action 的 CPU 足以应付
    with concurrent.futures.ThreadPoolExecutor(max_workers=60) as executor:
        future_to_proxy = {executor.submit(is_alive, p): p for p in all_raw_proxies}
        
        # 给重名节点加编号，防止 Clash 报错
        name_counter = 1
        for future in concurrent.futures.as_completed(future_to_proxy):
            proxy = future_to_proxy[future]
            if future.result():
                # 强制重命名，确保唯一性
                proxy['name'] = f"NODE-{name_counter:03d}"
                final_proxies.append(proxy)
                name_counter += 1

    # 3. 写入文件
    output = {"proxies": final_proxies}
    with open("all.yaml", "w", encoding="utf-8") as f:
        # default_flow_style=False 保证生成的是标准的 YAML 列表格式
        yaml.dump(output, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    
    print(f"处理结束！可用节点: {len(final_proxies)} / {len(all_raw_proxies)}")

if __name__ == "__main__":
    merge_and_filter()
