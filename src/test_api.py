"""
Quick API connectivity test.
Verifies that the Anthropic API key is valid and the model is reachable.

Usage:
    python test_api.py
"""

import anthropic
import os
import sys


def _get_api_key():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'api_key.txt')
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            return f.read().strip()
    raise FileNotFoundError(
        "API key not found. Set ANTHROPIC_API_KEY env var or create config/api_key.txt"
    )


if __name__ == "__main__":
    try:
        api_key = _get_api_key()
    except FileNotFoundError as e:
        print(f"❌ {e}")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    print("正在调用Claude API测试连接...")

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        messages=[
            {"role": "user", "content": "请用一句话简单介绍SUMO交通仿真软件"}
        ]
    )

    response = message.content[0].text
    print("\n✅ Claude的回复：")
    print(response)
    print("\n🎉 测试成功！环境配置完成。")
