import re

def generate_hashtags(title: str):
    words = re.findall(r"[A-Za-z]{4,}", title)
    seen = set()
    tags = []
    for w in words:
        lw = w.lower()
        if lw not in seen:
            seen.add(lw)
            tags.append(f"#{lw}")
        if len(tags) >= 5:
            break
    return " ".join(tags)
