import logging
import re
import requests
from typing import List, Dict, Any, Optional
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import yt_dlp

logger = logging.getLogger(__name__)

GEO_TO_LANG_MAP = {
    "KR": "ko",
    "JP": "ja",
    "VN": "vi",
    "US": "en", "GB": "en", "CA": "en", "AU": "en",
    "FR": "fr",
    "DE": "de",
    "ES": "es", "MX": "es", "AR": "es", "CO": "es", "CL": "es", "PE": "es",
    "BR": "pt", "PT": "pt",
    "RU": "ru",
    "TH": "th",
    "CN": "zh", "TW": "zh", "HK": "zh",
    "IT": "it",
    "IN": "hi",
    "ID": "id"
}

NICHE_SEARCH_TEMPLATES = {
    "infidelity_revenge": {
        "ko": ['사이다 썰', '바람 불륜 사이다 복수 썰', '사이다사연 참교육', '톡썰 사연 모음'],
        "ja": ['修羅場 スカッとする話', '浮気 復讐 スカッと', '修羅場 不倫 ざまぁ'],
        "es": ['historias de traicion drama familiar', 'relatos de infidelidad y venganza', 'historias de infidelidad y engaño'],
        "vi": ['tâm sự ngoại tình trả thù', 'drama bắt gian ngoại tình', 'đánh ghen bắt gian chuyện có thật'],
        "en": ['cheating revenge drama stories', 'infidelity betrayal stories reddit', 'family betrayal drama']
    },
    "father_inlaw_drama": {
        "ko": ['시어머니 며느리 갈등 사이다 썰', '시댁 갈등 사이다 사연', '막장 시댁 참교육 썰'],
        "ja": ['義母 嫁 姑 確執 スカッと', '義実家 ざまぁ スカッとする話'],
        "es": ['drama suegra y nuera historias', 'conflictos familiares historias', 'historias de drama familiar'],
        "vi": ['mẹ chồng nàng dâu drama', 'bố chồng nàng dâu tâm sự', 'xung đột mẹ chồng nàng dâu'],
        "en": ['mother in law drama stories', 'toxic mother in law reddit', 'entitled in laws stories']
    },
    "mother_inlaw_drama": {
        "ko": ['시어머니 며느리 갈등 사이다 썰', '시어머니 참교육 썰', '사이다 톡썰 모음'],
        "ja": ['姑 嫁いびり スカッと', '義母 撃退 ざまぁ スカッとする話'],
        "es": ['drama suegra y nuera historias', 'conflictos familiares historias', 'historias de suegras'],
        "vi": ['mẹ chồng nàng dâu drama', 'mẹ vợ con rể drama', 'xung đột gia đình'],
        "en": ['mother in law drama stories', 'toxic mother in law reddit', 'in laws drama']
    },
    "reddit_stories": {
        "ko": ['레딧 썰', '네이트판 레전드 썰', '사연 라디오', '커뮤니티 레전드 썰'],
        "ja": ['2ch スカッと 伝説', '2ちゃんねる スレ 朗読'],
        "es": ['reddit historias espanol', 'historias de reddit venganza', 'relatos reddit espanol'],
        "vi": ['truyện reddit vietsub', 'tâm sự reddit kể chuyện', 'drama reddit có thật'],
        "en": ['reddit stories podcast', 'aita revenge drama', 'best reddit confessions']
    },
    "drama_expose": {
        "ko": ['사건사고 이슈 폭로', '연예 이슈 정리', '논란 이슈 총정리'],
        "ja": ['炎上 事件 暴露 まとめ', '芸能界 闇 暴露'],
        "es": ['polemicas y drama youtube', 'historias de drama y secretos', 'exponiendo la verdad'],
        "vi": ['bóc phốt drama mới nhất', 'drama vạch trần sự thật', 'tin tức drama showbiz'],
        "en": ['drama expose commentary', 'youtube drama explained', 'truth exposed documentary']
    },
    "true_crime": {
        "ko": ['그것이 알고싶다 미제사건', '실화 범죄 미스터리', '한국 미제사건 실화'],
        "ja": ['未解決事件 迷宮入り', '実際の事件 凶悪事件 ドキュメンタリー'],
        "es": ['casos de misterio de la vida real', 'crimen real documental', 'casos criminales sin resolver'],
        "vi": ['hồ sơ vụ án có thật', 'kỳ án trinh thám phá án', 'tội phạm có thật bí ẩn'],
        "en": ['true crime documentary stories', 'real crime cases solved', 'mystery criminal investigation']
    },
    "horror_stories": {
        "ko": ['무서운 이야기 실화', '괴담 라디오', '공포 실화 썰'],
        "ja": ['本当にあった怖い話 朗読', '怪談 恐怖 実話'],
        "es": ['relatos de terror reales', 'historias de miedo reales', 'cuentos de terror paranormal'],
        "vi": ['truyện ma có thật đêm khuya', 'truyện ma kinh dị tâm linh', 'tâm linh kỳ bí'],
        "en": ['real horror stories true', 'scary stories narrated', 'creepy paranormal true stories']
    },
    "travel_vlog": {
        "ko": ['여행 브이로그', '세계여행 브이로그', '먹방 여행 브이로그'],
        "ja": ['旅行 vlog ひとり旅', '海外旅行 ドキュメンタリー'],
        "es": ['vlog de viajes y comida', 'viajes por el mundo vlog', 'explorando lugares comida'],
        "vi": ['vlog du lịch trải nghiệm', 'ẩm thực du lịch bốn phương', 'khám phá daily vlog'],
        "en": ['travel vlog documentary', 'street food and travel', 'travel lifestyle vlog']
    },
    "gaming": {
        "ko": ['게임 하이라이트', '게임 실황 플레이', '종합게임 플레이'],
        "ja": ['ゲーム実況 プレイ', 'ゲーム ハイライト 名場面'],
        "es": ['gameplay espanol', 'mejores momentos gaming', 'gameplay en espanol'],
        "vi": ['gameplay highlight tiếng việt', 'trải nghiệm game kịch tính', 'stream game hài hước'],
        "en": ['gaming highlights gameplay', 'game walkthrough review', 'best gaming moments']
    },
    "tech_ai": {
        "ko": ['it 테크 리뷰', 'ai 인공지능 활용법', '전자기기 언박싱'],
        "ja": ['ガジェット レビュー 最新', 'ai 活用法 ツール 最新情報'],
        "es": ['tecnologia inteligencia artificial', 'review tecnologia gadgets', 'tutoriales de inteligencia artificial'],
        "vi": ['đánh giá công nghệ trí tuệ nhân tạo', 'review đồ công nghệ mới', 'hướng dẫn công cụ ai'],
        "en": ['tech review artificial intelligence', 'latest tech gadgets review', 'ai tools tutorial']
    },
    "recap_stories": {
        "ko": ['영화 결말포함', '영화 리뷰 요약', '드라마 몰아보기 요약'],
        "ja": ['映画 解説 結末まで', '映画 あらすじ 要約'],
        "es": ['resumen de peliculas y series', 'resumen de pelicula drama', 'explicacion de peliculas'],
        "vi": ['review phim tóm tắt hay', 'tóm tắt phim điện ảnh', 'spoil phim nhanh'],
        "en": ['movie recap full story', 'film recap explained', 'movie summary storytelling']
    },
    "learn_english": {
        "ko": ['영어회화 꿀팁', '원어민 영어 표현', '기초 영어 패턴'],
        "ja": ['英会話 リスニング 練習', 'ネイティブ 英語 フレーズ'],
        "es": ['aprender ingles facil y rapido', 'curso de ingles conversacion', 'vocabulario en ingles'],
        "vi": ['học tiếng anh giao tiếp cơ bản', 'luyện nghe tiếng anh mỗi ngày', 'kỹ năng học tiếng anh'],
        "en": ['learn english conversation', 'daily english speaking practice', 'english listening practice']
    },
    "history_geopolitics": {
        "ko": ['세계사 역사 다큐', '전쟁사 다큐멘터리', '국제정세 지정학'],
        "ja": ['世界史 ドキュメンタリー', '戦争の歴史 地政学'],
        "es": ['historia mundial documental', 'geopolitica y guerras', 'documentales de historia'],
        "vi": ['lịch sử thế giới phóng sự', 'địa chính trị quốc tế', 'tư liệu chiến tranh lịch sử'],
        "en": ['world history documentary', 'geopolitics explained', 'historical warfare documentary']
    },
    "finance_money": {
        "ko": ['재테크 재정 경제', '주식 부동산 투자', '부자되는 습관'],
        "ja": ['資産運用 投資 初心者', 'お金の増やし方 副業'],
        "es": ['finanzas personales e inversiones', 'como ganar dinero negocios', 'educacion financiera'],
        "vi": ['tài chính cá nhân đầu tư', 'kinh doanh kiếm tiền thông minh', 'đầu tư chứng khoán bất động sản'],
        "en": ['personal finance investing', 'how to make money business', 'wealth building passive income']
    },
    "philosophy": {
        "ko": ['인생 명언 교훈', '인생 철학 동기부여', '마음공부 지혜'],
        "ja": ['人生の教訓 名言 哲学', '心を整える 智慧'],
        "es": ['lecciones de vida reflexion estoicismo', 'filosofia y motivacion', 'reflexiones para la vida'],
        "vi": ['bài học cuộc sống danh ngôn', 'triết lý sống chữa lành', 'động lực sống phát triển bản thân'],
        "en": ['stoicism life lessons philosophy', 'life wisdom motivation', 'philosophical life advice']
    },
    "christianity_bible": {
        "ko": ['말씀 기도 묵상', '성경 오디오 말씀', '기독교 설교 은혜'],
        "ja": ['聖書の言葉 祈り 礼拝', 'キリスト教 説教 賛美歌'],
        "es": ['estudio biblico reflexion oracion', 'predicas cristianas vida', 'palabra de dios diaria'],
        "vi": ['kinh thánh lời chúa mỗi ngày', 'bài giảng cơ đốc giáo đức tin', 'cầu nguyện tĩnh tâm lời chúa'],
        "en": ['bible study audio prayer', 'christian daily devotional', 'scripture reading sermon']
    },
    "buddhism": {
        "ko": ['불교 명상 법문', '마음 다스리는 법문', '부처님 말씀 힐링'],
        "ja": ['仏教 法話 瞑想 心の平安', 'ブッダの教え 説法'],
        "es": ['budismo ensenanzas meditacion', 'paz interior reflexion budista', 'filosofia budista meditacion'],
        "vi": ['lời phật dạy chữa lành tĩnh tâm', 'thuyết pháp phật giáo an lạc', 'thiền định lời phật dạy'],
        "en": ['buddhist wisdom teachings', 'healing peaceful meditation', 'inner peace buddhism philosophy']
    },
    "elderly_wisdom": {
        "ko": ['노후 인생 명언', '노년 인생 교훈', '은퇴 후 삶의 지혜'],
        "ja": ['老後の生き方 人生の知恵', 'シニア 人生の教訓'],
        "es": ['sabiduria de vida para la vejez', 'consejos para adultos mayores', 'lecciones para envejecer con paz'],
        "vi": ['tâm sự tuổi già bài học cuộc đời', 'lời khuyên tuổi trung niên già', 'dưỡng già an yên cuộc sống'],
        "en": ['aging wisdom life lessons', 'advice for growing older', 'elderly life reflections']
    },
    "astrology_horoscope": {
        "ko": ['오늘의 운세 띠별운세', '타로 카드 리딩', '신년 사주 운세'],
        "ja": ['占い タロット リーディング', '星座占い 運勢'],
        "es": ['horoscopo y tarot predicciones', 'astrologia signos del zodiaco', 'tarot interactivo'],
        "vi": ['tử vi 12 con giáp vận mệnh', 'xem bói phong thủy vận hạn', 'tarot thông điệp tương lai'],
        "en": ['daily horoscope tarot reading', 'astrology zodiac predictions', 'zodiac signs fortune']
    },
    "entertainment": {
        "ko": ['예능 레전드 모음', '웃긴 영상 챌린지', '재미있는 영상 모음'],
        "ja": ['おもしろ動画 爆笑', 'バラエティ 名場面'],
        "es": ['retos y entretenimiento viral', 'videos divertidos virales', 'desafios y comedia viral'],
        "vi": ['thử thách sinh tồn hài hước', 'giải trí triệu view viral', 'video hài hước giải trí'],
        "en": ['viral entertainment challenge', 'funny stunts challenge', 'trending entertainment comedy']
    }
}

def detect_channel_language(text: str, target_geo: Optional[str] = None, channel_country: Optional[str] = None) -> str:
    """Xác định ngôn ngữ chính xác dựa trên ký tự đặc trưng, từ vựng cốt lõi và quốc gia kênh/thị trường.
    
    Thứ tự ưu tiên:
    1. Nhận dạng bằng ký tự đặc trưng CJK / Thái / Cyrillic / Việt (độ chính xác cao nhất)
    2. Chấm điểm từ vựng có trọng số (vô hiệu hoá các từ Đức/Pháp quá ngắn dễ nhầm)
    3. Fallback theo quốc gia kênh / thị trường mục tiêu
    """
    t = text.lower()
    
    # 1. Tiếng Hàn Quốc (Hangul: [가-힣ᄀ-ᇿ])
    if len(re.findall(r'[가-힣ᄀ-ᇿ]', text)) >= 2:
        return 'ko'
        
    # 2. Tiếng Nhật (Kana: [ぁ-んァ-ヶ])
    if len(re.findall(r'[ぁ-んァ-ヶ]', text)) >= 2:
        return 'ja'
        
    # 3. Tiếng Trung (Hanzi [\u4e00-\u9fff])
    if len(re.findall(r'[\u4e00-\u9fff]', text)) >= 3:
        return 'zh'

    # 4. Tiếng Thái
    if len(re.findall(r'[\u0e00-\u0e7f]', text)) >= 3:
        return 'th'

    # 5. Tiếng Nga / Cyrillic
    if len(re.findall(r'[а-яА-ЯёЁ]', text)) >= 3:
        return 'ru'

    # 6. Ký tự dấu thuần Việt (độ chính xác cao, dấu không xuất hiện trong ngôn ngữ Latin khác)
    vn_chars = r'[đăâêôơưảãạẳẵặẩẫậẻẽẹểễệỉĩịỏõọổỗộởỡợủũụửữựỳỷỹỵằầềồờừắấếốớứ]'
    vn_words = r'\b(và|của|trong|cho|với|không|người|chuyện|tâm sự|ngoại tình|trả thù|bắt gian|đánh ghen|gia đình|hài hước|ẩm thực|du lịch|cuộc sống|phim|tóm tắt|vụ án)\b'
    vn_score = len(re.findall(vn_chars, t)) * 2 + len(re.findall(vn_words, t)) * 5
    # Nếu đủ ký tự Việt đặc trưng, trả về ngay để tránh nhầm vs Tây Ban Nha
    if vn_score >= 6:
        return 'vi'

    # 7. Tiếng Tây Ban Nha đặc trưng (ưu tiên dấu ñ ¿ ¡ và từ dài độc đáo)
    es_chars = r'[ñ¿¡]'
    # Chỉ dùng các từ dài >= 4 ký tự hoặc từ độc quyền để tránh nhầm vs de/fr/en
    es_words = r'\b(historias|relatos|esposa|marido|familia|vida|traicion|traición|venganza|desamor|cuentos|infiel|infidelidad|pelicula|resumen|suegra|nuera|engaño|mujer|hombre|espanol|español)\b'
    es_score = len(re.findall(es_chars, t)) * 4 + len(re.findall(es_words, t)) * 4

    # 8. Tiếng Pháp đặc trưng (ưu tiên ký tự œ æ ç và từ độc quyền)
    fr_chars = r'[çœæ]'
    # Chỉ dùng từ dài >= 4 ký tự hoặc từ độc quyền
    fr_words = r'\b(dans|pour|avec|cette|film|histoire|femme|homme|mariage|trahison|vengeance|famille|amour|bonjour|française|français)\b'
    fr_score = len(re.findall(fr_chars, t)) * 4 + len(re.findall(fr_words, t)) * 4

    # 9. Tiếng Bồ Đào Nha đặc trưng (ưu tiên từ dài độc quyền)
    pt_words = r'\b(você|voce|não|nao|história|historia|traição|traicao|vingança|vinganca|infidelidade|esposa|marido|casamento|família|familia|português)\b'
    pt_score = len(re.findall(pt_words, t)) * 4

    # 10. Tiếng Đức đặc trưng
    # LƯU Ý: Các từ Đức ngắn như "und", "der", "die", "das", "ein", "mit" dễ xuất hiện
    # trong tên kênh tiếng Anh. Chỉ chấm điểm cao cho từ DÀI và ĐỘC QUYỀN của tiếng Đức.
    de_chars = r'[äöüÄÖÜß]'
    de_words = r'\b(nicht|geschichten|rache|affäre|betrogen|ehefrau|ehemann|familie|deutsch|deutschen|scheidung|untreue|rache)\b'
    de_score = len(re.findall(de_chars, t)) * 4 + len(re.findall(de_words, t)) * 4

    scores = {'vi': vn_score, 'es': es_score, 'fr': fr_score, 'pt': pt_score, 'de': de_score}
    best_lang, best_score = max(scores.items(), key=lambda x: x[1])
    # Yêu cầu ngưỡng điểm cao hơn (>= 4) để tránh false positive
    if best_score >= 4:
        return best_lang

    # 11. Dựa vào target_geo hoặc channel_country khi text ít ký tự đặc trưng
    eff_geo = (target_geo or channel_country or "").upper()
    if eff_geo in GEO_TO_LANG_MAP:
        return GEO_TO_LANG_MAP[eff_geo]

    return 'en'


class CompetitorService:
    def __init__(self):
        self.ydl_opts = {
            'quiet': True,
            'skip_download': True,
            'no_warnings': True,
            'extract_flat': True,
            'socket_timeout': 15,
        }
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        self._last_queries = []
        self._last_niche = ""

    def _scrape_channel_avatar(self, channel_url: str) -> str:
        if not channel_url or 'results?search_query=' in channel_url:
            return ""
        try:
            r = requests.get(channel_url, headers=self.headers, timeout=5)
            matches = re.findall(r'(https://yt3\.(?:googleusercontent|ggpht)\.com/[a-zA-Z0-9_\-=]+)', r.text)
            valid = [m for m in matches if len(m) > 40 and not m.endswith('/ytc')]
            if valid:
                return valid[0]
            if matches:
                return matches[0]
        except Exception:
            pass
        return ""

    def is_short_or_shorts_channel(self, title: str = "", uploader: str = "", duration_sec: int = 0, url: str = "") -> bool:
        """Kiểm tra nghiêm ngặt xem video hoặc kênh có phải Shorts không."""
        t = (title or "").lower()
        ch = (uploader or "").lower()
        u = (url or "").lower()

        if "/shorts/" in u:
            return True
        ch_words = set(re.findall(r'\b\w+\b', ch))
        if "shorts" in ch or "쇼츠" in ch or "shorts" in ch_words:
            return True
        if any(tag in t for tag in ["#shorts", "#short", "#쇼츠", "#shortvideo", "#youtubeshorts"]):
            return True
        if 0 < duration_sec < 180:
            return True
        if duration_sec == 0:
            t_words = set(re.findall(r'\b\w+\b', t))
            if "shorts" in t_words or "쇼츠" in t:
                return True
        return False

    def is_music_or_topic_channel(self, title: str = "", uploader: str = "", description: str = "") -> bool:
        """Kiểm tra kênh hoặc video có phải MV / Nhạc / Topic channel không."""
        t = (title or "").lower()
        ch = (uploader or "").lower()
        
        if ch.endswith("- topic") or " - topic" in ch:
            return True
        if any(w in ch for w in ["vevo", "records", "discos", "official music"]):
            return True
        
        music_markers = [
            "official music video", "(official video)", "[official video]", 
            "(video oficial)", "[video oficial]", "videoclip oficial",
            "(audio oficial)", "[audio oficial]", "(audio)",
            "(letra)", "[letra]", "(lyrics)", "[lyrics]", "ft.", "feat."
        ]
        if any(m in t for m in music_markers):
            return True
        return False

    def is_tv_or_broadcast_network(self, title: str = "", uploader: str = "", description: str = "") -> bool:
        """Kiểm tra nghiêm ngặt xem kênh có phải là Đài truyền hình, Đài phát thanh, Hãng tin tức hoặc Tập đoàn truyền thông không.
        Mục tiêu: Đảm bảo tab đối thủ chỉ hiển thị các nhà sáng tạo nội dung độc lập (indie creators / drama story channels),
        loại bỏ hoàn toàn các đài quốc gia và kênh truyền hình chính thống như SBS, KBS, MBC, tvN, JTBC, VTV, BBC...
        """
        ch = (uploader or "").strip().lower()
        # Cũng kiểm tra title vì một số kênh có tên tiếng Anh nhưng title chứa tên đài
        t = (title or "").lower()
        desc = (description or "").lower()

        # 1. Các đài truyền hình & hệ thống kênh truyền hình Hàn Quốc
        # Lưu ý: dùng regex linh hoạt bắt cả "SBSnews", "sbs뉴스", "KBS2" v.v.
        kr_tv_patterns = [
            r'sbs\s*(plus|뉴스|news|스포츠|sports|funE|fun\s*e|드라마|drama|연예|joy|\d)',
            r'스플스',  # SBS Plus tiếng Hàn
            r'\bsbs\b',  # Tên kênh chỉ là "SBS"
            r'kbs\s*(\d|뉴스|news|drama|joy|world|스포츠|sports|n\b)',
            r'\bkbs\b',
            r'mbc\s*(\d|뉴스|news|drama|every1|스포츠|sports)',
            r'\bmbc\b',
            r'\btvn\b', r'tvn\s*(drama|story|show|스타일)',
            r'\bjtbc\b', r'jtbc\s*(drama|voyage|스튜디오)',
            r'\bmbn\b', r'\bytn\b', r'\bebs\b',
            r'채널\s*a', r'channel\s*a',
            r'tv\s*조선', r'tv\s*chosun',
            r'연합뉴스', r'엠비씨', r'케이비에스', r'에스비에스', r'제이티비씨', r'티비엔',
        ]
        for pat in kr_tv_patterns:
            if re.search(pat, ch) or re.search(pat, t):
                return True

        # 2. Các đài truyền hình, cơ quan báo chí & thông tấn Việt Nam
        vn_tv_patterns = [
            r'\bvtv\d*\b', r'\bhtv\d*\b', r'\bthvl\d*\b', r'\bvtc\d*\b', r'\bvov\b',
            r'truyền hình', r'báo thanh niên', r'báo tuổi trẻ', r'báo người lao động',
            r'vnexpress', r'báo dân trí', r'tiền phong', r'vtc now', r'vtv giải trí', r'thvl phim',
            r'truyenhinh'
        ]
        for pat in vn_tv_patterns:
            if re.search(pat, ch) or re.search(pat, t):
                return True

        # 3. Các đài truyền hình, hãng tin tức & tập đoàn giải trí toàn cầu (Mỹ, Anh...)
        global_tv_patterns = [
            r'\bbbc\b', r'\bcnn\b', r'\bmsnbc\b', r'\bcnbc\b',
            r'\babc\s*news\b', r'\bfox\s*news\b', r'\bcbs\s*news\b', r'\bnbc\s*news\b',
            r'\bap\s*news\b', r'\breuters\b', r'\bbloomberg\b',
            r'\bnew york times\b', r'\bwashington post\b', r'\bwall street journal\b',
            r'\bnetflix\b', r'\bhbo\b', r'\bwarner bros\b', r'\bparamount\b', r'\bdisney\+\b',
            r'\bdiscovery channel\b', r'\bnational geographic\b', r'\bespn\b'
        ]
        for pat in global_tv_patterns:
            if re.search(pat, ch) or re.search(pat, t):
                return True

        # 4. Các đài truyền hình Nhật Bản
        jp_tv_patterns = [
            r'\bnhk\b', r'\btbs\s*(tv|テレビ|\b)',
            r'フジテレビ', r'fuji\s*tv', r'テレビ朝日', r'tv\s*asahi',
            r'テレビ東京', r'tv\s*tokyo', r'日本テレビ', r'\bntv\b'
        ]
        for pat in jp_tv_patterns:
            if re.search(pat, ch) or re.search(pat, t):
                return True

        # 5. Phát hiện bổ sung qua description: kênh đài lớn thường khai báo "official channel of" hoặc "방송"
        if desc:
            if re.search(r'official (channel|page|account) of\s+(sbs|kbs|mbc|tvn|jtbc|mbn|ytn|nhk|bbc|cnn)', desc):
                return True
            if re.search(r'(방송국|공식\s*채널|공영\s*방송)', desc):
                return True

        return False

    def _build_search_queries(
        self,
        current_channel_name: str,
        top_keywords: List[Dict[str, Any]],
        channel_tags: Optional[List[str]] = None,
        channel_description: Optional[str] = None,
        video_titles: Optional[List[str]] = None,
        target_geo: Optional[str] = None,
        channel_country: Optional[str] = None,
        niche: Optional[str] = None,
        custom_query: Optional[str] = None
    ) -> List[str]:
        """Tạo danh sách các truy vấn ngách đắt giá nhất, đại diện cho toàn bộ thể loại kênh và chuẩn ngôn ngữ."""
        if custom_query and custom_query.strip():
            return [custom_query.strip()]

        queries = []
        all_text = f"{current_channel_name} {' '.join(channel_tags or [])} {channel_description or ''} {' '.join(video_titles or [])}".lower()
        lang = detect_channel_language(all_text, target_geo=target_geo, channel_country=channel_country)

        # 1. Khai thác mẫu truy vấn chuyên biệt theo ngách và ngôn ngữ
        if niche and niche in NICHE_SEARCH_TEMPLATES:
            n_templates = NICHE_SEARCH_TEMPLATES[niche]
            queries.extend(n_templates.get(lang, n_templates.get("en", [])))

        # 2. Khai thác Channel Tags & Top Keywords chất lượng có cùng hệ ngôn ngữ
        def is_tag_matching_lang(tg: str) -> bool:
            if lang == 'ko':
                return bool(re.search(r'[가-힣]', tg))
            elif lang == 'ja':
                return bool(re.search(r'[ぁ-んァ-ヶ]', tg))
            elif lang == 'zh':
                return bool(re.search(r'[\u4e00-\u9fff]', tg))
            elif lang == 'vi':
                return bool(re.search(r'[àáảãạăắằẳẵặâấầẩẫậèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵđ]', tg.lower()))
            return True

        if channel_tags:
            for tag in channel_tags:
                clean_tag = str(tag).strip().strip('"').strip("'")
                words = clean_tag.split()
                if 1 <= len(words) <= 4 and is_tag_matching_lang(clean_tag) and clean_tag.lower() not in [q.lower() for q in queries]:
                    queries.append(clean_tag)

        for kw in (top_keywords or [])[:5]:
            val = kw.get('keyword') if isinstance(kw, dict) else str(kw)
            val = (val or '').strip()
            words = val.split()
            if 1 <= len(words) <= 4 and is_tag_matching_lang(val) and val.lower() not in [q.lower() for q in queries]:
                queries.append(val)

        if not queries:
            queries = [current_channel_name]

        return queries[:4]

    def find_similar_channels(
        self,
        current_channel_name: str,
        current_channel_url: str,
        top_keywords: List[Dict[str, Any]],
        channel_tags: Optional[List[str]] = None,
        channel_description: Optional[str] = None,
        video_titles: Optional[List[str]] = None,
        target_geo: Optional[str] = None,
        channel_country: Optional[str] = None,
        niche: Optional[str] = None,
        custom_query: Optional[str] = None,
        limit: int = 6,
        api_key: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Tìm kiếm các kênh đối thủ UY TÍN, ĐANG HOẠT ĐỘNG MẠNH trong cùng ngách:
        - Quét cả video viral hàng đầu và kênh trực tiếp để tìm đúng những creator đang dẫn đầu ngách.
        - Khớp đúng 100% ngôn ngữ và chủ đề của kênh đang phân tích theo quốc gia mục tiêu.
        - Lọc bỏ hoàn toàn kênh mới 0 sub, kênh rác, kênh Shorts và kênh MV/Nhạc.
        """
        queries = self._build_search_queries(
            current_channel_name=current_channel_name,
            top_keywords=top_keywords,
            channel_tags=channel_tags,
            channel_description=channel_description,
            video_titles=video_titles,
            target_geo=target_geo,
            channel_country=channel_country,
            niche=niche,
            custom_query=custom_query
        )
        self._last_queries = queries
        self._last_niche = niche or ""
        logger.info(f"Finding established competitors for '{current_channel_name}' [Geo: {target_geo}] with queries: {queries}")

        all_target_text = f"{current_channel_name} {' '.join(channel_tags or [])} {channel_description or ''} {' '.join(video_titles or [])}".lower()
        target_lang = detect_channel_language(all_target_text, target_geo=target_geo, channel_country=channel_country)
        is_music_target = any(w in all_target_text for w in ['music', 'música', 'singer', 'ca sĩ', 'bài hát', 'nhạc'])

        candidates_map: Dict[str, Dict[str, Any]] = {}
        candidate_ids: List[str] = []  # Dùng để kiểm tra trùng lặp nhanh

        # Chuẩn bị tham số khu vực cho YouTube Search API
        region_param = f"&regionCode={target_geo.upper()}" if target_geo and target_geo.upper() not in ["GLOBAL", "ALL"] else ""
        lang_param = f"&relevanceLanguage={target_lang}" if target_lang else ""

        # =========================================================================
        # Chiến lược 1: Tìm kiếm đối thủ thực tế qua YouTube Data API v3
        # Quét video thịnh hành nhất trong ngách để lấy creator thực sự + quét kênh
        # =========================================================================
        if api_key and api_key.strip():
            try:
                for q in queries:
                    # 1.1 Quét video hàng đầu trong ngách để tìm kênh đứng sau các video viral đó
                    v_search_url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&type=video&q={requests.utils.quote(q)}{region_param}{lang_param}&order=relevance&maxResults=12&key={api_key.strip()}"
                    v_res = requests.get(v_search_url, timeout=7).json()
                    for it in v_res.get('items', []):
                        snip = it.get('snippet', {})
                        c_id = snip.get('channelId')
                        c_name = snip.get('channelTitle', '')
                        v_title = snip.get('title', '')

                        if not c_id or not c_name or c_id in candidate_ids:
                            continue

                        # Bỏ qua chính kênh hiện tại
                        if current_channel_name and (current_channel_name.lower() in c_name.lower() or c_name.lower() in current_channel_name.lower()):
                            continue
                        if current_channel_url and c_id in current_channel_url:
                            continue

                        if self.is_short_or_shorts_channel(title=v_title, uploader=c_name):
                            continue
                        if not is_music_target and self.is_music_or_topic_channel(title=v_title, uploader=c_name):
                            continue
                        if self.is_tv_or_broadcast_network(uploader=c_name, title=v_title):
                            continue

                        candidate_ids.append(c_id)
                        candidates_map[c_id] = {
                            'channel_name': c_name,
                            'title': c_name,
                            'name': c_name,
                            'channel_id': c_id,
                            'channel_url': f"https://www.youtube.com/channel/{c_id}",
                            'url': f"https://www.youtube.com/channel/{c_id}",
                            'avatar_url': '',
                            'avatar': '',
                            'thumbnail': '',
                            'description': '',
                            'subscriber_count': 0,
                            'video_count': 0,
                            'total_views': 0,
                            'avg_views': 0,
                            'avg_views_sample': 0,
                            'sample_matched_videos': 1,
                            'top_video_title': v_title,
                            'top_video_views': 0,
                            'is_verified': False
                        }

                    # 1.2 Quét trực tiếp type=channel để bổ sung kênh mang từ khóa ngách
                    c_search_url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&type=channel&q={requests.utils.quote(q)}{region_param}{lang_param}&maxResults=4&key={api_key.strip()}"
                    c_res = requests.get(c_search_url, timeout=6).json()
                    for it in c_res.get('items', []):
                        snip = it.get('snippet', {})
                        c_id = snip.get('channelId')
                        c_name = snip.get('channelTitle', '')
                        c_desc = snip.get('description', '')

                        if not c_id or not c_name or c_id in candidate_ids:
                            continue

                        if current_channel_name and (current_channel_name.lower() in c_name.lower() or c_name.lower() in current_channel_name.lower()):
                            continue
                        if current_channel_url and c_id in current_channel_url:
                            continue

                        if self.is_short_or_shorts_channel(uploader=c_name):
                            continue
                        if not is_music_target and self.is_music_or_topic_channel(uploader=c_name, description=c_desc):
                            continue
                        if self.is_tv_or_broadcast_network(uploader=c_name, description=c_desc):
                            continue

                        thumb = (snip.get('thumbnails', {}).get('high') or snip.get('thumbnails', {}).get('medium') or snip.get('thumbnails', {}).get('default', {})).get('url', '')

                        candidate_ids.append(c_id)
                        candidates_map[c_id] = {
                            'channel_name': c_name,
                            'title': c_name,
                            'name': c_name,
                            'channel_id': c_id,
                            'channel_url': f"https://www.youtube.com/channel/{c_id}",
                            'url': f"https://www.youtube.com/channel/{c_id}",
                            'avatar_url': thumb,
                            'avatar': thumb,
                            'thumbnail': thumb,
                            'description': c_desc,
                            'subscriber_count': 0,
                            'video_count': 0,
                            'total_views': 0,
                            'avg_views': 0,
                            'avg_views_sample': 0,
                            'sample_matched_videos': 1,
                            'top_video_title': '',
                            'top_video_views': 0,
                            'is_verified': False
                        }

                # 1.3 Lấy thông số chi tiết (Subscribers, Views, Videos, Avatar) cho tất cả ứng viên
                if candidate_ids:
                    chunk = candidate_ids[:45]
                    detail_url = f"https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics&id={','.join(chunk)}&key={api_key.strip()}"
                    d_res = requests.get(detail_url, timeout=8).json()
                    
                    for d_it in d_res.get('items', []):
                        d_id = d_it.get('id')
                        st = d_it.get('statistics', {})
                        sn = d_it.get('snippet', {})
                        if d_id in candidates_map:
                            subs = int(st.get('subscriberCount') or 0)
                            v_cnt = int(st.get('videoCount') or 0)
                            tot_v = int(st.get('viewCount') or 0)
                            avg_v = int(tot_v / max(v_cnt, 1)) if tot_v > 0 else 0
                            
                            candidates_map[d_id]['subscriber_count'] = subs
                            candidates_map[d_id]['video_count'] = v_cnt
                            candidates_map[d_id]['total_views'] = tot_v
                            candidates_map[d_id]['avg_views'] = avg_v
                            candidates_map[d_id]['avg_views_sample'] = avg_v
                            candidates_map[d_id]['is_verified'] = subs >= 100000
                            candidates_map[d_id]['description'] = sn.get('description', '') or candidates_map[d_id]['description']
                            candidates_map[d_id]['country'] = sn.get('country', '')
                            
                            thumbs = sn.get('thumbnails', {})
                            if thumbs:
                                av = (thumbs.get('high') or thumbs.get('medium') or thumbs.get('default', {})).get('url', '')
                                if av:
                                    candidates_map[d_id]['avatar_url'] = av
                                    candidates_map[d_id]['avatar'] = av
                                    candidates_map[d_id]['thumbnail'] = av

            except Exception as api_err:
                logger.warning(f"Lỗi khi tìm kênh qua YouTube API: {api_err}")

        # Lọc nghiêm ngặt: KÊNH ĐỐI THỦ THỰC SỰ (Sub >= 1.000 hoặc Tổng view >= 20.000, ít nhất 3 video, không phải đài truyền hình)
        established_candidates = []
        for c in candidates_map.values():
            subs = c.get('subscriber_count', 0)
            vids = c.get('video_count', 0)
            tot_v = c.get('total_views', 0)
            c_name = c.get('channel_name', '')
            c_desc = c.get('description', '')

            if self.is_tv_or_broadcast_network(uploader=c_name, description=c_desc):
                continue

            if (subs >= 1000 or tot_v >= 20000) and vids >= 3:
                established_candidates.append(c)

        # Chấm điểm độ tương đồng ngách & ngôn ngữ để đưa đúng đối thủ thực sự lên đầu
        def _score_candidate(cand: Dict[str, Any]) -> int:
            text = (cand['channel_name'] + ' ' + cand.get('description', '') + ' ' + cand.get('top_video_title', '')).lower()
            cand_country = cand.get('country', '')
            score = 0
            cand_lang = detect_channel_language(text, target_geo=cand_country, channel_country=cand_country)

            # Khớp ngôn ngữ của kênh phân tích
            if target_lang == 'ko':
                if not re.search(r'[가-힣]', text):
                    return -999  # Loại bỏ hoàn toàn kênh ngoại lai khi đang phân tích kênh Hàn Quốc
                score += 80
            elif target_lang == 'ja':
                if not re.search(r'[ぁ-んァ-ヶ]', text):
                    return -999
                score += 80
            elif target_lang == 'zh':
                if not re.search(r'[\u4e00-\u9fff]', text):
                    return -999
                score += 80
            elif target_lang == 'vi':
                if re.search(r'[가-힣ぁ-んァ-ヶ\u0e00-\u0e7f]', text):
                    return -999
                score += 60 if cand_lang == 'vi' else -50
            else:
                if cand_lang == target_lang:
                    score += 60
                else:
                    score -= 40

            if target_geo and cand_country and cand_country.upper() == target_geo.upper():
                score += 30

            # Khớp từ khóa chủ đề ngách
            for q in queries:
                q_words = [w for w in q.lower().split() if len(w) > 1]
                overlap = sum(1 for w in q_words if w in text)
                score += overlap * 10

            # Ưu tiên kênh đối thủ cùng hạng cân (5.000 - 800.000 subs)
            subs = cand.get('subscriber_count', 0)
            if 5000 <= subs <= 500000:
                score += 35
            elif 500000 < subs <= 1500000:
                score += 25
            elif subs > 0:
                score += 10

            # Có video tiêu biểu viral
            if cand.get('top_video_title'):
                score += 20

            # Lượt xem trung bình
            avg_v = cand.get('avg_views', 0)
            score += min(20, avg_v // 5000)
            return score

        # Lọc bỏ các kênh điểm âm do sai ngôn ngữ
        established_candidates = [c for c in established_candidates if _score_candidate(c) > 0]
        established_candidates.sort(key=_score_candidate, reverse=True)
        final_candidates = established_candidates[:limit]

        # Bổ sung video tiêu biểu cho các kênh được chọn nếu chưa có
        if api_key and api_key.strip() and final_candidates:
            def _fetch_channel_top_video(cand: Dict[str, Any]):
                if cand.get('top_video_title'):
                    return
                c_id = cand['channel_id']
                uploads_id = 'UU' + c_id[2:]
                try:
                    pl_url = f"https://www.googleapis.com/youtube/v3/playlistItems?part=snippet&playlistId={uploads_id}&maxResults=1&key={api_key.strip()}"
                    p_data = requests.get(pl_url, timeout=5).json()
                    pl_items = p_data.get('items', [])
                    if pl_items:
                        cand['top_video_title'] = pl_items[0].get('snippet', {}).get('title', '')
                except Exception:
                    pass

            with ThreadPoolExecutor(max_workers=min(6, len(final_candidates))) as pool:
                list(pool.map(_fetch_channel_top_video, final_candidates))

        # =========================================================================
        # Chiến lược 2: Fallback yt-dlp nếu không có API Key hoặc chưa đủ kênh
        # =========================================================================
        if len(final_candidates) < limit:
            try:
                with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                    fallback_q = queries[0] if queries else current_channel_name
                    res = ydl.extract_info(f"ytsearch25:{fallback_q}", download=False)
                    if res and res.get('entries'):
                        existing_ids = {c.get('channel_id') for c in final_candidates if c.get('channel_id')}
                        existing_names = {c.get('channel_name', '').lower() for c in final_candidates}

                        for entry in res['entries']:
                            if not entry:
                                continue
                            uploader = entry.get('channel') or entry.get('uploader') or ''
                            uploader_id = entry.get('channel_id') or ''
                            uploader_url = entry.get('channel_url') or entry.get('uploader_url') or (f"https://www.youtube.com/channel/{uploader_id}" if uploader_id else '')
                            
                            if not uploader or uploader.lower() in existing_names or (uploader_id and uploader_id in existing_ids):
                                continue
                            if current_channel_name and (current_channel_name.lower() in uploader.lower() or uploader.lower() in current_channel_name.lower()):
                                continue

                            v_title = entry.get('title', '')
                            v_dur = entry.get('duration') or 0
                            v_views = entry.get('view_count') or 0
                            
                            if self.is_short_or_shorts_channel(title=v_title, uploader=uploader, duration_sec=v_dur):
                                continue
                            if not is_music_target and self.is_music_or_topic_channel(title=v_title, uploader=uploader):
                                continue
                            if self.is_tv_or_broadcast_network(uploader=uploader, title=v_title):
                                continue

                            # Kiểm tra ngôn ngữ tối thiểu cho fallback
                            cand_text = f"{uploader} {v_title}"
                            if target_lang == 'ko' and not re.search(r'[가-힣]', cand_text):
                                continue
                            if target_lang == 'ja' and not re.search(r'[ぁ-んァ-ヶ]', cand_text):
                                continue
                            if target_lang == 'zh' and not re.search(r'[\u4e00-\u9fff]', cand_text):
                                continue
                            # Fallback tiếng Việt: loại bỏ kênh không có ký tự tiếng Việt hoặc tiếng Anh thuần
                            if target_lang == 'vi':
                                vn_char_found = bool(re.search(r'[đăâêôơưảãạẳẵặẩẫậẻẽẹểễệỉĩịỏõọổỗộởỡợủũụửữựỳỷỹỵằầềồờừắấếốớứ]', cand_text))
                                # Nếu không có ký tự Việt đặc trưng và cũng không có GEO target_geo==VN → bỏ
                                if not vn_char_found and (target_geo or '').upper() == 'VN':
                                    continue

                            # Chỉ nhận video có lượt view tốt (>= 2000 view)
                            if v_views < 2000:
                                continue

                            final_candidates.append({
                                'channel_name': uploader,
                                'title': uploader,
                                'name': uploader,
                                'channel_id': uploader_id,
                                'channel_url': uploader_url,
                                'url': uploader_url,
                                'avatar_url': '',
                                'avatar': '',
                                'thumbnail': '',
                                'sample_matched_videos': 1,
                                'avg_views_sample': v_views,
                                'avg_views': v_views,
                                'subscriber_count': 0,
                                'is_verified': False,
                                'top_video_title': v_title,
                                'top_video_views': v_views
                            })
                            existing_names.add(uploader.lower())
                            if len(final_candidates) >= limit:
                                break
            except Exception as e:
                logger.warning(f"Lỗi fallback yt-dlp: {e}")

            # Cào avatar đa luồng cho các kênh còn thiếu avatar
            need_scrape = [c for c in final_candidates if not c.get('avatar_url') and c.get('channel_url')]
            if need_scrape:
                with ThreadPoolExecutor(max_workers=min(6, len(need_scrape))) as executor:
                    urls = [c['channel_url'] for c in need_scrape]
                    scraped_avatars = list(executor.map(self._scrape_channel_avatar, urls))
                    for c, av in zip(need_scrape, scraped_avatars):
                        if av:
                            c['avatar_url'] = av
                            c['avatar'] = av
                            c['thumbnail'] = av

        return final_candidates[:limit]
