"""
LLM 调用封装，四个智能体共用。
api_key 为空时自动降级，不向上抛出异常，保证系统始终可用。
"""
import os
import requests
import yaml
from typing import Dict, Any


class LLMService:
    def __init__(self, config_path: str = "config.yaml"):
        self._client: requests.Session | None = None
        # 初始化默认值
        self.api_key: str = ""
        self.base_url: str = ""
        self.model: str = ""
        self.timeout: int = 10

        # 读取配置文件：优先 config.yaml，若不存在则回退到 config.example.yaml
        actual_path = config_path
        from_example = False
        if not os.path.exists(config_path):
            fallback_path = "config.example.yaml"
            if os.path.exists(fallback_path):
                actual_path = fallback_path
                from_example = True
                print(
                    "[LLMService] ==============================================\n"
                    "  未找到 config.yaml，使用 config.example.yaml 兜底。\n"
                    "  LLM 增强功能暂不可用（需真实 API Key）。\n"
                    "  请复制 config.example.yaml → config.yaml 并填入真实密钥：\n"
                    "    cp config.example.yaml config.yaml\n"
                    "=============================================================="
                )
            else:
                print(
                    "[LLMService] 警告: 配置文件不存在，LLM 增强功能不可用。"
                )

        if os.path.exists(actual_path):
            try:
                with open(actual_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                    llm_config = config.get('llm', {})
                    self.base_url = llm_config.get('base_url', '')
                    self.model = llm_config.get('model', 'deepseek-chat')
                    self.timeout = llm_config.get('timeout', 20)
                    raw_key = llm_config.get('api_key', '')
                    # 如果是从 example 文件读取的、或者是占位符格式的 key，
                    # 则视为未配置，避免用假 key 发起无意义的 API 调用
                    if from_example or "your-api-key" in raw_key or "your-key" in raw_key:
                        self.api_key = ""
                    else:
                        self.api_key = raw_key
            except Exception as e:
                print(f"[LLMService] 警告: 读取配置文件失败 {e}")

    @property
    def client(self) -> requests.Session:
        if self._client is None:
            self._client = requests.Session()
            self._client.headers.update({'Content-Type': 'application/json'})
            # 如果配置了 API Key，添加 Authorization 头 (适用于 DeepSeek/OpenAI 兼容接口)
            if self.api_key:
                self._client.headers.update({'Authorization': f'Bearer {self.api_key}'})
        return self._client

    def is_configured(self) -> bool:
        """
        判断 LLM 是否已配置。
        如果有 API Key，或者使用的是本地 Ollama 服务（localhost），则视为已配置。
        """
        if self.api_key and self.api_key.strip():
            return True
        # 如果是本地 Ollama 服务，即使没有 Key 也视为已配置
        if "localhost" in self.base_url or "127.0.0.1" in self.base_url:
            return True
        return False

    def chat(self, prompt: str) -> str:
        """
        调用 LLM 生成回复。
        api_key 未配置或调用失败时返回带 [规则引擎模式] 前缀的降级文本，不抛异常。
        """
        if not self.is_configured():
            return self._fallback("API Key 未配置，请在 config.yaml 中填写 llm.api_key")

        try:
            # 判断是 OpenAI 兼容接口还是 Ollama 原生接口
            # DeepSeek 使用 OpenAI 兼容格式: /v1/chat/completions
            # Ollama 通常使用: /api/generate 或 /api/chat
            
            is_ollama = "localhost" in self.base_url or "127.0.0.1" in self.base_url
            
            if is_ollama:
                # Ollama 原生接口
                url = f"{self.base_url}/api/generate"
                payload = {
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False
                }
            else:
                # OpenAI/DeepSeek 兼容接口
                url = f"{self.base_url}/v1/chat/completions"
                payload = {
                    "model": self.model,
                    "messages": [
                        {"role": "user", "content": prompt}
                    ],
                    "stream": False
                }

            response = self.client.post(
                url,
                json=payload,
                timeout=self.timeout
            )

            if response.status_code == 200:
                result = response.json()
                # 根据 API 类型解析结果
                if "choices" in result:
                    # OpenAI/DeepSeek 格式
                    return result['choices'][0]['message']['content']
                elif "response" in result:
                    # Ollama generate 格式
                    return result.get('response', '')
                else:
                    return str(result)
            else:
                error_msg = f"LLM API 错误: {response.status_code} - {response.text}"
                return self._fallback(error_msg)

        except Exception as exc:
            return self._fallback(f"{type(exc).__name__}: {exc}")

    def _fallback(self, reason: str) -> str:
        return f"[规则引擎模式] 分组依据规则引擎自动计算，LLM 服务不可用（{reason}）。"