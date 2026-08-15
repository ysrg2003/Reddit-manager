import os
import json

from reddit_manager import get_community_intel

q = os.getenv("TEST_KEYWORD")

print("Searching for:", q)

text, media = get_community_intel(q)

print("=== TEXT LENGTH ===", len(text))
print("=== MEDIA COUNT ===", len(media))

# -------- Save Evidence Text --------
with open("reddit_evidence.txt", "w", encoding="utf-8") as f:
    f.write(text)

# -------- Save Media JSON --------
with open("reddit_media.json", "w", encoding="utf-8") as f:
    json.dump(media, f, indent=2, ensure_ascii=False)

print("Files saved successfully.")
