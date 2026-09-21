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
    },
    "quotes_philosophy": {
        "name_vi": "Danh ngôn / Triết lý sống / Động lực & Chữa lành",
        "upload_1_start": 5.0,
        "upload_1_end": 6.5,
        "upload_1_label": "Khung chính: Sáng sớm nạp năng lượng & suy ngẫm",
        "upload_2_start": 19.5,
        "upload_2_end": 21.0,
        "upload_2_label": "Khung phụ: Tối thư giãn, chữa lành trước khi ngủ",
        "best_weekdays": ["Chủ Nhật", "Thứ 2", "Thứ 5", "Thứ 6"],
        "behavior_insight": "Khán giả nghe danh ngôn & triết lý sống vào sáng sớm thức dậy hoặc tối muộn trước khi ngủ để chữa lành và tìm động lực.",
        "keywords": [
            "명언", "인생", "인생철학", "철학", "지혜", "동기부여", "위로", "힐링", "인생 조언", "자기계발", "성공명언", "좋은글", "마인드셋",
            "danh ngôn", "triết lý", "triết lý sống", "châm ngôn", "bài học cuộc sống", "chữa lành", "động lực", "đạo lý", "phát triển bản thân", "nhân sinh", "sách nói",
            "quotes", "life quotes", "philosophy", "stoic", "stoicism", "wisdom", "motivation", "motivational", "healing", "life lessons", "mindset", "self improvement", "deep quotes",
            "名言", "人生の教訓", "哲学"
        ]
    },
    "health_wellness": {
        "name_vi": "Sức khỏe / Y học / Dinh dưỡng & Trường thọ",
        "upload_1_start": 6.0,
        "upload_1_end": 7.5,
        "upload_1_label": "Khung chính: Sáng sớm khởi động ngày mới",
        "upload_2_start": 17.0,
        "upload_2_end": 18.5,
        "upload_2_label": "Khung phụ: Chiều tối chuẩn bị bữa ăn",
        "best_weekdays": ["Thứ 2", "Thứ 3", "Thứ 7", "Chủ Nhật"],
        "behavior_insight": "Người quan tâm sức khỏe thường tìm kiếm kiến thức vào sáng sớm hoặc chiều tối trước bữa cơm gia đình.",
        "keywords": [
            "건강", "장수", "의학", "의사", "영양", "면역력", "당뇨", "혈압", "암예방", "운동", "다이어트", "무병장수",
            "sức khỏe", "y học", "dinh dưỡng", "bác sĩ", "chữa bệnh", "sống khỏe", "trường thọ", "bài thuốc", "giảm cân", "thực phẩm chức năng", "yoga", "thể hình",
            "health", "wellness", "longevity", "nutrition", "medical", "doctor", "healthy diet", "weight loss", "fitness", "immune system", "healthy lifestyle"
        ]
    },
    "music_relaxation": {
        "name_vi": "Âm nhạc / Lofi / Nhạc ngủ & ASMR",
        "upload_1_start": 17.0,
        "upload_1_end": 18.5,
        "upload_1_label": "Khung chính: Chiều tối thư giãn sau giờ làm",
        "upload_2_start": 21.0,
        "upload_2_end": 22.5,
        "upload_2_label": "Khung phụ: Đêm khuya ngủ ngon & ASMR",
        "best_weekdays": ["Thứ 5", "Thứ 6", "Thứ 7", "Chủ Nhật"],
        "behavior_insight": "Khán giả nghe nhạc thư giãn/ASMR tập trung cao độ vào buổi tối và đêm khuya trước khi ngủ.",
        "keywords": [
            "음악", "수면", "명상", "수면음악", "힐링음악", "노래", "playlist", "플레이리스트",
            "nhạc thư giãn", "nhạc ngủ ngon", "nhạc không lời", "nhạc lofi", "nhạc thiền", "nhạc chill", "asmr", "playlist nhạc",
            "relaxing music", "sleep music", "lofi hip hop", "chill beats", "meditation music", "ambient music", "piano music", "asmr", "deep sleep"
        ]
    },
    "food_cooking": {
        "name_vi": "Ẩm thực / Nấu ăn & Mukbang",
        "upload_1_start": 10.3,
        "upload_1_end": 11.8,
        "upload_1_label": "Khung chính: Trưa đón giờ thèm ăn",
        "upload_2_start": 17.0,
        "upload_2_end": 18.3,
        "upload_2_label": "Khung phụ: Chiều tối chuẩn bị bữa ăn",
        "best_weekdays": ["Thứ 6", "Thứ 7", "Chủ Nhật"],
        "behavior_insight": "Khán giả ẩm thực xem nhiều nhất ngay trước giờ cơm trưa hoặc chiều tối để tìm cảm hứng ăn uống/nấu nướng.",
        "keywords": [
            "요리", "먹방", "레시피", "맛집", "음식", "집밥",
            "món ngon", "nấu ăn", "công thức nấu", "ẩm thực", "hướng dẫn nấu ăn", "mukbang", "quán ăn ngon", "món ăn gia đình",
            "cooking", "recipe", "recipes", "food", "street food", "mukbang", "delicious food", "chef", "baking", "tasty"
        ]
    },
    "tech_gadgets": {
        "name_vi": "Công nghệ / Review thiết bị & Hướng dẫn AI",
        "upload_1_start": 11.5,
        "upload_1_end": 12.5,
        "upload_1_label": "Khung chính: Nghỉ trưa lướt tin công nghệ",
        "upload_2_start": 18.5,
        "upload_2_end": 20.0,
        "upload_2_label": "Khung phụ: Tối sau giờ làm",
        "best_weekdays": ["Thứ 3", "Thứ 4", "Thứ 5", "Thứ 7"],
        "behavior_insight": "Dân công nghệ thích theo dõi tin tức sản phẩm mới vào giờ nghỉ trưa và tối sau giờ làm.",
        "keywords": [
            "테크", "스마트폰", "리뷰", "인공지능", "it리뷰", "가젯",
            "công nghệ", "đánh giá điện thoại", "review công nghệ", "trí tuệ nhân tạo", "mở hộp", "hướng dẫn phần mềm", "laptop review", "thủ thuật",
            "technology", "tech review", "smartphone review", "unboxing", "gadgets", "artificial intelligence", "software tutorial", "pc build"
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
        """Tự động phân tích và nhận diện ngách nội dung của kênh từ từ khóa, tiêu đề và mô tả."""
        title_text = (channel_title or "").lower()
        desc_text = (channel_description or "").lower()
        kw_list = [str(k).lower().strip().lstrip("#") for k in (channel_keywords or []) if str(k).strip()]
        
        video_titles = " ".join([v.get("title", "").lower() for v in (videos or [])[:30]])
        video_descs = " ".join([(v.get("description", "") or "")[:200].lower() for v in (videos or [])[:30]])

        scores = {}
        for niche_key, niche_info in NICHE_PROFILES.items():
            if niche_key == "general":
                continue
            score = 0
            for kw in niche_info.get("keywords", []):
                kw_clean = kw.strip().lower()
                if not kw_clean:
                    continue
                # 1. Trùng trong tên kênh (Trọng số cực cao: 12đ)
                if kw_clean in title_text:
                    score += 12
                # 2. Trùng trong từ khóa / hashtag kênh (Trọng số cao: 8đ)
                if any(kw_clean in k or k in kw_clean for k in kw_list):
                    score += 8
                # 3. Trùng trong tiêu đề video (Trọng số: 4đ mỗi lần xuất hiện, tối đa 24đ)
                v_count = video_titles.count(kw_clean)
                if v_count > 0:
                    score += min(24, v_count * 4)
                # 4. Trùng trong mô tả kênh hoặc mô tả video (Trọng số: 2đ)
                if kw_clean in desc_text or kw_clean in video_descs:
                    score += 2
                    
            scores[niche_key] = score

        if not scores:
            return "general"

        best_niche = max(scores, key=scores.get)
        # Ngưỡng tin cậy: >= 5 điểm (chỉ cần trùng tên kênh, hashtag kênh hoặc 2 tiêu đề video)
        if scores.get(best_niche, 0) < 5:
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


