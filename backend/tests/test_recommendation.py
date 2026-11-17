from conftest import chat


def test_chinese_hiking_backpack_is_grounded(client):
    result = chat(client, "推荐一个适合徒步的防雨背包")["results"][0]
    products = result["data"]["products"]
    assert [p["sku"] for p in products] == ["SOBP001"]
    assert "防风雨材料" in products[0]["features"]
    assert "充足储物空间" in products[0]["features"]
    assert len(result["evidence"]) == 1


def test_no_fabricated_weight_or_multiple_backpacks(client):
    result = chat(client, "推荐轻便背包，比较重量和价格")["results"][0]
    assert len(result["data"]["products"]) == 1
    assert "未提供价格" in result["text"]
    assert "轻量设计" not in result["data"]["products"][0]["features"]


def test_follow_up_keeps_category(client):
    chat(client, "Recommend a hiking backpack")
    result = chat(client, "Is there a lighter product?")["results"][0]
    assert [p["sku"] for p in result["data"]["products"]] == ["SOBP001"]


def test_multitask_request(client):
    result = chat(client, "Track #W001 for explorer01@example.com and recommend a hiking backpack")
    assert {r["workflow"] for r in result["results"]} == {"lookup", "recommend"}
