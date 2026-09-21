import datetime
from collections import defaultdict
from typing import List, Dict, Any, Optional

# Bản đồ thông tin múi giờ và thói quen xem video của các quốc gia quy đổi sang giờ Việt Nam (UTC+7)
COUNTRY_TIMEZONE_PROFILES = {
    "US": {
        "name": "Hoa Kỳ (Mỹ)",
        "utc_offset": -5,  # EST chuẩn (chậm hơn VN 12 tiếng)
        "tz_name": "EST (Miền Đông Mỹ, UTC-5)",
        "prime_view_local": "18:00 - 22:00 (Tối Mỹ)",
        "prime_view_vn": "06:00 - 10:00 (Sáng hôm sau)",
        "best_upload_local": "14:00 - 16:00 (Chiều Mỹ)",
        "best_upload_vn": "02:00 - 04:00 (Sáng hôm sau)",
        "weekend_view_vn": "21:00 - 00:00 (Đêm Việt Nam)",
        "weekend_upload_vn": "19:00 - 21:00 (Tối Việt Nam)",
        "tip": "Khán giả Mỹ xem nhiều nhất vào chiều tối (18h-22h EST, tức 6h-10h sáng VN). Đăng lúc 2h-4h sáng VN giúp thuật toán YouTube kịp xử lý chất lượng cao (HD/4K) và bắt đầu đề xuất đúng đỉnh xem!"
    },
    "GB": {
        "name": "Vương Quốc Anh (UK)",
        "utc_offset": 0,  # Chậm hơn VN 7 tiếng
        "tz_name": "GMT / BST (London, UTC+0)",
        "prime_view_local": "18:00 - 22:00 (Tối Anh)",
        "prime_view_vn": "01:00 - 05:00 (Rạng sáng hôm sau)",
        "best_upload_local": "14:00 - 16:00 (Chiều London)",
        "best_upload_vn": "21:00 - 23:00 (Tối Việt Nam)",
        "weekend_view_vn": "17:00 - 20:00 (Chiều Việt Nam)",
        "weekend_upload_vn": "15:00 - 17:00 (Chiều Việt Nam)",
        "tip": "Khán giả Anh xem nhiều từ 18h - 22h giờ London (tức 1h - 5h sáng VN). Đăng vào khoảng 21h - 23h đêm VN là thời điểm vàng để đón trọn dòng view châu Âu."
    },
    "JP": {
        "name": "Nhật Bản",
        "utc_offset": 9,  # Sớm hơn VN 2 tiếng
        "tz_name": "JST (Tokyo, UTC+9)",
        "prime_view_local": "18:00 - 22:00 (Tối Nhật Bản)",
        "prime_view_vn": "16:00 - 20:00 (Chiều tối VN)",
        "best_upload_local": "15:00 - 17:00 (Chiều Tokyo)",
        "best_upload_vn": "13:00 - 15:00 (Đầu giờ chiều VN)",
        "weekend_view_vn": "10:00 - 14:00 (Trưa Việt Nam)",
        "weekend_upload_vn": "08:00 - 10:00 (Sáng Việt Nam)",
        "tip": "Nhật Bản đi trước Việt Nam 2 tiếng. Lượng người xem cao nhất từ 18h - 22h JST (16h - 20h VN). Bạn nên đăng lúc 13h - 15h chiều VN để đón đầu người xem sau giờ tan sở."
    },
    "KR": {
        "name": "Hàn Quốc",
        "utc_offset": 9,  # Sớm hơn VN 2 tiếng
        "tz_name": "KST (Seoul, UTC+9)",
        "prime_view_local": "18:00 - 22:00 (Tối Hàn Quốc)",
        "prime_view_vn": "16:00 - 20:00 (Chiều tối VN)",
        "best_upload_local": "15:00 - 17:00 (Chiều Seoul)",
        "best_upload_vn": "13:00 - 15:00 (Đầu giờ chiều VN)",
        "weekend_view_vn": "10:00 - 14:00 (Trưa Việt Nam)",
        "weekend_upload_vn": "08:00 - 10:00 (Sáng Việt Nam)",
        "tip": "Hàn Quốc đi trước Việt Nam 2 tiếng. Lượng xem YouTube cao nhất từ 18h - 22h KST (16h - 20h VN). Đăng vào khoảng 13h - 15h giờ VN sẽ tối ưu nhất."
    },
    "DE": {
        "name": "Đức & Trung Âu",
        "utc_offset": 1,  # Chậm hơn VN 6 tiếng
        "tz_name": "CET (Berlin, UTC+1)",
        "prime_view_local": "18:00 - 22:00 (Tối Đức)",
        "prime_view_vn": "00:00 - 04:00 (Rạng sáng hôm sau)",
        "best_upload_local": "14:00 - 16:00 (Chiều Berlin)",
        "best_upload_vn": "20:00 - 22:00 (Tối Việt Nam)",
        "weekend_view_vn": "16:00 - 20:00 (Chiều tối VN)",
        "weekend_upload_vn": "14:00 - 16:00 (Chiều VN)",
        "tip": "Khán giả Đức xem nhiều sau 18h (tức từ 0h đêm VN). Đăng lúc 20h - 22h tối VN là thời điểm chuẩn xác nhất để thuật toán sẵn sàng."
    },
    "IN": {
        "name": "Ấn Độ",
        "utc_offset": 5.5,  # Chậm hơn VN 1.5 tiếng
        "tz_name": "IST (New Delhi, UTC+5:30)",
        "prime_view_local": "18:00 - 22:00 (Tối Ấn Độ)",
        "prime_view_vn": "19:30 - 23:30 (Tối Việt Nam)",
        "best_upload_local": "15:30 - 17:30 (Chiều Ấn Độ)",
        "best_upload_vn": "17:00 - 19:00 (Chiều tối VN)",
        "weekend_view_vn": "13:30 - 17:30 (Chiều VN)",
        "weekend_upload_vn": "11:30 - 13:30 (Trưa VN)",
        "tip": "Ấn Độ chậm hơn Việt Nam 1.5 tiếng. Thời điểm vàng khán giả Ấn xem nhiều nhất là 19h30 - 23h30 giờ VN. Bạn nên đăng lúc 17h - 19h tối VN."
    },
    "BR": {
        "name": "Brazil",
        "utc_offset": -3,  # Chậm hơn VN 10 tiếng
        "tz_name": "BRT (Sao Paulo, UTC-3)",
        "prime_view_local": "18:00 - 22:00 (Tối Brazil)",
        "prime_view_vn": "04:00 - 08:00 (Sáng hôm sau)",
        "best_upload_local": "15:00 - 17:00 (Chiều Brazil)",
        "best_upload_vn": "01:00 - 03:00 (Rạng sáng VN)",
        "weekend_view_vn": "22:00 - 02:00 (Đêm Việt Nam)",
        "weekend_upload_vn": "20:00 - 22:00 (Tối Việt Nam)",
        "tip": "Brazil chậm hơn Việt Nam 10 tiếng. Giờ cao điểm xem ở Brazil (18h-22h) tương đương 4h-8h sáng hôm sau tại VN. Đăng từ 1h-3h sáng VN là đẹp nhất."
    },
    "FR": {
        "name": "Pháp (France)",
        "utc_offset": 1,  # Chậm hơn VN 6 tiếng
        "tz_name": "CET / CEST (Paris, UTC+1)",
        "prime_view_local": "18:00 - 22:00 (Tối Paris)",
        "prime_view_vn": "00:00 - 04:00 (Rạng sáng hôm sau)",
        "best_upload_local": "14:00 - 16:00 (Chiều Paris)",
        "best_upload_vn": "20:00 - 22:00 (Tối Việt Nam)",
        "weekend_view_vn": "16:00 - 20:00 (Chiều tối VN)",
        "weekend_upload_vn": "14:00 - 16:00 (Chiều VN)",
        "tip": "Khán giả Pháp xem nhiều nhất từ 18h - 22h giờ Paris (tức 0h - 4h sáng hôm sau tại VN). Đăng từ 20h - 22h tối VN giúp video kịp xử lý chất lượng cao và đón trọn đỉnh xem tại Pháp!"
    },
    "IT": {
        "name": "Ý (Italy)",
        "utc_offset": 1,  # Chậm hơn VN 6 tiếng
        "tz_name": "CET / CEST (Rome, UTC+1)",
        "prime_view_local": "18:00 - 22:00 (Tối Rome)",
        "prime_view_vn": "00:00 - 04:00 (Rạng sáng hôm sau)",
        "best_upload_local": "14:00 - 16:00 (Chiều Rome)",
        "best_upload_vn": "20:00 - 22:00 (Tối Việt Nam)",
        "weekend_view_vn": "16:00 - 20:00 (Chiều tối VN)",
        "weekend_upload_vn": "14:00 - 16:00 (Chiều VN)",
        "tip": "Khán giả Ý có thói quen xem YouTube mạnh nhất vào buổi tối từ 18h - 22h giờ Rome (tức 0h - 4h sáng VN). Đăng vào khoảng 20h - 22h đêm VN là thời điểm vàng tối ưu."
    },
    "VN": {
        "name": "Việt Nam",
        "utc_offset": 7,
        "tz_name": "ICT (Hà Nội, TP.HCM, UTC+7)",
        "prime_view_local": "19:30 - 22:30 (Tối Việt Nam)",
        "prime_view_vn": "19:30 - 22:30 (Tối Việt Nam)",
        "best_upload_local": "17:30 - 19:00 (Chiều tối VN)",
        "best_upload_vn": "17:30 - 19:00 (Chiều tối VN)",
        "weekend_view_vn": "11:30 - 13:30 & 19:30 - 22:30",
        "weekend_upload_vn": "10:30 - 11:30 & 17:30 - 18:30",
        "tip": "Khán giả Việt Nam xem nhiều nhất từ 19h30 đến 22h30. Đăng trước 1-2 tiếng (khoảng 17h30 - 19h00) để video có đà phân phối mạnh nhất."
    }
}

class TimeService:
    def __init__(self):
        pass

    def analyze_upload_times(self, videos: List[Dict[str, Any]], target_geo: str = "US") -> Dict[str, Any]:
        """Phân tích lịch sử thời gian đăng và tính toán giờ vàng quy đổi sang giờ Việt Nam."""
        geo = target_geo.upper().strip() if target_geo else "US"
        profile = COUNTRY_TIMEZONE_PROFILES.get(geo, COUNTRY_TIMEZONE_PROFILES["US"])

        # Phân bố theo giờ trong ngày (giờ Việt Nam: UTC+7)
        hour_views_vn = defaultdict(list)
        hour_counts_vn = defaultdict(int)
        
        # Phân bố theo thứ trong tuần
        days_names = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ Nhật"]
        weekday_views = defaultdict(list)
        weekday_counts = defaultdict(int)

        channel_published_history = []

        for v in videos:
            ts = v.get("timestamp")
            views = v.get("view_count", 0)
            if not ts:
                continue

            # Chuyển về giờ Việt Nam (UTC+7)
            dt_vn = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone(datetime.timedelta(hours=7)))
            h_vn = dt_vn.hour
            weekday_idx = dt_vn.weekday()

            hour_views_vn[h_vn].append(views)
            hour_counts_vn[h_vn] += 1

            weekday_views[weekday_idx].append(views)
            weekday_counts[weekday_idx] += 1

            channel_published_history.append({
                "title": v.get("title", ""),
                "views": views,
                "hour_vn": h_vn,
                "hour_formatted_vn": f"{h_vn:02d}:00",
                "weekday": days_names[weekday_idx],
                "date": dt_vn.strftime("%d/%m/%Y %H:%M")
            })

        # Xây dựng mảng 24 giờ biểu diễn hiệu suất view trung bình
        hours_distribution = []
        for h in range(24):
            v_list = hour_views_vn.get(h, [])
            avg_v = int(sum(v_list) / len(v_list)) if v_list else 0
            cnt = hour_counts_vn.get(h, 0)
            hours_distribution.append({
                "hour": h,
                "label": f"{h:02d}:00",
                "avg_views": avg_v,
                "video_count": cnt
            })

        # Tìm giờ mà các video của kênh đạt view cao nhất trong lịch sử
        sorted_hours = sorted(hours_distribution, key=lambda x: (x["avg_views"], x["video_count"]), reverse=True)
        top_historical_hours = [h for h in sorted_hours if h["avg_views"] > 0][:3]

        # Phân tích ngày trong tuần hiệu quả nhất
        weekdays_distribution = []
        for idx in range(7):
            w_list = weekday_views.get(idx, [])
            avg_w = int(sum(w_list) / len(w_list)) if w_list else 0
            weekdays_distribution.append({
                "day_index": idx,
                "day_name": days_names[idx],
                "avg_views": avg_w,
                "video_count": weekday_counts.get(idx, 0)
            })

        sorted_days = sorted(weekdays_distribution, key=lambda x: (x["avg_views"], x["video_count"]), reverse=True)
        best_days = [d["day_name"] for d in sorted_days if d["video_count"] > 0][:3]
        if not best_days:
            best_days = ["Thứ 6", "Thứ 7", "Chủ Nhật"]

        # Tổng hợp Top 3 Khung Giờ Đăng Khuyến Nghị Cụ Thể (Giờ Việt Nam)
        top_recommendations = [
            {
                "time_slot_vn": profile["best_upload_vn"],
                "target_local_time": profile["best_upload_local"],
                "target_audience": f"Khán giả {profile['name']} xem ngày thường ({profile['prime_view_local']})",
                "recommended_for": f"Đăng lúc {profile['best_upload_vn']} để YouTube kịp xử lý HD và đón đỉnh view {profile['prime_view_vn']} (tương ứng {profile['prime_view_local']})"
            },
            {
                "time_slot_vn": profile["weekend_upload_vn"],
                "target_local_time": "Cuối tuần (Thứ 7 & CN)",
                "target_audience": f"Khán giả {profile['name']} xem cuối tuần ({profile['weekend_view_vn']})",
                "recommended_for": "Video giải trí, đời sống, vlog, nội dung dài thư giãn cuối tuần"
            }
        ]

        if top_historical_hours:
            best_h = top_historical_hours[0]
            top_recommendations.append({
                "time_slot_vn": f"Khung {best_h['label']} (Giờ VN)",
                "target_local_time": "Lịch sử thực tế của kênh",
                "target_audience": "Thời điểm kênh của bạn từng đạt view cao nhất trong lịch sử",
                "recommended_for": f"Kênh đã từng đạt trung bình {best_h['avg_views']:,} views khi đăng lúc {best_h['label']}"
            })

        return {
            "target_country_code": geo,
            "target_country_name": profile["name"],
            "target_timezone_name": profile["tz_name"],
            "strategy_tip": profile["tip"],
            "best_upload_time_vn": profile["best_upload_vn"],
            "peak_view_time_vn": profile["prime_view_vn"],
            "suggested_weekday_vn": profile["best_upload_vn"],
            "suggested_weekend_vn": profile["weekend_upload_vn"],
            "best_upload_desc": f"Nên đăng trước 2-3 tiếng để thuật toán xử lý HD và đón đỉnh xem {profile['prime_view_local']}.",
            "peak_view_desc": f"Khung giờ khán giả {profile['name']} tập trung xem nhiều nhất trong ngày ({profile['prime_view_local']}).",
            "best_day_of_week": best_days[0] if best_days else "Thứ 5",
            "best_weekdays": best_days,
            "hours_distribution": hours_distribution,
            "weekdays_distribution": weekdays_distribution,
            "top_recommendations": top_recommendations
        }
