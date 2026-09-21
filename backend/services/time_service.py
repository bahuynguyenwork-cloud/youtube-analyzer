import datetime
import re
from collections import defaultdict
from typing import List, Dict, Any, Optional

# Bản đồ thông tin múi giờ các quốc gia quy đổi sang giờ Việt Nam (UTC+7)
COUNTRY_TIMEZONE_PROFILES = {
    "US": {
        "name": "Hoa Kỳ (Mỹ)",
        "utc_offset": -5,  # EST chuẩn (chậm hơn VN 12 tiếng)
        "tz_name": "EST (Miền Đông Mỹ, UTC-5)",
    },
    "GB": {
        "name": "Vương Quốc Anh (UK)",
        "utc_offset": 0,  # London (chậm hơn VN 7 tiếng)
        "tz_name": "GMT / BST (London, UTC+0)",
    },
    "JP": {
        "name": "Nhật Bản",
        "utc_offset": 9,  # Tokyo (sớm hơn VN 2 tiếng)
        "tz_name": "JST (Tokyo, UTC+9)",
    },
    "KR": {
        "name": "Hàn Quốc",
        "utc_offset": 9,  # Seoul (sớm hơn VN 2 tiếng)
        "tz_name": "KST (Seoul, UTC+9)",
    },
    "DE": {
        "name": "Đức & Trung Âu",
        "utc_offset": 1,  # Berlin (chậm hơn VN 6 tiếng)
        "tz_name": "CET (Berlin, UTC+1)",
    },
    "IN": {
        "name": "Ấn Độ",
        "utc_offset": 5.5,  # New Delhi (chậm hơn VN 1.5 tiếng)
        "tz_name": "IST (New Delhi, UTC+5:30)",
    },
    "BR": {
        "name": "Brazil",
        "utc_offset": -3,  # Sao Paulo (chậm hơn VN 10 tiếng)
        "tz_name": "BRT (Sao Paulo, UTC-3)",
    },
    "FR": {
        "name": "Pháp (France)",
        "utc_offset": 1,  # Paris (chậm hơn VN 6 tiếng)
        "tz_name": "CET / CEST (Paris, UTC+1)",
    },
    "IT": {
        "name": "Ý (Italy)",
        "utc_offset": 1,  # Rome (chậm hơn VN 6 tiếng)
        "tz_name": "CET / CEST (Rome, UTC+1)",
    },
    "VN": {
        "name": "Việt Nam",
        "utc_offset": 7,  # Giờ ICT (UTC+7)
        "tz_name": "ICT (Hà Nội, TP.HCM, UTC+7)",
    }
}

# Hồ sơ 2 khung giờ đăng tối ưu theo từng chủ đề / ngách
NICHE_PROFILES = {
    "general": {
        "name_vi": "Giải trí đại chúng / Vlog / Đời sống",
        "upload_1_start": 16.5,
        "upload_1_end": 18.5,
        "upload_1_label": "Khung chính: Chiều tối ngày thường",
        "upload_2_start": 10.5,
        "upload_2_end": 12.0,
        "upload_2_label": "Khung phụ: Trưa & Cuối tuần",
        "best_weekdays": ["Thứ 6", "Thứ 7", "Chủ Nhật"],
        "behavior_insight": "Khán giả đại chúng xem nhiều nhất vào các buổi tối sau giờ tan làm và trưa cuối tuần.",
        "keywords": []
    },
    "horror": {
        "name_vi": "Kinh dị & Truyện ma / Quái đàm",
        "upload_1_start": 19.5,
        "upload_1_end": 21.0,
        "upload_1_label": "Khung chính: Đầu tối trước giờ ngủ",
        "upload_2_start": 21.5,
        "upload_2_end": 23.0,
        "upload_2_label": "Khung phụ: Đêm khuya cho cú đêm",
        "best_weekdays": ["Thứ 5", "Thứ 6", "Thứ 7", "Chủ Nhật"],
        "behavior_insight": "Khán giả truyện ma & kinh dị có thói quen nghe vào đêm khuya trước khi đi ngủ. Nên đăng từ đầu tối đến đêm muộn.",
        "keywords": [
            "truyện ma", "quái đàm", "creepypasta", "scary story", "scary stories", "ghost story", "ghost stories",
            "paranormal activity", "haunted house", "tâm linh huyền bí", "kinh dị", "cõi âm", "chuyện ma",
            "nghe truyện ma", "공포 괴담", "귀신 이야기", "무서운 이야기", "괴담", "怪談", "ホラー"
        ]
    },
    "education": {
        "name_vi": "Học tập / Ngoại ngữ / Giáo dục",
        "upload_1_start": 5.5,
        "upload_1_end": 7.0,
        "upload_1_label": "Khung chính: Sáng sớm trước giờ học/làm",
        "upload_2_start": 17.5,
        "upload_2_end": 19.0,
        "upload_2_label": "Khung phụ: Tối học bài sau giờ làm",
        "best_weekdays": ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5"],
        "behavior_insight": "Người học tập trung nghe bài vào sáng sớm thức dậy hoặc tối sau giờ làm. Ngày trong tuần xem nhiều hơn cuối tuần.",
        "keywords": [
            "học tiếng anh", "learn english", "tiếng anh giao tiếp", "ngữ pháp tiếng anh", "luyện thi toeic",
            "ielts preparation", "english lesson", "english lessons", "bài giảng", "khóa học online",
            "luyện nghe tiếng anh", "từ vựng tiếng anh", "phát âm tiếng anh", "영어 회화", "영어 공부", "토익",
            "英語学習", "英会話"
        ]
    },
    "drama_story": {
        "name_vi": "Drama / Bắt gian / Hóng biến / Gia đình",
        "upload_1_start": 10.5,
        "upload_1_end": 11.5,
        "upload_1_label": "Khung chính: Đón giờ nghỉ trưa ăn cơm",
        "upload_2_start": 18.5,
        "upload_2_end": 20.0,
        "upload_2_label": "Khung phụ: Đón ca tối sau bữa cơm",
        "best_weekdays": ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Chủ Nhật"],
        "behavior_insight": "Khán giả drama hóng biến mạnh nhất lúc ăn trưa và tối thư giãn.",
        "keywords": [
            "bắt gian", "ngoại tình", "đánh ghen", "tiểu tam", "mẹ chồng nàng dâu", "cheating revenge",
            "affair story", "divorce story", "con giáp thứ 13", "drama bắt gian", "chuyện mẹ chồng",
            "불륜", "막장", "시월드", "不倫", "浮気", "修羅場"
        ]
    },
    "finance_biz": {
        "name_vi": "Tài chính / Crypto / MMO / Đầu tư",
        "upload_1_start": 6.5,
        "upload_1_end": 7.5,
        "upload_1_label": "Khung chính: Sáng trước giờ mở phiên",
        "upload_2_start": 15.5,
        "upload_2_end": 16.5,
        "upload_2_label": "Khung phụ: Chiều trước khi đóng phiên",
        "best_weekdays": ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5"],
        "behavior_insight": "Khán giả tài chính theo sát lịch làm việc và phiên giao dịch từ Thứ 2 đến Thứ 5.",
        "keywords": [
            "chứng khoán", "đầu tư tài chính", "tiền điện tử", "crypto trading", "stock market",
            "forex trading", "bitcoin analysis", "mmo kiếm tiền", "kiếm tiền online", "phân tích kỹ thuật",
            "kinh doanh làm giàu", "quản lý tài chính", "주식 투자", "가상화폐", "株式投資", "暗号資産"
        ]
    },
    "gaming": {
        "name_vi": "Gaming / Trò chơi / Esports",
        "upload_1_start": 14.0,
        "upload_1_end": 15.5,
        "upload_1_label": "Khung chính: Chiều đón tan học",
        "upload_2_start": 18.5,
        "upload_2_end": 20.0,
        "upload_2_label": "Khung phụ: Tối cày game & Cuối tuần",
        "best_weekdays": ["Thứ 6", "Thứ 7", "Chủ Nhật"],
        "behavior_insight": "Khán giả game xem nhiều từ chiều tan học và bùng nổ tối cuối tuần.",
        "keywords": [
            "gameplay", "walkthrough", "chơi game", "game thủ", "livestream game", "playthrough",
            "minecraft survival", "roblox gameplay", "esports", "tựa game", "gaming channel",
            "highlight liên quân", "game bắn súng", "게임 플레이", "ゲーム実況"
        ]
    },
    "kids": {
        "name_vi": "Trẻ em / Hoạt hình thiếu nhi",
        "upload_1_start": 5.5,
        "upload_1_end": 6.5,
        "upload_1_label": "Khung chính: Sáng trước giờ đi học",
        "upload_2_start": 15.5,
        "upload_2_end": 16.5,
        "upload_2_label": "Khung phụ: Chiều cơm nước & Sáng cuối tuần",
        "best_weekdays": ["Thứ 7", "Chủ Nhật", "Thứ 6"],
        "behavior_insight": "Phụ huynh mở cho con xem sáng trước giờ đi học, chiều tắm rửa cơm nước và sáng cuối tuần.",
        "keywords": [
            "nhạc thiếu nhi", "hoạt hình thiếu nhi", "nursery rhymes", "kids animation", "cartoons for kids",
            "baby songs", "trẻ mầm non", "đồng dao", "ca nhạc thiếu nhi", "동요", "어린이 만화", "子供向け", "童謡"
        ]
    },
    "true_crime": {
        "name_vi": "Vụ án có thật / Kỳ án / Trinh thám",
        "upload_1_start": 18.0,
        "upload_1_end": 19.5,
        "upload_1_label": "Khung chính: Đầu tối sau giờ làm",
        "upload_2_start": 20.5,
        "upload_2_end": 22.0,
        "upload_2_label": "Khung phụ: Tối muộn thư giãn sâu",
        "best_weekdays": ["Thứ 5", "Thứ 6", "Thứ 7", "Chủ Nhật"],
        "behavior_insight": "Kỳ án và phim tài liệu điều tra đòi hỏi tập trung cao, xem nhiều vào tối cuối tuần.",
        "keywords": [
            "vụ án có thật", "kỳ án", "trinh thám", "hồ sơ vụ án", "true crime story",
            "serial killer documentary", "unsolved mystery crime", "điều tra phá án", "hồ sơ tội phạm",
            "사건 파일", "미제 사건", "未解決事件", "殺人事件"
        ]
    }
}

def convert_local_hour_to_vn(hour: float, utc_offset: float) -> float:
    """Chuyển đổi giờ địa phương sang giờ Việt Nam (UTC+7)."""
    return (hour - utc_offset + 7.0) % 24.0

def format_hour_float(h: float) -> str:
    """Format số thực giờ thành chuỗi HH:MM."""
    h_int = int(h) % 24
    m_int = int(round((h - int(h)) * 60))
    if m_int >= 60:
        h_int = (h_int + 1) % 24
        m_int = 0
    return f"{h_int:02d}:{m_int:02d}"

def convert_range_to_vn(start_local: float, end_local: float, utc_offset: float) -> str:
    """Chuyển dải giờ địa phương sang dải giờ Việt Nam dạng HH:MM - HH:MM."""
    s_vn = convert_local_hour_to_vn(start_local, utc_offset)
    e_vn = convert_local_hour_to_vn(end_local, utc_offset)
    return f"{format_hour_float(s_vn)} - {format_hour_float(e_vn)}"


class TimeService:
    def __init__(self):
        pass

    def detect_channel_niche(
        self,
        videos: List[Dict[str, Any]],
        channel_keywords: Optional[List[str]] = None,
        channel_title: str = "",
        channel_description: str = ""
    ) -> str:
        """Tự động phân tích và nhận diện ngách nội dung của kênh từ từ khóa, tiêu đề và mô tả.
        Chỉ phân loại khi có bằng chứng rõ ràng (cụm từ cụ thể), mặc định luôn là general (đại chúng).
        """
        corpus = [channel_title, channel_description]
        if channel_keywords:
            corpus.extend(channel_keywords)

        for v in (videos or [])[:30]:
            corpus.append(v.get("title", ""))
            desc = v.get("description", "")
            if desc:
                corpus.append(desc[:200])

        full_text = " ".join(corpus).lower()

        scores = {}
        for niche_key, niche_info in NICHE_PROFILES.items():
            if niche_key == "general":
                continue
            score = 0
            for kw in niche_info.get("keywords", []):
                kw_clean = kw.strip().lower()
                if not kw_clean:
                    continue
                # Đếm số lần xuất hiện của cụm từ chính xác
                count = full_text.count(kw_clean)
                if count > 0:
                    score += count * 3
            scores[niche_key] = score

        if not scores:
            return "general"

        best_niche = max(scores, key=scores.get)
        # Yêu cầu điểm số tối thiểu là 6 (ít nhất 2 lần xuất hiện cụm từ ngách đặc thù)
        if scores.get(best_niche, 0) < 6:
            return "general"
        return best_niche

    def analyze_upload_times(
        self,
        videos: List[Dict[str, Any]],
        target_geo: str = "US",
        channel_keywords: Optional[List[str]] = None,
        channel_title: str = "",
        channel_description: str = "",
        forced_niche: Optional[str] = None
    ) -> Dict[str, Any]:
        """Tính toán 1 hoặc 2 khung giờ đăng vàng theo Chủ đề & Quốc gia quy đổi sang giờ Việt Nam (UTC+7)."""
        geo = target_geo.upper().strip() if target_geo else "US"
        country_prof = COUNTRY_TIMEZONE_PROFILES.get(geo, COUNTRY_TIMEZONE_PROFILES["US"])
        utc_offset = country_prof["utc_offset"]

        # 1. Xác định ngách nội dung của kênh
        if forced_niche and forced_niche in NICHE_PROFILES:
            niche_key = forced_niche
        else:
            niche_key = self.detect_channel_niche(
                videos=videos,
                channel_keywords=channel_keywords,
                channel_title=channel_title,
                channel_description=channel_description
            )
        niche_prof = NICHE_PROFILES.get(niche_key, NICHE_PROFILES["general"])

        # 2. Quy đổi 2 khung giờ đăng sang Giờ Việt Nam (UTC+7)
        upload_1_vn = convert_range_to_vn(niche_prof["upload_1_start"], niche_prof["upload_1_end"], utc_offset)
        upload_2_vn = convert_range_to_vn(niche_prof["upload_2_start"], niche_prof["upload_2_end"], utc_offset)

        # 3. Phân tích lịch sử kênh
        hour_views_vn = defaultdict(list)
        hour_counts_vn = defaultdict(int)
        days_names = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ Nhật"]
        weekday_views = defaultdict(list)
        weekday_counts = defaultdict(int)

        for v in (videos or []):
            ts = v.get("timestamp")
            views = v.get("view_count", 0)
            if not ts:
                continue

            dt_vn = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone(datetime.timedelta(hours=7)))
            h_vn = dt_vn.hour
            weekday_idx = dt_vn.weekday()

            hour_views_vn[h_vn].append(views)
            hour_counts_vn[h_vn] += 1
            weekday_views[weekday_idx].append(views)
            weekday_counts[weekday_idx] += 1

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
        historical_best_days = [d["day_name"] for d in sorted_days if d["video_count"] > 0]
        recommended_days = niche_prof.get("best_weekdays", ["Thứ 6", "Thứ 7", "Chủ Nhật"])
        best_day_single = historical_best_days[0] if historical_best_days else recommended_days[0]

        # 4. Lời khuyên chiến lược ngắn gọn, tập trung thẳng vào GIỜ ĐĂNG
        strategy_tip = (
            f"🎯 Chủ đề: {niche_prof['name_vi']} | Thị trường: {country_prof['name']} ({country_prof['tz_name']}). "
            f"{niche_prof['behavior_insight']} "
            f"Khuyến nghị bạn bấm đăng vào Khung 1 ({upload_1_vn}) hoặc Khung 2 ({upload_2_vn}) "
            f"theo giờ Việt Nam để video kịp xử lý HD và bắt đúng sóng người xem bản địa."
        )

        return {
            "target_country_code": geo,
            "target_country_name": country_prof["name"],
            "target_timezone_name": country_prof["tz_name"],
            "detected_niche_code": niche_key,
            "detected_niche_name": niche_prof["name_vi"],
            "niche_behavior_insight": niche_prof["behavior_insight"],
            "strategy_tip": strategy_tip,
            "best_upload_time_vn": upload_1_vn,
            "second_upload_time_vn": upload_2_vn,
            "upload_slot_1_label": niche_prof["upload_1_label"],
            "upload_slot_2_label": niche_prof["upload_2_label"],
            "best_day_of_week": best_day_single,
            "best_weekdays": recommended_days,
            "hours_distribution": hours_distribution,
            "weekdays_distribution": weekdays_distribution
        }


