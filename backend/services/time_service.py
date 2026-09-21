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
        "weekend_label": "Cuối tuần Mỹ (Thứ 7 & CN)",
    },
    "GB": {
        "name": "Vương Quốc Anh (UK)",
        "utc_offset": 0,  # London (chậm hơn VN 7 tiếng)
        "tz_name": "GMT / BST (London, UTC+0)",
        "weekend_label": "Cuối tuần London (Thứ 7 & CN)",
    },
    "JP": {
        "name": "Nhật Bản",
        "utc_offset": 9,  # Tokyo (sớm hơn VN 2 tiếng)
        "tz_name": "JST (Tokyo, UTC+9)",
        "weekend_label": "Cuối tuần Nhật Bản (Thứ 7 & CN)",
    },
    "KR": {
        "name": "Hàn Quốc",
        "utc_offset": 9,  # Seoul (sớm hơn VN 2 tiếng)
        "tz_name": "KST (Seoul, UTC+9)",
        "weekend_label": "Cuối tuần Hàn Quốc (Thứ 7 & CN)",
    },
    "DE": {
        "name": "Đức & Trung Âu",
        "utc_offset": 1,  # Berlin (chậm hơn VN 6 tiếng)
        "tz_name": "CET (Berlin, UTC+1)",
        "weekend_label": "Cuối tuần Đức (Thứ 7 & CN)",
    },
    "IN": {
        "name": "Ấn Độ",
        "utc_offset": 5.5,  # New Delhi (chậm hơn VN 1.5 tiếng)
        "tz_name": "IST (New Delhi, UTC+5:30)",
        "weekend_label": "Cuối tuần Ấn Độ (Thứ 7 & CN)",
    },
    "BR": {
        "name": "Brazil",
        "utc_offset": -3,  # Sao Paulo (chậm hơn VN 10 tiếng)
        "tz_name": "BRT (Sao Paulo, UTC-3)",
        "weekend_label": "Cuối tuần Brazil (Thứ 7 & CN)",
    },
    "FR": {
        "name": "Pháp (France)",
        "utc_offset": 1,  # Paris (chậm hơn VN 6 tiếng)
        "tz_name": "CET / CEST (Paris, UTC+1)",
        "weekend_label": "Cuối tuần Pháp (Thứ 7 & CN)",
    },
    "IT": {
        "name": "Ý (Italy)",
        "utc_offset": 1,  # Rome (chậm hơn VN 6 tiếng)
        "tz_name": "CET / CEST (Rome, UTC+1)",
        "weekend_label": "Cuối tuần Ý (Thứ 7 & CN)",
    },
    "VN": {
        "name": "Việt Nam",
        "utc_offset": 7,  # Giờ ICT (UTC+7)
        "tz_name": "ICT (Hà Nội, TP.HCM, UTC+7)",
        "weekend_label": "Cuối tuần Việt Nam (Thứ 7 & CN)",
    }
}

# Hồ sơ hành vi xem video chuyên sâu theo từng chủ đề / ngách (Niche Viewing Behavior)
NICHE_PROFILES = {
    "horror": {
        "name_vi": "Kinh dị & Truyện ma / Quái đàm",
        "keywords": [
            "ghost", "horror", "scary", "paranormal", "haunted", "spooky", "creepy", "creepypasta", "supernatural",
            "dark", "nightmare", "demon", "cemetery", "witch", "monster",
            "ma", "quỷ", "kinh dị", "truyện ma", "rùng rợn", "tâm linh", "huyền bí", "kỳ bí", "cõi âm", "bóng đè",
            "khám phá tâm linh", "người chết", "oan hồn",
            "공포", "괴담", "귀신", "무서운", "호러", "미스터리", "심령", "흉가",
            "怖い", "ホラー", "怪談", "心霊", "都市伝説", "心霊スポット"
        ],
        "local_prime_start": 21.5,
        "local_prime_end": 24.5,
        "local_prime_label": "21:30 - 00:30 (Đêm muộn khi đi ngủ)",
        "local_upload_start": 19.5,
        "local_upload_end": 21.0,
        "local_upload_label": "19:30 - 21:00 (Đầu tối trước giờ ngủ)",
        "best_weekdays": ["Thứ 5", "Thứ 6", "Thứ 7", "Chủ Nhật"],
        "behavior_insight": "Khán giả ngách Kinh dị / Truyện ma có thói quen nghe và xem vào đêm muộn trong không gian yên tĩnh khi chuẩn bị đi ngủ. Không nên đăng ban ngày vì CTR và thời lượng xem thấp."
    },
    "education": {
        "name_vi": "Học tập / Ngoại ngữ / Giáo dục",
        "keywords": [
            "english", "learn", "study", "lesson", "vocabulary", "grammar", "pronunciation", "speaking",
            "listening", "tutorial", "course", "education", "productivity", "toeic", "ielts", "lecture",
            "học", "tiếng anh", "ngoại ngữ", "từ vựng", "ngữ pháp", "bài học", "hướng dẫn", "giáo dục",
            "kỹ năng", "luyện nghe", "giao tiếp", "phát âm", "tự học", "khoa học", "tri thức",
            "영어", "공부", "회화", "단어", "문법", "토익", "교육", "학습", "강의",
            "英語", "学習", "勉強", "英会話", "リスニング", "文法", "講座", "授業"
        ],
        "local_prime_start": 7.0,
        "local_prime_end": 8.5,
        "local_prime_label": "07:00 - 08:30 (Sáng sớm trước giờ học/làm)",
        "local_upload_start": 5.0,
        "local_upload_end": 6.5,
        "local_upload_label": "05:00 - 06:30 (Rạng sáng chuẩn bị ngày mới)",
        "secondary_prime_start": 19.5,
        "secondary_prime_end": 21.5,
        "secondary_prime_label": "19:30 - 21:30 (Tối học bài sau bữa cơm)",
        "secondary_upload_start": 17.5,
        "secondary_upload_end": 19.0,
        "secondary_upload_label": "17:30 - 19:00 (Cuối buổi chiều đón ca tối)",
        "best_weekdays": ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Chủ Nhật"],
        "behavior_insight": "Học viên tập trung học nhiều nhất vào sáng sớm trước khi đi làm/đi học (7h-8h30) và tối ôn bài (19h30-21h30). Cuối tuần Thứ 7 lượt xem học thuật thường giảm do khán giả đi chơi xả hơi."
    },
    "drama_story": {
        "name_vi": "Drama / Bắt gian / Ngoại tình / Gia đình",
        "keywords": [
            "drama", "cheating", "revenge", "affair", "divorce", "mother in law", "confession", "story",
            "betrayal", "mistress", "conflict",
            "ngoại tình", "bắt gian", "tiểu tam", "mẹ chồng", "nàng dâu", "tâm sự", "hôn nhân", "gia đình", "đánh ghen",
            "bi kịch", "ly hôn", "phản bội", "người thứ ba",
            "바람", "불륜", "막장", "시월드", "사이다", "결혼", "이혼", "썰",
            "浮気", "不倫", "修羅場", "義母", "泥沼", "スカッとする話", "嫁姑"
        ],
        "local_prime_start": 12.0,
        "local_prime_end": 13.5,
        "local_prime_label": "12:00 - 13:30 (Nghỉ trưa văn phòng)",
        "local_upload_start": 10.5,
        "local_upload_end": 11.5,
        "local_upload_label": "10:30 - 11:30 (Đón đầu trước bữa trưa)",
        "secondary_prime_start": 20.0,
        "secondary_prime_end": 22.5,
        "secondary_prime_label": "20:00 - 22:30 (Tối thư giãn gia đình)",
        "secondary_upload_start": 18.0,
        "secondary_upload_end": 19.5,
        "secondary_upload_label": "18:00 - 19:30 (Đón đầu ca tối)",
        "best_weekdays": ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Chủ Nhật"],
        "behavior_insight": "Khán giả drama hóng biến mạnh nhất vào giờ nghỉ trưa ăn cơm (12h-13h30) và lúc chuẩn bị ngủ (20h-22h30). Đăng đón trước bữa trưa hoặc bữa tối tạo hiệu ứng lan truyền bàn tán cao nhất."
    },
    "true_crime": {
        "name_vi": "Vụ án có thật / Kỳ án / Trinh thám",
        "keywords": [
            "true crime", "crime", "mystery", "murder", "unsolved", "killer", "investigation", "case", "detective",
            "serial killer", "mysterious", "autopsy",
            "vụ án", "kỳ án", "trinh thám", "sát nhân", "bí ẩn", "phá án", "tội phạm", "hồ sơ vụ án", "tử thi",
            "범죄", "살인", "사건", "미제", "그것이알고싶다", "수사", "형사",
            "未解決事件", "事件", "殺人", "犯罪", "サイコパス", "真相"
        ],
        "local_prime_start": 20.5,
        "local_prime_end": 23.5,
        "local_prime_label": "20:30 - 23:30 (Tối muộn tập trung sâu)",
        "local_upload_start": 18.0,
        "local_upload_end": 19.5,
        "local_upload_label": "18:00 - 19:30 (Đầu tối sau giờ làm)",
        "best_weekdays": ["Thứ 5", "Thứ 6", "Thứ 7", "Chủ Nhật"],
        "behavior_insight": "Kỳ án và phim tài liệu điều tra đòi hỏi thời lượng tập trung cao. Khán giả xem nhiều nhất sau bữa tối từ 20h30 đến 23h30, đặc biệt các đêm cuối tuần."
    },
    "finance_biz": {
        "name_vi": "Tài chính / Đầu tư / MMO / Kinh doanh",
        "keywords": [
            "finance", "stock", "crypto", "bitcoin", "investment", "money", "trading", "mmo", "passive income",
            "business", "economy", "forex", "gold", "market",
            "tài chính", "chứng khoán", "tiền ảo", "đầu tư", "kiếm tiền", "kinh doanh", "làm giàu", "tiết kiệm",
            "bất động sản", "ngoại hối", "giá vàng", "lạm phát",
            "주식", "코인", "재테크", "투자", "비트코인", "부동산", "수익",
            "株", "投資", "暗号資産", "仮想通貨", "副業", "資産形成", "不労所得"
        ],
        "local_prime_start": 7.5,
        "local_prime_end": 9.0,
        "local_prime_label": "07:30 - 09:00 (Trước giờ mở phiên giao dịch)",
        "local_upload_start": 6.0,
        "local_upload_end": 7.5,
        "local_upload_label": "06:00 - 07:30 (Đầu giờ sáng)",
        "secondary_prime_start": 16.5,
        "secondary_prime_end": 18.5,
        "secondary_prime_label": "16:30 - 18:30 (Sau khi đóng phiên thị trường)",
        "secondary_upload_start": 15.0,
        "secondary_upload_end": 16.0,
        "secondary_upload_label": "15:00 - 16:00 (Trước khi đóng phiên)",
        "best_weekdays": ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5"],
        "behavior_insight": "Người xem tài chính hoạt động theo nhịp làm việc và phiên giao dịch. Thứ 2 đến Thứ 5 là đỉnh cao; cuối tuần (Thứ 7, CN) view thường tụt do thị trường đóng cửa và nhà đầu tư nghỉ ngơi."
    },
    "gaming": {
        "name_vi": "Gaming / Trò chơi / Esports",
        "keywords": [
            "game", "gameplay", "gaming", "playthrough", "walkthrough", "mod", "minecraft", "roblox", "gta",
            "genshin", "pubg", "valorant", "esports", "speedrun",
            "chơi game", "liên quân", "free fire", "tốc chiến", "streamer", "phá đảo", "game thủ",
            "게임", "플레이", "롤", "마인크래프트", "배그", "게임방송",
            "ゲーム", "実況", "プレイ動画", "マイクラ", "攻略"
        ],
        "local_prime_start": 16.0,
        "local_prime_end": 18.0,
        "local_prime_label": "16:00 - 18:00 (Chiều tan học/tan làm)",
        "local_upload_start": 14.0,
        "local_upload_end": 15.5,
        "local_upload_label": "14:00 - 15:30 (Đầu giờ chiều)",
        "secondary_prime_start": 20.0,
        "secondary_prime_end": 23.5,
        "secondary_prime_label": "20:00 - 23:30 (Tối giải trí cày game)",
        "secondary_upload_start": 18.5,
        "secondary_upload_end": 19.5,
        "secondary_upload_label": "18:30 - 19:30 (Đầu giờ tối)",
        "best_weekdays": ["Thứ 6", "Thứ 7", "Chủ Nhật"],
        "behavior_insight": "Khán giả game phần lớn là giới trẻ và học sinh/sinh viên. Lượt xem bùng nổ mạnh nhất từ chiều Thứ 6 xuyên suốt cả ngày Thứ 7 và Chủ Nhật."
    },
    "kids": {
        "name_vi": "Trẻ em / Hoạt hình / Ca nhạc thiếu nhi",
        "keywords": [
            "kids", "children", "nursery", "cartoon", "animation", "toys", "rhymes", "baby", "lullaby", "toddlers",
            "trẻ em", "thiếu nhi", "hoạt hình", "đồ chơi", "búp bê", "ca nhạc thiếu nhi", "bài hát ru",
            "어린이", "키즈", "만화", "동요", "장난감", "유아",
            "キッズ", "子供", "アニメ", "おもちゃ", "童謡"
        ],
        "local_prime_start": 7.0,
        "local_prime_end": 8.5,
        "local_prime_label": "07:00 - 08:30 (Sáng trước khi đi học)",
        "local_upload_start": 5.5,
        "local_upload_end": 6.5,
        "local_upload_label": "05:30 - 06:30 (Sáng sớm)",
        "secondary_prime_start": 17.0,
        "secondary_prime_end": 19.0,
        "secondary_prime_label": "17:00 - 19:00 (Chiều tắm rửa cơm nước)",
        "secondary_upload_start": 15.5,
        "secondary_upload_end": 16.5,
        "secondary_upload_label": "15:30 - 16:30 (Giữa buổi chiều)",
        "best_weekdays": ["Thứ 7", "Chủ Nhật", "Thứ 6"],
        "behavior_insight": "Phụ huynh mở YouTube cho con lúc sáng trước khi đi học, chiều tối cơm nước và đặc biệt là sáng Thứ 7 & Chủ Nhật khi bố mẹ nghỉ ngơi."
    },
    "general": {
        "name_vi": "Giải trí đại chúng / Vlog / Đời sống",
        "keywords": [],
        "local_prime_start": 18.5,
        "local_prime_end": 22.0,
        "local_prime_label": "18:30 - 22:00 (Tối sinh hoạt gia đình)",
        "local_upload_start": 16.0,
        "local_upload_end": 17.5,
        "local_upload_label": "16:00 - 17:30 (Chiều chuẩn bị tan sở)",
        "best_weekdays": ["Thứ 6", "Thứ 7", "Chủ Nhật"],
        "behavior_insight": "Khung giờ vàng đại chúng là chiều tối sau giờ làm việc (18h30 - 22h00 local). Nên đăng trước 1.5 - 2 tiếng để thuật toán xử lý HD và đón đỉnh xem."
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
        corpus = [channel_title, channel_description]
        if channel_keywords:
            corpus.extend(channel_keywords)

        for v in (videos or [])[:30]:
            corpus.append(v.get("title", ""))
            desc = v.get("description", "")
            if desc:
                corpus.append(desc[:200])
            for tag in v.get("tags", []) or []:
                corpus.append(tag)

        full_text = " ".join(corpus).lower()

        scores = {}
        for niche_key, niche_info in NICHE_PROFILES.items():
            if niche_key == "general":
                continue
            score = 0
            for kw in niche_info["keywords"]:
                kw_clean = kw.strip().lower()
                if not kw_clean:
                    continue
                # Kiểm tra từ đơn hay cụm từ
                if len(kw_clean) <= 3:
                    # Với từ ngắn, dùng regex word boundary để tránh false positive
                    matches = re.findall(rf"\b{re.escape(kw_clean)}\b", full_text)
                    score += len(matches) * 2
                else:
                    if kw_clean in full_text:
                        score += 3
            scores[niche_key] = score

        best_niche = max(scores, key=scores.get) if scores else "general"
        if scores.get(best_niche, 0) < 3:
            return "general"
        return best_niche

    def analyze_upload_times(
        self,
        videos: List[Dict[str, Any]],
        target_geo: str = "US",
        channel_keywords: Optional[List[str]] = None,
        channel_title: str = "",
        channel_description: str = ""
    ) -> Dict[str, Any]:
        """Phân tích giờ vàng 2 tầng: Chủ đề ngách + Múi giờ Quốc gia quy đổi sang giờ Việt Nam (UTC+7)."""
        geo = target_geo.upper().strip() if target_geo else "US"
        country_prof = COUNTRY_TIMEZONE_PROFILES.get(geo, COUNTRY_TIMEZONE_PROFILES["US"])
        utc_offset = country_prof["utc_offset"]

        # 1. Nhận diện ngách nội dung của kênh
        niche_key = self.detect_channel_niche(
            videos=videos,
            channel_keywords=channel_keywords,
            channel_title=channel_title,
            channel_description=channel_description
        )
        niche_prof = NICHE_PROFILES.get(niche_key, NICHE_PROFILES["general"])

        # 2. Quy đổi giờ địa phương theo ngách sang Giờ Việt Nam (UTC+7)
        best_upload_vn = convert_range_to_vn(niche_prof["local_upload_start"], niche_prof["local_upload_end"], utc_offset)
        peak_view_vn = convert_range_to_vn(niche_prof["local_prime_start"], niche_prof["local_prime_end"], utc_offset)

        # 3. Phân tích lịch sử thực tế của kênh (Channel Empirical History)
        hour_views_vn = defaultdict(list)
        hour_counts_vn = defaultdict(int)
        days_names = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ Nhật"]
        weekday_views = defaultdict(list)
        weekday_counts = defaultdict(int)

        channel_published_history = []
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
        historical_best_days = [d["day_name"] for d in sorted_days if d["video_count"] > 0]
        
        # Kết hợp ngày khuyến nghị của ngách và lịch sử kênh
        recommended_days = niche_prof.get("best_weekdays", ["Thứ 6", "Thứ 7", "Chủ Nhật"])
        best_day_single = historical_best_days[0] if historical_best_days else recommended_days[0]

        # 4. Xây dựng lời khuyên chiến lược chi tiết theo Chủ đề & Quốc gia
        strategy_tip = (
            f"🎯 Chủ đề: {niche_prof['name_vi']} | Thị trường: {country_prof['name']} ({country_prof['tz_name']}). "
            f"{niche_prof['behavior_insight']} "
            f"Quy đổi sang giờ Việt Nam: Bạn nên bấm đăng lúc {best_upload_vn} (tương ứng {niche_prof['local_upload_label']} giờ địa phương) "
            f"để YouTube kịp xử lý HD và đẩy đề xuất đúng đỉnh xem {peak_view_vn} ({niche_prof['local_prime_label']})."
        )

        # 5. Top khuyến nghị hành động cụ thể
        top_recommendations = [
            {
                "time_slot_vn": f"Khung {best_upload_vn} (Giờ VN)",
                "target_local_time": niche_prof["local_upload_label"],
                "target_audience": f"Khán giả {country_prof['name']} xem ngách {niche_prof['name_vi']}",
                "recommended_for": f"Đăng lúc {best_upload_vn} đón đỉnh view {peak_view_vn} ({niche_prof['local_prime_label']})"
            }
        ]

        # Nếu có ca phụ (ví dụ học tập hoặc drama có 2 ca trong ngày)
        if "secondary_upload_start" in niche_prof:
            sec_upload_vn = convert_range_to_vn(niche_prof["secondary_upload_start"], niche_prof["secondary_upload_end"], utc_offset)
            sec_prime_vn = convert_range_to_vn(niche_prof["secondary_prime_start"], niche_prof["secondary_prime_end"], utc_offset)
            top_recommendations.append({
                "time_slot_vn": f"Khung ca phụ: {sec_upload_vn} (Giờ VN)",
                "target_local_time": niche_prof.get("secondary_upload_label", ""),
                "target_audience": f"Ca xem thứ 2 của khán giả {country_prof['name']}",
                "recommended_for": f"Đăng lúc {sec_upload_vn} đón đỉnh xem {sec_prime_vn} ({niche_prof.get('secondary_prime_label', '')})"
            })

        # Thêm minh chứng từ lịch sử kênh nếu có dữ liệu view vượt trội
        if top_historical_hours:
            best_h = top_historical_hours[0]
            top_recommendations.append({
                "time_slot_vn": f"Khung {best_h['label']} (Giờ VN)",
                "target_local_time": "Minh chứng thực tế kênh",
                "target_audience": "Thời điểm kênh của bạn từng đạt view cao nhất trong quá khứ",
                "recommended_for": f"Kênh đã từng đạt trung bình {best_h['avg_views']:,} views khi xuất bản lúc {best_h['label']}"
            })

        return {
            "target_country_code": geo,
            "target_country_name": country_prof["name"],
            "target_timezone_name": country_prof["tz_name"],
            "detected_niche_code": niche_key,
            "detected_niche_name": niche_prof["name_vi"],
            "niche_behavior_insight": niche_prof["behavior_insight"],
            "strategy_tip": strategy_tip,
            "best_upload_time_vn": best_upload_vn,
            "peak_view_time_vn": peak_view_vn,
            "suggested_weekday_vn": best_upload_vn,
            "best_day_of_week": best_day_single,
            "best_weekdays": recommended_days,
            "best_upload_desc": f"Đăng trước 1.5 - 2h để đón đỉnh xem {niche_prof['local_prime_label']} tại {country_prof['name']}.",
            "peak_view_desc": f"Đỉnh khán giả {country_prof['name']} tập trung xem nhiều nhất ({niche_prof['local_prime_label']}).",
            "hours_distribution": hours_distribution,
            "weekdays_distribution": weekdays_distribution,
            "top_recommendations": top_recommendations
        }

