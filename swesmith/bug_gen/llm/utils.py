import re


PROMPT_KEYS = ["system", "demonstration", "instance"]


def extract_code_block(text: str) -> str:
    pattern = r"```(?:\w+)?\n(.*?)```"
    blocks = re.findall(pattern, text, re.DOTALL)
    if not blocks:
        return ""
    # Join multiple fenced code blocks to support LLMs that emit one block per function
    return "\n\n".join(b.strip() for b in blocks)
