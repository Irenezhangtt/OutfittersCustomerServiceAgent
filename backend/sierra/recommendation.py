import re

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# Small, auditable bilingual domain ontology. No external model download at startup.
CONCEPTS = {
    "backpack": ["背包", "双肩包", "backpack", "rucksack", "daypack"],
    "hiking": ["徒步", "登山", "hiking", "hike", "trek", "trail"],
    "weatherproof": ["防雨", "防水", "rain", "waterproof", "weatherproof"],
    "lightweight": ["轻便", "轻量", "轻一些", "lightweight", "lighter", "light weight"],
    "storage": ["容量", "能装", "空间", "storage", "capacity", "roomy"],
    "skis": ["滑雪", "雪板", "skis", "skiing", "snow", "winter"],
    "food": ["零食", "蛋白棒", "能量棒", "protein", "bars", "snack", "nutrition"],
    "beverage": ["饮料", "咖啡因", "drink", "beverage", "caffeine"],
    "home": ["灯罩", "家居", "lampshade", "decor", "lighting"],
    "shoes": ["鞋", "shoes", "footwear"],
    "flight": ["飞行", "喷气", "飞机", "flight", "jetpack", "plane"],
    "hairbrush": ["梳子", "hairbrush", "hair"],
    "cloak": ["隐身", "斗篷", "cloak", "invisible", "stealth"],
}
CATEGORIES = {"backpack", "skis", "food", "beverage", "home", "shoes", "flight", "hairbrush", "cloak"}
ZH_FEATURES = {
    "weatherproof": "防风雨材料", "storage": "充足储物空间", "durability": "耐用设计",
    "lightweight": "轻量设计", "snow": "雪地运动", "precision": "精准操控",
}


def concepts(text):
    lower = text.lower()
    return {key for key, words in CONCEPTS.items() if any(word in lower for word in words)}


def expand(text):
    return text.lower() + " " + " ".join(sorted(concepts(text))) * 3


def extract_features(description):
    features = []
    for key, pattern in [("weatherproof", r"weatherproof|waterproof"), ("storage", r"ample storage"),
                         ("durability", r"durab"), ("lightweight", r"lightweight"), ("precision", r"precision")]:
        if re.search(pattern, description.lower()):
            features.append(key)
    return features


class ProductSearch:
    """TF-IDF retrieval with semantic query expansion and hard product-category gates."""

    def __init__(self, products):
        self.products = products
        texts = [expand(f"{p['name']} {' '.join(p['tags'])} {p['description']}") for p in products]
        self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True)
        self.matrix = self.vectorizer.fit_transform(texts)

    def search(self, query, limit=3):
        wanted = concepts(query)
        scores = cosine_similarity(self.vectorizer.transform([expand(query)]), self.matrix)[0]
        rows = []
        for p, score in zip(self.products, scores):
            # A "Backpack" search must not return a beverage tagged "Weatherproof".
            category_text = p["name"] + " " + " ".join(p["tags"])
            categories = concepts(category_text) & CATEGORIES
            if wanted & CATEGORIES and not (wanted & CATEGORIES & categories):
                continue
            if p["inventory"] <= 0 or score < 0.025:
                continue
            rows.append({**p, "score": round(float(score), 4), "features": extract_features(p["description"])})
        return sorted(rows, key=lambda p: p["score"], reverse=True)[:limit]
