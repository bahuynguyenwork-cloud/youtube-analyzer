import sys
import os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, r'd:\youtube_analysis')

from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

def test_upgraded_features():
    print("--- 1. Testing /api/health ---")
    res = client.get("/api/health")
    assert res.status_code == 200
    print("Health:", res.json())

    print("\n--- 2. Testing Channel Analysis with US Geo & Upload Time & Copyable Tags ---")
    res = client.post("/api/analyze/channel", json={
        "channel_input": "@veritasium", 
        "max_videos": 6,
        "target_geo": "US"
    })
    assert res.status_code == 200
    data = res.json()
    
    # Check Channel & Geo
    print(f"Channel: {data['channel']['channel_title']}")
    print(f"Target Geo: {data['trend']['target_geo']}")
    print(f"Trend Status: {data['trend']['trend_status']}")
    
    # Check Upload Time Analysis
    time_analysis = data.get("upload_time_analysis", {})
    print(f"\n[TIME ANALYSIS]")
    print(f"- Nước mục tiêu: {time_analysis.get('target_country_name')} ({time_analysis.get('target_timezone_name')})")
    print(f"- Giờ đăng ngày thường (Giờ VN): {time_analysis.get('suggested_weekday_vn')}")
    print(f"- Giờ đăng cuối tuần (Giờ VN): {time_analysis.get('suggested_weekend_vn')}")
    print(f"- Số khung giờ 24h: {len(time_analysis.get('hours_distribution', []))}")
    print(f"- Số khuyến nghị cụ thể: {len(time_analysis.get('top_recommendations', []))}")
    assert len(time_analysis.get("top_recommendations", [])) >= 2
    
    # Check Copyable Tags
    kws = data.get("keywords", {})
    print(f"\n[KEYWORDS & COPYABLE TAGS]")
    print(f"- Copyable Tags CSV: {kws.get('copyable_tags_csv')[:100]}...")
    print(f"- Copyable Tags List Count: {len(kws.get('copyable_tags_list', []))}")
    assert len(kws.get("copyable_tags_list", [])) > 0
    assert len(kws.get("copyable_tags_csv", "")) > 0

    print("\n--- 3. Testing Keyword Search with Geo ('AI', 'US') ---")
    kw_res = client.post("/api/analyze/keyword", json={"keyword": "AI", "geo": "US"})
    assert kw_res.status_code == 200
    kw_data = kw_res.json()
    print(f"Keyword: {kw_data.get('keyword')}, Geo: {kw_data.get('geo')}, Trend Score: {kw_data.get('trend_score')}")

    print("\n--- 4. Testing Publish Time Checker (UC...) in Free Mode ---")
    uc_res = client.post("/api/channel/publish-times", json={
        "channel_id": "UCX6OQ3DkcsbYNE6H8uQQuVA",
        "limit": 5
    })
    assert uc_res.status_code == 200
    uc_data = uc_res.json()
    print(f"Channel: {uc_data.get('channel_title')} ({uc_data.get('channel_id')})")
    print(f"Total videos: {uc_data.get('total_videos')}")
    print(f"Extraction mode: {uc_data.get('extraction_mode')}")
    assert uc_data.get("total_videos") > 0
    assert len(uc_data.get("videos")) > 0
    sample_v = uc_data["videos"][0]
    print(f"Sample Video: {sample_v['title'][:40]}... | Date: {sample_v['publish_date']} | Time: {sample_v['publish_time']} | Day: {sample_v['publish_weekday']}")
    assert len(sample_v["publish_time"]) == 8  # HH:mm:ss
    assert "tsv_content" in uc_data
    assert "STT\tVideo ID\tTiêu đề" in uc_data["tsv_content"]

    print("\n>>> ALL UPGRADE TESTS PASSED WITH 100% SUCCESS! <<<")

if __name__ == "__main__":
    test_upgraded_features()
