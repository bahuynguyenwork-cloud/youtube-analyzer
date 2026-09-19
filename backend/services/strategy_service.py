from typing import List, Dict, Any

class StrategyService:
    def __init__(self):
        pass

    def generate_recommendations(
        self,
        channel_meta: Dict[str, Any],
        stats: Dict[str, Any],
        keyword_data: Dict[str, Any],
        trend_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Tự động sinh đề xuất chiến lược nội dung và ý tưởng tiêu đề bắt trend."""
        channel_title = channel_meta.get('channel_title', 'Kênh')
        avg_views = stats.get('avg_views', 0)
        views_to_subs = stats.get('views_to_subs_ratio', 0)
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

        # Đánh giá sức hút so với Subscriber
        if views_to_subs > 25:
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

        return {
            'insights': insights,
            'title_ideas': title_ideas,
            'recommended_tags': recommended_tags,
            'high_impact_focus': high_impact_kws[:5],
            'avoid_or_improve': low_impact_kws[:4]
        }
