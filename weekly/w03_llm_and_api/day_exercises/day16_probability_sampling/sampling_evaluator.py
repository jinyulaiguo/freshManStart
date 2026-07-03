"""
Day 16: 概率采样控制与 Agent 确定性路由策略 - 参考标准答案

设计方案说明：
1. 设计意图：
   通过自建的自回归 Logits 采样模拟器，演示并量化分析大模型在不同采样参数下的表现。
   利用香农熵公式度量文本的不确定性，通过 JSON 解析校验评估结构化输出的损毁情况。
2. 类与函数结构：
   - `calculate_entropy(text: str) -> float`: 计算字符的香农信息熵。
   - `is_valid_json(text: str) -> bool`: 校验 JSON 解析。
   - `mock_llm_generate(prompt: str, temperature: float, top_p: float) -> str`: 
     底层的自回归生成模拟，支持调整后的 Logits 的 Softmax 转化以及 Top-P（核采样）截断与再归一化。
   - `SamplingEvaluator`: 控制多次实验执行，汇总输出各配置组的统计平均值。
3. 关键数据流流向：
   `Prompt` -> `自回归 18 步生成` -> `Softmax 概率` -> `Top-P 过滤` -> `加权抽样` -> `结果文本` -> `指标评估`
"""

import math
import json
import random
from typing import List, Dict, Tuple


def calculate_entropy(text: str) -> float:
    """
    计算输入文本的字符级香农熵（Shannon Entropy）。
    
    公式：H(X) = -sum(P(x_i) * log2(P(x_i)))
    """
    if not text:
        return 0.0
    
    # 统计词频
    char_counts = {}
    for char in text:
        char_counts[char] = char_counts.get(char, 0) + 1
        
    total_len = len(text)
    entropy = 0.0
    for count in char_counts.values():
        p = count / total_len
        entropy -= p * math.log2(p)
        
    return entropy


def is_valid_json(text: str) -> bool:
    """
    校验输入文本是否为合法的 JSON 格式。
    """
    try:
        json.loads(text)
        return True
    except json.JSONDecodeError:
        return False


def mock_llm_generate(prompt: str, temperature: float, top_p: float) -> str:
    """
    模拟大模型的自回归生成逻辑（支持 Temperature 与 Top-P 采样控制）。
    """
    target_tokens = ['{', '"', 'r', 'o', 'u', 't', 'e', '"', ':', ' ', '"', 'a', 'g', 'e', 'n', 't', '"', '}']
    noise_tokens = ['x', 'y', 'z', '[', ']', '!', '?']
    
    generated_chars = []
    
    for i in range(len(target_tokens)):
        # 候选词表：当前的正确字符 + 所有干扰噪声字符
        candidates = [target_tokens[i]] + noise_tokens
        
        # 定义原始 Logits，目标字符的 Logits 远高于噪声字符
        logits = [10.0] + [2.0] * len(noise_tokens)
        
        # 1. 应用 Temperature 调节温度，防止分母为 0
        temp_val = max(temperature, 1e-6)
        adjusted_logits = [l / temp_val for l in logits]
        
        # 2. 计算 Softmax 概率
        max_logit = max(adjusted_logits)  # 减去最大值防止指数溢出
        exp_logits = [math.exp(l - max_logit) for l in adjusted_logits]
        sum_exp = sum(exp_logits)
        probabilities = [e / sum_exp for e in exp_logits]
        
        # 绑定候选词与概率
        candidates_probs = list(zip(candidates, probabilities))
        
        # 3. 应用 Top-P (核采样)
        # 按概率从大到小排序
        candidates_probs.sort(key=lambda x: x[1], reverse=True)
        
        cumulative_prob = 0.0
        keep_candidates = []
        
        for cand, prob in candidates_probs:
            keep_candidates.append((cand, prob))
            cumulative_prob += prob
            if cumulative_prob >= top_p:
                break
                
        # 4. 重新归一化保留下的候选词概率
        sum_keep_probs = sum(p for _, p in keep_candidates)
        final_candidates = [c for c, _ in keep_candidates]
        final_probs = [p / sum_keep_probs for _, p in keep_candidates]
        
        # 5. 加权随机选择
        chosen_char = random.choices(final_candidates, weights=final_probs, k=1)[0]
        generated_chars.append(chosen_char)
        
    return "".join(generated_chars)


class SamplingEvaluator:
    """
    采样测试与分析评估器
    """
    def __init__(self, prompt: str, runs_per_config: int = 50):
        self.prompt = prompt
        self.runs_per_config = runs_per_config

    def evaluate_config(self, temperature: float, top_p: float) -> Tuple[float, float]:
        """
        在特定的 Temperature 和 Top-P 组合下，执行 runs_per_config 次生成，
        统计平均字符香农熵以及 JSON 格式损毁率。
        """
        total_entropy = 0.0
        failures = 0
        
        for _ in range(self.runs_per_config):
            text = mock_llm_generate(self.prompt, temperature, top_p)
            
            # 计算并累加熵
            total_entropy += calculate_entropy(text)
            
            # 统计 JSON 是否损坏
            if not is_valid_json(text):
                failures += 1
                
        avg_entropy = total_entropy / self.runs_per_config
        failure_rate = failures / self.runs_per_config
        
        return avg_entropy, failure_rate

    def run_suite(self, temp_list: List[float], top_p_list: List[float]) -> Dict[str, Dict[str, float]]:
        """
        遍历不同的参数组合运行评估测试。
        """
        results = {}
        for temp in temp_list:
            for top_p in top_p_list:
                key = f"T={temp:.1f}/P={top_p:.1f}"
                avg_entropy, failure_rate = self.evaluate_config(temp, top_p)
                results[key] = {
                    "avg_entropy": avg_entropy,
                    "failure_rate": failure_rate
                }
        return results


if __name__ == "__main__":
    print("=== Day 16 概率采样控制实验 (标准答案验证) ===")
    prompt = "Generate a JSON with field 'route' value 'agent'"
    evaluator = SamplingEvaluator(prompt, runs_per_config=50)
    
    # 不同的 Temperature 参数测试，Top-P 锁定 1.0 (不截断)
    print("\n--- 实验一：锁定 Top-P = 1.0，调节 Temperature ---")
    temp_test = [0.1, 0.7, 1.2, 1.8]
    suite_results_1 = evaluator.run_suite(temp_test, [1.0])
    for config, metrics in suite_results_1.items():
        print(f"配置 {config} -> 平均字符熵: {metrics['avg_entropy']:.4f}, JSON格式损毁率: {metrics['failure_rate']*100:.1f}%")
        
    # 不同的 Top-P 参数测试，锁定高温 Temperature = 1.8
    print("\n--- 实验二：锁定高温 Temperature = 1.8，调节 Top-P 过滤噪声 ---")
    top_p_test = [1.0, 0.7, 0.4, 0.1]
    suite_results_2 = evaluator.run_suite([1.8], top_p_test)
    for config, metrics in suite_results_2.items():
        print(f"配置 {config} -> 平均字符熵: {metrics['avg_entropy']:.4f}, JSON格式损毁率: {metrics['failure_rate']*100:.1f}%")
        
    print("\n[理论解析]")
    print("1. 当 Temperature 趋于 0.1 时，Softmax 后目标 Token 概率接近 100%，输出结果极度稳定 (格式损毁率为 0.0%)，字符熵较低。")
    print("2. 当 Temperature 提升至 1.8 时，Logits 差异被抹平，噪声被大量引入，导致生成的 JSON 无法解析 (损毁率激增)。")
    print("3. 当引入 Top-P (如 0.4) 截断时，即使在 Temperature = 1.8 的高温下，累计概率快速收缩，排除了绝大部分低概率噪声，依然可以显著降低格式损毁率。")
