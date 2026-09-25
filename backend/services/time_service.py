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

# Hồ sơ 2 khung giờ đăng tối ưu theo 19 chủ đề / ngách chuẩn của hệ thống
NICHE_PROFILES = {
    "learn_english": {
        "name_vi": "🎓 Học Tiếng Anh (English Learning & Speaking)",
        "upload_1_start": 5.5,
        "upload_1_end": 7.0,
        "upload_1_label": "Khung chính: Sáng sớm trước giờ học/làm",
        "upload_2_start": 17.5,
        "upload_2_end": 19.0,
        "upload_2_label": "Khung phụ: Tối học bài sau giờ làm",
        "best_weekdays": ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5"],
        "behavior_insight": "Người học tập trung nghe và luyện phản xạ vào sáng sớm thức dậy hoặc tối sau giờ làm.",
        "keywords": [
            "học tiếng anh", "tiếng anh giao tiếp", "phát âm tiếng anh", "luyện nghe tiếng anh", "ngữ pháp tiếng anh",
            "learn english", "english speaking", "english conversation", "english lesson", "english listening", "ielts", "toeic",
            "영어 회화", "영어 공부", "기초 영어", "영어 발음", "英語学習", "英会話"
        ]
    },
    "spicy_18_drama": {
        "name_vi": "🔞 18+ & Tâm Sự Thầm Kín Đêm Muộn",
        "upload_1_start": 20.5,
        "upload_1_end": 22.0,
        "upload_1_label": "Khung chính: Đêm muộn giờ riêng tư",
        "upload_2_start": 22.5,
        "upload_2_end": 23.8,
        "upload_2_label": "Khung phụ: Nửa đêm cho cú đêm",
        "best_weekdays": ["Thứ 5", "Thứ 6", "Thứ 7", "Chủ Nhật"],
        "behavior_insight": "Khán giả nghe tâm sự thầm kín tập trung vào đêm muộn khi ở một mình hoặc trước khi ngủ.",
        "keywords": [
            "tâm sự thầm kín", "chuyện đêm muộn", "thầm kín", "tình một đêm", "18+", "chuyện phòng the", "tâm sự phòng the",
            "spicy relationship", "secret affair", "affair stories", "confessions late night", "19금", "19금 사연", "연애 썰", "夜の告白"
        ]
    },
    "father_inlaw_drama": {
        "name_vi": "🏡 Bố Chồng Nàng Dâu (Gia Đình Cay Đắng)",
        "upload_1_start": 10.5,
        "upload_1_end": 11.5,
        "upload_1_label": "Khung chính: Trưa nghỉ ngơi ăn cơm",
        "upload_2_start": 19.0,
        "upload_2_end": 20.3,
        "upload_2_label": "Khung phụ: Tối sau bữa cơm gia đình",
        "best_weekdays": ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Chủ Nhật"],
        "behavior_insight": "Nội dung gia đình cay đắng hóng biến mạnh nhất lúc nghỉ trưa và tối thư giãn.",
        "keywords": [
            "bố chồng nàng dâu", "bố chồng", "nàng dâu", "gia đình cay đắng", "tâm sự gia đình", "mâu thuẫn gia đình",
            "father in law", "daughter in law", "in-law drama", "toxic family", "family drama stories",
            "시아버지", "며느리", "시댁 갈등", "가족 갈등 썰", "義父", "嫁"
        ]
    },
    "mother_inlaw_drama": {
        "name_vi": "⚡ Mẹ Vợ Con Rể (Xung Đột & Trớ Trêu)",
        "upload_1_start": 10.5,
        "upload_1_end": 11.5,
        "upload_1_label": "Khung chính: Trưa ăn cơm hóng biến",
        "upload_2_start": 19.0,
        "upload_2_end": 20.3,
        "upload_2_label": "Khung phụ: Tối thư giãn gia đình",
        "best_weekdays": ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Chủ Nhật"],
        "behavior_insight": "Khán giả thích nghe chuyện xung đột mẹ vợ con rể / mẹ chồng vào giờ trưa và tối.",
        "keywords": [
            "mẹ vợ con rể", "mẹ vợ", "con rể", "mẹ chồng nàng dâu", "mẹ chồng", "xung đột gia đình",
            "mother in law", "son in law", "toxic mother in law", "in law conflict", "family conflict stories",
            "장모", "사위", "장모 사위", "시월드", "義母", "婿"
        ]
    },
    "infidelity_revenge": {
        "name_vi": "💔 Ngoại Tình & Bắt Gian Trả Thù (Revenge Drama)",
        "upload_1_start": 11.0,
        "upload_1_end": 12.5,
        "upload_1_label": "Khung chính: Trưa hóng drama bắt gian",
        "upload_2_start": 19.5,
        "upload_2_end": 21.0,
        "upload_2_label": "Khung phụ: Tối xem trả thù sướng mắt",
        "best_weekdays": ["Thứ 3", "Thứ 4", "Thứ 5", "Chủ Nhật"],
        "behavior_insight": "Drama ngoại tình và trả thù bắt gian thu hút người xem cao điểm lúc trưa và tối.",
        "keywords": [
            "ngoại tình", "bắt gian", "đánh ghen", "trả thù", "tiểu tam", "con giáp thứ 13", "drama bắt gian",
            "cheating spouse", "cheating partner", "cheating revenge", "caught cheating", "revenge drama",
            "불륜", "바람", "참교육", "사이다 썰", "막장", "浮気", "不倫", "修羅場"
        ]
    },
    "philosophy": {
        "name_vi": "📜 Triết Lý & Khắc Kỷ (Stoicism)",
        "upload_1_start": 5.0,
        "upload_1_end": 6.5,
        "upload_1_label": "Khung chính: Sáng sớm nạp năng lượng & suy ngẫm",
        "upload_2_start": 19.5,
        "upload_2_end": 21.0,
        "upload_2_label": "Khung phụ: Tối chiêm nghiệm, chữa lành trước khi ngủ",
        "best_weekdays": ["Chủ Nhật", "Thứ 2", "Thứ 5", "Thứ 6"],
        "behavior_insight": "Khán giả nghe danh ngôn, triết lý & khắc kỷ vào sáng sớm thức dậy hoặc tối muộn trước khi ngủ để chữa lành và tìm động lực.",
        "keywords": [
            "triết lý", "khắc kỷ", "stoic", "stoicism", "marcus aurelius", "triết học", "danh ngôn", "nhân sinh", "bài học cuộc sống", "châm ngôn", "đạo lý", "phát triển bản thân", "chữa lành", "sách nói",
            "philosophy", "life lessons", "wisdom quotes", "deep quotes", "stoic quotes", "mindset",
            "명언", "인생", "철학", "인생철학", "지혜", "인생 교훈", "깨우는 명언", "동기부여", "마인드셋", "성공명언", "좋은글",
            "哲学", "名言", "人生訓", "人生の教訓"
        ]
    },
    "buddhism": {
        "name_vi": "🪷 Phật Pháp & Chữa Lành",
        "upload_1_start": 5.0,
        "upload_1_end": 6.5,
        "upload_1_label": "Khung chính: Sáng sớm nghe kinh & tĩnh tâm",
        "upload_2_start": 20.0,
        "upload_2_end": 21.5,
        "upload_2_label": "Khung phụ: Tối nghe pháp, chữa lành tâm hồn",
        "best_weekdays": ["Thứ 7", "Chủ Nhật", "Thứ 2", "Thứ 6"],
        "behavior_insight": "Phật tử và người tìm kiếm sự an yên nghe giảng pháp vào sáng sớm hoặc tối trước khi ngủ.",
        "keywords": [
            "phật pháp", "lời phật dạy", "chữa lành", "thích chân quang", "thích minh niệm", "thiền định", "tâm an lạc", "giác ngộ", "đạo phật", "kinh phật",
            "buddhism", "buddha teachings", "mindfulness", "healing meditation", "dharma", "monk teaching",
            "불교", "설법", "명상", "힐링", "마음치유", "불교 설법", "仏教", "説法", "禅"
        ]
    },
    "elderly_wisdom": {
        "name_vi": "👴 Tâm Sự & Lời Khuyên Người Già",
        "upload_1_start": 5.3,
        "upload_1_end": 6.8,
        "upload_1_label": "Khung chính: Sáng sớm dậy sớm ngẫm sự đời",
        "upload_2_start": 18.5,
        "upload_2_end": 20.0,
        "upload_2_label": "Khung phụ: Đầu tối thư giãn nhẹ nhàng",
        "best_weekdays": ["Thứ 7", "Chủ Nhật", "Thứ 2"],
        "behavior_insight": "Người trung niên và cao tuổi thường dậy từ rất sớm và nghe tâm sự cuộc sống vào đầu ngày hoặc đầu tối.",
        "keywords": [
            "người già", "lời khuyên người già", "tâm sự tuổi già", "dưỡng già", "tuổi xế chiều", "tuổi trung niên", "lời dạy cổ nhân",
            "elderly wisdom", "senior life lessons", "aging gracefully", "grandpa advice", "old age wisdom",
            "노인의 지혜", "인생 교훈", "황혼", "노후", "어르신", "高齢者", "人生の教訓", "老後"
        ]
    },
    "reddit_stories": {
        "name_vi": "💬 Truyện Reddit & Confessions (AITA)",
        "upload_1_start": 11.5,
        "upload_1_end": 13.0,
        "upload_1_label": "Khung chính: Nghỉ trưa lướt đọc tâm sự",
        "upload_2_start": 19.0,
        "upload_2_end": 20.3,
        "upload_2_label": "Khung phụ: Tối nghe kể chuyện thư giãn",
        "best_weekdays": ["Thứ 5", "Thứ 6", "Thứ 7", "Chủ Nhật"],
        "behavior_insight": "Khán giả truyện Reddit thích nghe câu chuyện đời thực nhiều phần vào giờ nghỉ trưa và tối.",
        "keywords": [
            "truyện reddit", "tâm sự reddit", "reddit confessions", "reddit stories", "aita", "am i the asshole", "askreddit", "storytime", "tifu",
            "레딧 썰", "레딧 사연", "레딧", "스레 썰", "2ch", "スレ"
        ]
    },
    "drama_expose": {
        "name_vi": "🎭 Drama & Bóc Phốt (Exposé)",
        "upload_1_start": 11.5,
        "upload_1_end": 12.8,
        "upload_1_label": "Khung chính: Trưa hóng tin tức nóng",
        "upload_2_start": 18.5,
        "upload_2_end": 20.0,
        "upload_2_label": "Khung phụ: Tối bàn tán xôn xao mạng xã hội",
        "best_weekdays": ["Thứ 6", "Thứ 7", "Chủ Nhật", "Thứ 2"],
        "behavior_insight": "Drama bóc phốt lan truyền với tốc độ chóng mặt vào giờ tan tầm và cuối tuần.",
        "keywords": [
            "bóc phốt", "drama showbiz", "vạch trần", "scandal", "hóng biến", "drama bóc phốt",
            "the downfall of", "expose", "exposed", "controversy", "drama explained", "internet drama",
            "사건 폭로", "이슈", "논란", "폭로", "사건의 전말", "炎上", "暴露"
        ]
    },
    "true_crime": {
        "name_vi": "🕵️ Vụ Án Có Thật & Bí Ẩn",
        "upload_1_start": 18.0,
        "upload_1_end": 19.5,
        "upload_1_label": "Khung chính: Đầu tối sau giờ làm",
        "upload_2_start": 20.5,
        "upload_2_end": 22.0,
        "upload_2_label": "Khung phụ: Tối muộn thư giãn sâu",
        "best_weekdays": ["Thứ 5", "Thứ 6", "Thứ 7", "Chủ Nhật"],
        "behavior_insight": "Kỳ án và phim tài liệu điều tra đòi hỏi tập trung cao, xem nhiều vào tối cuối tuần.",
        "keywords": [
            "vụ án có thật", "kỳ án", "trinh thám", "hồ sơ vụ án", "điều tra phá án", "hồ sơ tội phạm",
            "true crime", "true crime documentary", "interrogation", "serial killer", "unsolved mystery", "cold case",
            "사건 파일", "미제 사건", "실화 범죄", "범죄 다큐", "未解決事件", "犯罪ドキュメンタリー", "殺人事件"
        ]
    },
    "horror_stories": {
        "name_vi": "👻 Kinh Dị & Truyện Đêm Muộn",
        "upload_1_start": 19.5,
        "upload_1_end": 21.0,
        "upload_1_label": "Khung chính: Đầu tối trước giờ ngủ",
        "upload_2_start": 21.5,
        "upload_2_end": 23.0,
        "upload_2_label": "Khung phụ: Nửa đêm cho cú đêm",
        "best_weekdays": ["Thứ 5", "Thứ 6", "Thứ 7", "Chủ Nhật"],
        "behavior_insight": "Khán giả truyện ma & kinh dị có thói quen nghe vào đêm khuya trước khi đi ngủ.",
        "keywords": [
            "truyện ma", "quái đàm", "kinh dị", "cõi âm", "chuyện ma", "tâm linh huyền bí", "nghe truyện ma",
            "scary horror stories", "creepypasta", "ghost story", "scary stories", "paranormal", "haunted",
            "무서운 이야기", "공포 괴담", "실화 괴담", "괴담", "귀신 이야기", "怖い話", "怪談", "ホラー"
        ]
    },
    "history_geopolitics": {
        "name_vi": "⚔️ Lịch Sử & Địa Chính Trị",
        "upload_1_start": 11.5,
        "upload_1_end": 12.8,
        "upload_1_label": "Khung chính: Nghỉ trưa theo dõi tư liệu",
        "upload_2_start": 19.0,
        "upload_2_end": 20.3,
        "upload_2_label": "Khung phụ: Tối xem tư liệu chuyên sâu",
        "best_weekdays": ["Thứ 3", "Thứ 4", "Thứ 5", "Thứ 7"],
        "behavior_insight": "Khán giả lịch sử và địa chính trị thường theo dõi tư liệu dài vào buổi tối các ngày trong tuần.",
        "keywords": [
            "lịch sử", "địa chính trị", "chiến tranh", "quân sự", "tư liệu lịch sử", "thế chiến", "lịch sử thế giới",
            "history documentary", "geopolitics", "warfare", "world war", "military history", "historical documentary",
            "역사 다큐멘터리", "전쟁", "지정학", "역사", "歴史", "地政学"
        ]
    },
    "space_science": {
        "name_vi": "🌌 Bí Ẩn Vũ Trụ & Khoa Học",
        "upload_1_start": 18.0,
        "upload_1_end": 19.3,
        "upload_1_label": "Khung chính: Tối giải trí khám phá",
        "upload_2_start": 20.5,
        "upload_2_end": 22.0,
        "upload_2_label": "Khung phụ: Đêm suy ngẫm về vũ trụ",
        "best_weekdays": ["Thứ 5", "Thứ 6", "Thứ 7", "Chủ Nhật"],
        "behavior_insight": "Khán giả yêu thích vũ trụ và khoa học xem nhiều vào buổi tối và đêm cuối tuần.",
        "keywords": [
            "bí ẩn vũ trụ", "vũ trụ", "khoa học", "thiên văn", "hố đen", "hệ mặt trời", "khám phá khoa học",
            "space science", "universe", "astronomy", "black hole", "cosmos", "space documentary",
            "우주 과학", "블랙홀", "우주 다큐", "우주 미스터리", "宇宙", "科学", "天文学"
        ]
    },
    "finance_money": {
        "name_vi": "💰 Tài Chính & Kiếm Tiền Online",
        "upload_1_start": 6.5,
        "upload_1_end": 7.5,
        "upload_1_label": "Khung chính: Sáng trước giờ mở phiên",
        "upload_2_start": 15.5,
        "upload_2_end": 16.5,
        "upload_2_label": "Khung phụ: Chiều trước khi đóng phiên",
        "best_weekdays": ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5"],
        "behavior_insight": "Khán giả tài chính theo sát lịch làm việc và phiên giao dịch từ Thứ 2 đến Thứ 5.",
        "keywords": [
            "tài chính", "kiếm tiền online", "mmo", "đầu tư", "chứng khoán", "tiền điện tử", "crypto", "làm giàu", "kinh doanh",
            "personal finance", "investing", "make money online", "passive income", "stock market", "crypto trading",
            "재테크", "투자", "부업", "주식", "가상화폐", "投資", "副業", "資産運用"
        ]
    },
    "tech_ai": {
        "name_vi": "🤖 Công Nghệ & Trí Tuệ Nhân Tạo (AI)",
        "upload_1_start": 11.5,
        "upload_1_end": 12.5,
        "upload_1_label": "Khung chính: Nghỉ trưa lướt tin công nghệ",
        "upload_2_start": 18.5,
        "upload_2_end": 20.0,
        "upload_2_label": "Khung phụ: Tối sau giờ làm việc",
        "best_weekdays": ["Thứ 3", "Thứ 4", "Thứ 5", "Thứ 7"],
        "behavior_insight": "Dân công nghệ thích theo dõi tin tức công nghệ và AI vào giờ nghỉ trưa và tối sau giờ làm.",
        "keywords": [
            "công nghệ", "trí tuệ nhân tạo", "chatgpt", "công nghệ mới", "review công nghệ", "thủ thuật ai", "mở hộp",
            "artificial intelligence", "ai tools", "tech review", "chatgpt tutorial", "future tech", "gadgets",
            "인공지능", "ai 도구", "테크", "스마트폰 리뷰", "人工知能", "aiツール", "最新技術"
        ]
    },
    "recap_stories": {
        "name_vi": "🎬 Tóm Tắt Phim & Truyện",
        "upload_1_start": 11.3,
        "upload_1_end": 12.5,
        "upload_1_label": "Khung chính: Trưa vừa ăn cơm vừa xem tóm tắt",
        "upload_2_start": 18.5,
        "upload_2_end": 20.0,
        "upload_2_label": "Khung phụ: Tối thư giãn xem phim ngắn gọn",
        "best_weekdays": ["Thứ 6", "Thứ 7", "Chủ Nhật"],
        "behavior_insight": "Khán giả tóm tắt phim xem bùng nổ vào giờ ăn trưa và tối cuối tuần.",
        "keywords": [
            "tóm tắt phim", "review phim", "giải thích phim", "tóm tắt truyện", "phim hay", "spoil phim",
            "movie recap", "film recap", "film summary", "movie explained", "ending explained",
            "영화 요약", "결말포함", "영화 리뷰", "映画 要約", "映画解説"
        ]
    },
    "gaming": {
        "name_vi": "🎮 Gaming & Esports",
        "upload_1_start": 14.0,
        "upload_1_end": 15.5,
        "upload_1_label": "Khung chính: Chiều đón tan học",
        "upload_2_start": 18.5,
        "upload_2_end": 20.0,
        "upload_2_label": "Khung phụ: Tối cày game & Cuối tuần",
        "best_weekdays": ["Thứ 6", "Thứ 7", "Chủ Nhật"],
        "behavior_insight": "Khán giả game xem nhiều từ chiều tan học và bùng nổ tối cuối tuần.",
        "keywords": [
            "gaming", "gameplay", "chơi game", "streamer", "esports", "highlight game", "game walkthrough", "game bắn súng",
            "gaming highlights", "game streamer", "minecraft survival", "roblox",
            "게임 플레이", "게임 하이라이트", "실황", "ゲーム実況", "プレイ動画"
        ]
    },
    "travel_vlog": {
        "name_vi": "✈️ Du Lịch, Ẩm Thực & Vlog Đời Sống",
        "upload_1_start": 11.5,
        "upload_1_end": 13.0,
        "upload_1_label": "Khung chính: Trưa nghỉ ngơi xem ẩm thực & du lịch",
        "upload_2_start": 18.5,
        "upload_2_end": 20.3,
        "upload_2_label": "Khung phụ: Tối thư giãn giải trí sau giờ làm",
        "best_weekdays": ["Thứ 5", "Thứ 6", "Thứ 7", "Chủ Nhật"],
        "behavior_insight": "Khán giả xem vlog du lịch, ẩm thực và trải nghiệm cuộc sống nhiều nhất vào giờ ăn trưa và buổi tối cuối tuần để giải trí và lên kế hoạch đi chơi.",
        "keywords": [
            "vlog", "du lịch", "ẩm thực", "ăn uống", "trải nghiệm", "khám phá", "solo trip",
            "du lịch việt nam", "du lịch tự túc", "review du lịch", "review ẩm thực", "món ăn",
            "đặc sản", "quán ăn", "food tour", "street food", "ẩm thực đường phố", "vlog cuộc sống",
            "cuộc sống", "đi chơi", "phượt", "camping", "cắm trại", "khoa pug", "khoai lang thang",
            "sang vlog", "hành trình", "chuyến đi", "check in", "khách sạn", "resort", "nhà hàng",
            "đất nước", "quốc gia", "travel vlog", "travel", "solo travel", "food review",
            "walking tour", "travel guide", "daily vlog", "lifestyle vlog", "budget travel",
            "trip", "traveling", "vacation", "eating show", "mukbang",
            "여행", "브이로그", "여행 브이로그", "맛집", "먹방", "旅行", "vlog", "グルメ"
        ]
    },
    "entertainment": {
        "name_vi": "🎉 Giải Trí & Hài Hước",
        "upload_1_start": 16.5,
        "upload_1_end": 18.5,
        "upload_1_label": "Khung chính: Chiều tối tan ca giải trí",
        "upload_2_start": 10.5,
        "upload_2_end": 12.0,
        "upload_2_label": "Khung phụ: Trưa & Cuối tuần xả stress",
        "best_weekdays": ["Thứ 6", "Thứ 7", "Chủ Nhật"],
        "behavior_insight": "Khán giả giải trí xem nhiều nhất vào các buổi tối sau giờ tan làm và trưa cuối tuần.",
        "keywords": [
            "hài hước", "giải trí", "tiểu phẩm hài", "troll vui", "thử thách", "viral clip",
            "funny moments", "comedy", "entertainment viral", "prank", "challenge",
            "예능", "웃긴 영상", "레전드", "バラエティ", "面白い"
        ]
    }
}

# Alias mappings for backward compatibility
NICHE_PROFILES["general"] = NICHE_PROFILES["entertainment"]
NICHE_PROFILES["horror"] = NICHE_PROFILES["horror_stories"]
NICHE_PROFILES["education"] = NICHE_PROFILES["learn_english"]
NICHE_PROFILES["drama_story"] = NICHE_PROFILES["infidelity_revenge"]
NICHE_PROFILES["finance_biz"] = NICHE_PROFILES["finance_money"]
NICHE_PROFILES["quotes_philosophy"] = NICHE_PROFILES["philosophy"]
NICHE_PROFILES["vlog"] = NICHE_PROFILES["travel_vlog"]
NICHE_PROFILES["travel"] = NICHE_PROFILES["travel_vlog"]

VN_WORD_BOUNDARY = r'(?<![\wàáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ])'
VN_WORD_BOUNDARY_END = r'(?![\wàáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ])'

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

        def count_kw_in_text(text: str, kw: str) -> int:
            if not text or not kw:
                return 0
            pattern = VN_WORD_BOUNDARY + re.escape(kw) + VN_WORD_BOUNDARY_END
            return len(re.findall(pattern, text, re.IGNORECASE))

        def phrase_matches_tag(kw_clean: str, tag: str) -> bool:
            kw_clean = kw_clean.strip().lower()
            tag = tag.strip().lower()
            if not kw_clean or not tag:
                return False
            if kw_clean == tag:
                return True
            kw_words = kw_clean.split()
            tag_words = tag.split()
            # Only match phrase containment if the sub-phrase is at least 2 words
            if len(tag_words) >= 2 and re.search(VN_WORD_BOUNDARY + re.escape(tag) + VN_WORD_BOUNDARY_END, kw_clean, re.IGNORECASE):
                return True
            if len(kw_words) >= 2 and re.search(VN_WORD_BOUNDARY + re.escape(kw_clean) + VN_WORD_BOUNDARY_END, tag, re.IGNORECASE):
                return True
            return False

        scores = {}
        for niche_key, niche_info in NICHE_PROFILES.items():
            if niche_key in ["general", "horror", "education", "drama_story", "finance_biz", "quotes_philosophy", "vlog", "travel"]:
                continue
            score = 0
            for kw in niche_info.get("keywords", []):
                kw_clean = kw.strip().lower()
                if not kw_clean:
                    continue

                # 1. Trùng trong tên kênh (Trọng số cực cao: 20đ mỗi lần xuất hiện)
                c_title = count_kw_in_text(title_text, kw_clean)
                if c_title > 0:
                    score += 20 * c_title

                # 2. Trùng trong từ khóa / hashtag kênh (Trọng số cao: 10đ)
                if any(phrase_matches_tag(kw_clean, k) for k in kw_list):
                    score += 10

                # 3. Trùng trong tiêu đề video (Trọng số: 5đ mỗi lần xuất hiện, tối đa 35đ)
                c_vids = count_kw_in_text(video_titles, kw_clean)
                if c_vids > 0:
                    score += min(35, c_vids * 5)

                # 4. Trùng trong mô tả kênh hoặc mô tả video (Trọng số: 6đ)
                c_desc = count_kw_in_text(desc_text, kw_clean)
                if c_desc > 0:
                    score += 8
                elif count_kw_in_text(video_descs, kw_clean) > 0:
                    score += 4
                    
            scores[niche_key] = score

        if not scores:
            return "entertainment"

        best_niche = max(scores, key=scores.get)
        # Ngưỡng tin cậy: >= 8 điểm (ít nhất 1 từ khóa tên kênh/mô tả hoặc 2 lần trong tiêu đề video)
        if scores.get(best_niche, 0) < 8:
            return "entertainment"
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
        niche_prof = NICHE_PROFILES.get(niche_key, NICHE_PROFILES["entertainment"])

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

        # Tính điểm tin cậy thống kê cho từng ngày:
        # Score = avg_views * sample_weight * niche_multiplier
        # Tránh trường hợp 1 video tình cờ view cao lấn át ngày có nhiều video đều đặn view cao
        recommended_days = niche_prof.get("best_weekdays", ["Thứ 6", "Thứ 7", "Chủ Nhật"])

        for d in weekdays_distribution:
            cnt = d["video_count"]
            avg_w = d["avg_views"]
            if cnt == 0:
                conf_weight = 0.0
            elif cnt == 1:
                conf_weight = 0.55
            elif cnt == 2:
                conf_weight = 0.80
            elif cnt == 3:
                conf_weight = 1.0
            else:
                conf_weight = min(1.25, 1.0 + (cnt - 3) * 0.05)

            is_niche_fav = d["day_name"] in recommended_days
            niche_multiplier = 1.15 if is_niche_fav else 1.0
            d["composite_score"] = avg_w * conf_weight * niche_multiplier

        sorted_days = sorted(weekdays_distribution, key=lambda x: x.get("composite_score", 0), reverse=True)
        historical_best_days = [d["day_name"] for d in sorted_days if d["video_count"] > 0 and d.get("composite_score", 0) > 0]
        best_day_single = historical_best_days[0] if historical_best_days else (recommended_days[0] if recommended_days else "Thứ 6")

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


