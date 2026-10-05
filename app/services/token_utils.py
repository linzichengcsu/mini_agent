"""Token 估算工具（本地、无需网络）。

在发起真实请求前用字符数近似估算 token 消耗，用于判断是否需要触发
上下文压缩。估算值刻意略偏保守（偏高），以便提前干预；API 返回的
usage 字段才是准确值。
"""


def _is_cjk_char(ch: str) -> bool:
    """判断字符是否属于 CJK（汉字 / CJK 标点 / 全角符号），这类字符约 1 token。"""
    cp = ord(ch)
    return (
        0x4E00 <= cp <= 0x9FFF or    # CJK 统一表意文字（汉字）
        0x3000 <= cp <= 0x303F or    # CJK 符号和标点（、。「」等）
        0xFF00 <= cp <= 0xFFEF       # 全角形式（，。！？等）
    )


def estimate_tokens(text: str) -> int:
    """粗略估算一段文本的 token 数。

    中文及全角标点按 1 字符 ≈ 1 token，英文等其他字符按 4 字符 ≈ 1 token。
    """
    if not text:
        return 0
    cjk = sum(1 for ch in text if _is_cjk_char(ch))
    other = len(text) - cjk
    # 非中文字符按 4 字符 ≈ 1 token，向上取整；纯中文时 other=0，加 0
    return cjk + (other + 3) // 4


def count_messages_tokens(messages) -> int:
    """估算整组消息的 token 数（每条消息另计约 4 token 的角色开销）。"""
    overhead = len(messages) * 4
    return overhead + sum(estimate_tokens(m.get("content", "")) for m in messages)
