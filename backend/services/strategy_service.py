from typing import List, Dict, Any, Optional

GEO_BASE_RPM = {
    "US": 4.5,
    "GB": 4.0,
    "DE": 4.2,
    "CA": 3.8,
    "AU": 4.0,
    "FR": 3.2,
    "JP": 2.8,
    "KR": 2.6,
    "IT": 2.5,
    "BR": 1.2,
    "VN": 0.75,
    "IN": 0.65,
    "GLOBAL": 2.2
}

NICHE_RPM_MULTIPLIERS = {
    "finance_money": 2.3,
    "tech_ai": 1.85,
    "learn_english": 1.45,
    "philosophy": 1.35,
    "elderly_wisdom": 1.25,
    "true_crime": 1.25,
    "history_geopolitics": 1.30,
    "space_science": 1.35,
    "horror_stories": 1.10,
    "spicy_18_drama": 1.15,
    "father_inlaw_drama": 1.15,
    "mother_inlaw_drama": 1.15,
    "infidelity_revenge": 1.15,
    "drama_expose": 1.10,
    "reddit_stories": 1.10,
    "buddhism": 1.05,
    "christianity_bible": 1.05,
    "bible": 1.05,
    "christianity": 1.05,
    "religion": 1.05,
    "recap_stories": 0.95,
    "travel_vlog": 1.15,
    "vlog": 1.15,
    "travel": 1.15,
    "gaming": 0.75,
    "entertainment": 0.85
}

USD_VND_RATE = 25400

class StrategyService:
    def __init__(self):
        pass

    def calculate_estimated_earnings(
        self,
        target_geo: str = "US",
        niche_key: str = "entertainment",
        avg_views: int = 0,
        upload_freq_days: float = 7.0
    ) -> Dict[str, Any]:
        """Ước tính doanh thu và RPM AdSense theo quốc gia mục tiêu và ngách nội dung."""
        geo = (target_geo or "US").upper().strip()
        base_rpm = GEO_BASE_RPM.get(geo, GEO_BASE_RPM.get("GLOBAL", 2.2))
        mult = NICHE_RPM_MULTIPLIERS.get(niche_key, 1.0)

        avg_rpm = round(base_rpm * mult, 2)
        min_rpm = round(avg_rpm * 0.70, 2)
        max_rpm = round(avg_rpm * 1.45, 2)

        safe_views = max(0, avg_views)
        safe_freq = max(1.0, upload_freq_days if upload_freq_days > 0 else 7.0)
        videos_per_month = round(min(60.0, 30.0 / safe_freq), 1)
        monthly_views = int(videos_per_month * safe_views)

        monthly_usd_min = round((monthly_views / 1000.0) * min_rpm, 1)
        monthly_usd_max = round((monthly_views / 1000.0) * max_rpm, 1)
        monthly_usd_avg = round((monthly_views / 1000.0) * avg_rpm, 1)

        return {
            "target_geo": geo,
            "niche_key": niche_key,
            "currency_rate": USD_VND_RATE,
            "rpm_usd": {
                "min": min_rpm,
                "max": max_rpm,
                "avg": avg_rpm
            },
            "rpm_vnd": {
                "min": int(min_rpm * USD_VND_RATE),
                "max": int(max_rpm * USD_VND_RATE),
                "avg": int(avg_rpm * USD_VND_RATE)
            },
            "earnings_10k": {
                "usd": round(avg_rpm * 10, 1),
                "vnd": int(avg_rpm * 10 * USD_VND_RATE)
            },
            "earnings_100k": {
                "usd": round(avg_rpm * 100, 1),
                "vnd": int(avg_rpm * 100 * USD_VND_RATE)
            },
            "earnings_1m": {
                "usd": round(avg_rpm * 1000, 1),
                "vnd": int(avg_rpm * 1000 * USD_VND_RATE)
            },
            "monthly_estimate": {
                "videos_per_month": videos_per_month,
                "estimated_views": monthly_views,
                "usd_min": monthly_usd_min,
                "usd_max": monthly_usd_max,
                "usd_avg": monthly_usd_avg,
                "vnd_min": int(monthly_usd_min * USD_VND_RATE),
                "vnd_max": int(monthly_usd_max * USD_VND_RATE),
                "vnd_avg": int(monthly_usd_avg * USD_VND_RATE)
            }
        }

    def generate_recommendations(
        self,
        channel_meta: Dict[str, Any],
        stats: Dict[str, Any],
        keyword_data: Dict[str, Any],
        trend_data: Dict[str, Any],
        target_geo: str = "US",
        niche_key: str = "entertainment"
    ) -> Dict[str, Any]:
        """Tự động sinh đề xuất chiến lược nội dung, ý tưởng tiêu đề bắt trend và dự đoán doanh thu RPM."""
        channel_title = channel_meta.get('channel_title', 'Kênh')
        avg_views = stats.get('avg_views', 0)
        is_subs_hidden = stats.get('is_subs_hidden', False)
        views_to_subs = stats.get('views_to_subs_ratio')
        upload_freq = stats.get('upload_frequency_days', 0)
        outliers = stats.get('outliers', [])
        
        top_kws = keyword_data.get('top_keywords', [])
        high_impact_kws = keyword_data.get('high_impact_keywords', [])
        low_impact_kws = keyword_data.get('low_impact_keywords', [])
        hashtags = keyword_data.get('hashtags', [])
        
        trend_score = trend_data.get('trend_score', 50)
        primary_kw = trend_data.get('primary_keyword') or (top_kws[0]['keyword'] if top_kws else 'chủ đề này')

        # 1. Nhận định chuyên sâu
        insights = []

        # Đánh giá sức hút so với Subscriber (xử lý trường hợp kênh ẩn Sub)
        if is_subs_hidden or views_to_subs is None:
            insights.append({
                'type': 'info',
                'title': 'Kênh đang ẩn số người đăng ký',
                'description': f'Kênh hiện đang tắt hiển thị số lượng Subscriber công khai. Lượt xem trung bình của các video dài đạt {avg_views:,} view/video. Hãy tập trung đẩy mạnh CTR Thumbnail và giữ chân người xem 30 giây đầu để kích hoạt thuật toán đề xuất trang chủ.'
            })
        elif views_to_subs > 25:
            insights.append({
                'type': 'success',
                'title': 'Sức hút vượt trội so với lượng Sub',
                'description': f'Tỉ lệ xem/sub đạt {views_to_subs}%. Nội dung của bạn có khả năng viral tự nhiên và liên tục được YouTube đề xuất tới khán giả mới ngoài tệp sub hiện tại.'
            })
        elif views_to_subs > 8:
            insights.append({
                'type': 'info',
                'title': 'Khán giả trung thành ổn định',
                'description': f'Tỉ lệ xem/sub đạt {views_to_subs}%. Bạn có tệp người xem trung thành khá tốt. Hãy tập trung tối ưu CTR của Thumbnail để kéo thêm view từ trang chủ (Browse Features).'
            })
        else:
            insights.append({
                'type': 'warning',
                'title': 'Cần kích hoạt lại tệp người đăng ký',
                'description': f'Tỉ lệ xem/sub hiện tại ({views_to_subs}%) còn khiêm tốn. Có thể nhiều người đăng ký cũ đã ít tương tác. Hãy thử nghiệm đổi format mở đầu video (Hook 30s đầu) hoặc khảo sát qua tab Community.'
            })

        # Đánh giá tần suất ra video
        if upload_freq > 14:
            insights.append({
                'type': 'warning',
                'title': 'Tần suất ra video còn khá thưa',
                'description': f'Khoảng cách trung bình giữa các video là {upload_freq:.1f} ngày. Thuật toán YouTube rất ưu ái các kênh duy trì lịch đăng cố định (tối thiểu 1 video/tuần) để giữ chân khán giả.'
            })
        elif upload_freq <= 4:
            insights.append({
                'type': 'success',
                'title': 'Tần suất sản xuất nội dung rất tích cực',
                'description': f'Kênh ra video đều đặn mỗi {upload_freq:.1f} ngày. Hãy đảm bảo chất lượng hình ảnh thumbnail và giữ vững nhịp độ này.'
            })

        # Phân tích từ khóa gánh view
        if high_impact_kws:
            best_kw = high_impact_kws[0]['keyword']
            mult = high_impact_kws[0]['efficiency_ratio']
            insights.append({
                'type': 'highlight',
                'title': f'Từ khóa "Mỏ vàng": "{best_kw}"',
                'description': f'Các video có chứa "{best_kw}" mang lại lượng xem cao gấp {mult}x so với mức trung bình của kênh. Nên xây dựng chuỗi video (Playlist series) xoay quanh từ khóa này.'
            })

        # 2. Sinh các mẫu tiêu đề bắt trend (Click-worthy Title Ideas)
        target_kw = high_impact_kws[0]['keyword'] if high_impact_kws else primary_kw
        sec_kw = top_kws[1]['keyword'] if len(top_kws) > 1 else 'chi tiết'

        title_ideas = [
            f"Sự Thật Về {target_kw.title()} Mà 99% Mọi Người Đang Hiểu Sai",
            f"Tôi Đã Thử Nghiệm {target_kw.title()} Trong 30 Ngày Và Cái Kết Bất Ngờ",
            f"Hướng Dẫn {target_kw.title()} Từ A-Z Cho Người Mới Bắt Đầu (Cập Nhật Mới)",
            f"Tại Sao {target_kw.title()} Đang Trở Thành Xu Hướng Đột Phá Năm Nay?",
            f"Đừng Bao Giờ Làm {target_kw.title()} Nếu Bạn Chưa Biết Điều Này!",
            f"Top 5 Sai Lầm Khi Tiếp Cận {target_kw.title()} Khiến Bạn Tốn Thời Gian",
            f"So Sánh Thực Tế: {target_kw.title()} vs {sec_kw.title()} - Đâu Là Lựa Chọn Tốt Nhất?",
            f"Bí Quyết Làm Chủ {target_kw.title()} Chỉ Trong 15 Phút"
        ]

        # 3. Gợi ý Hashtags và Thẻ tối ưu SEO
        recommended_tags = [kw['keyword'] for kw in top_kws[:8]]
        if high_impact_kws:
            for hk in high_impact_kws[:3]:
                if hk['keyword'] not in recommended_tags:
                    recommended_tags.append(hk['keyword'])

        # 4. Tính toán dự toán doanh thu RPM
        earnings_data = self.calculate_estimated_earnings(
            target_geo=target_geo,
            niche_key=niche_key,
            avg_views=avg_views,
            upload_freq_days=upload_freq
        )

        return {
            'insights': insights,
            'title_ideas': title_ideas,
            'recommended_tags': recommended_tags,
            'high_impact_focus': high_impact_kws[:5],
            'avoid_or_improve': low_impact_kws[:4],
            'estimated_earnings': earnings_data
        }
