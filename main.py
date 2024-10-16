import requests
import random
import time
import re
import sys
from fake_useragent import UserAgent
from twocaptcha import TwoCaptcha, ApiException, ValidationException, NetworkException, TimeoutException
from typing import List, Optional
from loguru import logger
from dotenv import load_dotenv
import os

# 加载环境变量
load_dotenv()

# 日志设置
logger.remove(0)
logger.add(sys.stderr, level='DEBUG', colorize=True, format="{time:HH:mm:ss} <level>| {level: <7} | {message}</level>")

# 文件加载
def load_lines(file_path: str) -> List[str]:
    try:
        with open(file_path, 'r') as file:
            return [line.strip() for line in file if line.strip()]
    except FileNotFoundError:
        logger.warning(f"{file_path} 未找到，将跳过此文件。")
        return []

# 生成伪造的 User-Agent
def generate_fake_user_agent() -> str:
    return UserAgent().random

# 解决 CAPTCHA 验证
def solve_captcha(solver: TwoCaptcha, sitekey: str, url: str, useragent: str, max_attempts: int = 3) -> Optional[str]:
    for attempt in range(max_attempts):
        try:
            logger.info("正在解决 CAPTCHA 验证...")
            result = solver.turnstile(sitekey=sitekey, url=url, useragent=useragent)
            logger.info("CAPTCHA 验证成功")
            return result['code']
        except (ValidationException, NetworkException, TimeoutException, ApiException) as e:
            logger.error(f"解决 CAPTCHA 验证时出错: {e}")
            if attempt < max_attempts - 1:
                backoff_time = 2 ** (attempt + 1)
                logger.info(f"等待 {backoff_time} 秒后重试...")
                time.sleep(backoff_time)
    logger.error("多次尝试后未能解决 CAPTCHA 验证。")
    return None

# 发起 API 请求
def make_api_request(api_url: str, captcha_code: str, proxy: Optional[str], max_attempts: int = 3) -> Optional[str]:
    headers = generate_headers()
    api_url_with_captcha = api_url.format(captcha_code=captcha_code)
    proxies = {'http': proxy} if proxy else None
    log_message = '使用代理' if proxy else '不使用代理'
    logger.info(f"正在向 API 发起请求，{log_message}...")

    for attempt in range(max_attempts):
        try:
            response = requests.get(api_url_with_captcha, headers=headers, proxies=proxies)
            return handle_response(response)
        except requests.RequestException as e:
            logger.error(f"请求失败: {e}")
            if attempt < max_attempts - 1:
                backoff_time = 2 ** (attempt + 1)
                logger.info(f"等待 {backoff_time} 秒后重试...")
                time.sleep(backoff_time)
    logger.error("多次尝试后请求 API 失败。")
    return None

# 生成请求头
def generate_headers() -> dict:
    user_agent = generate_fake_user_agent()
    platform_match = re.search(r'\([^;]+', user_agent)
    system_platform = platform_match.group(0)[1:] if platform_match else "未知平台"
    return {
        "path": "/airdrop/{captcha_code}",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Dnt": "1",
        "Origin": "https://faucet.sonic.game",
        "Priority": "u=1, i",
        "Referer": "https://faucet.sonic.game/",
        "User-Agent": user_agent,
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": f'"{system_platform}"'
    }

# 处理 API 响应
def handle_response(response: requests.Response) -> Optional[str]:
    if response.status_code == 200:
        try:
            data = response.json()
            if data['status'] == 'ok':
                logger.info(f"响应状态: {data['status']}")
                return data['data']['data'].strip()
            else:
                logger.error(f"API 响应错误: {data}")
        except ValueError:
            logger.error("错误: 接收到无效的 JSON。")
            logger.error(f"响应内容: {response.content}")
    elif response.status_code == 429:
        logger.warning("收到 429 请求过多，跳过此钱包。")
        return "too_many_requests"
    elif response.status_code == 401:
        logger.warning("收到 401 错误，可能被识别为机器人，跳过此钱包。")
        return "might_be_a_robot"
    else:
        logger.error(f"错误: {response.status_code}, 响应内容: {response.content}")
    return None

# 保存钱包签名
def save_wallet_signature(wallet: str, signature: str) -> None:
    with open('successful_wallets.txt', 'a') as file:
        file.write(f'{wallet},{signature}\n')

# 选择网络
def choose_network() -> str:
    while True:
        print("\n请选择网络:")
        print("1. Devnet")
        print("2. Testnet")
        choice = input("请输入你的选择 (1 或 2): ")
        if choice == '1':
            return "devnet"
        elif choice == '2':
            return "testnet"
        else:
            print("无效选择。请输入 1 或 2。")

# 主逻辑
def main() -> None:
    api_key = os.getenv("API_KEY")
    if not api_key:
        logger.error("未在环境变量中找到 API 密钥。")
        return
    
    network = choose_network()
    
    sitekey = '0x4AAAAAAAc6HG1RMG_8EHSC'
    url = 'https://faucet.sonic.game/'
    
    if network == "devnet":
        api_base_url = "https://faucet-api.sonic.game/airdrop/"
    else:  # testnet
        api_base_url = "https://faucet-api-grid-1.sonic.game/airdrop/"
    
    proxies = load_lines('proxy.txt')
    wallets = load_lines('wallet.txt')
    
    if not wallets:
        logger.error("未找到要处理的钱包。")
        return

    solver = TwoCaptcha(api_key)

    for wallet in wallets:
        logger.info(f"正在处理钱包: {wallet}")
        api_url = f"{api_base_url}{wallet}/0.5/{{captcha_code}}"
        proxy = random.choice(proxies) if proxies else None
        captcha_code = solve_captcha(solver, sitekey, url, generate_fake_user_agent())
        
        if not captcha_code:
            logger.error(f"多次尝试后未能解决 CAPTCHA，跳过钱包 {wallet} 的请求。")
            continue
        
        signature = make_api_request(api_url, captcha_code, proxy)
        if signature and signature not in ["too_many_requests", "might_be_a_robot"]:
            logger.info(f"成功获取钱包 {wallet} 的签名: {signature}")
            save_wallet_signature(wallet, signature)
        
        time.sleep(20)

if __name__ == "__main__":
    main()
