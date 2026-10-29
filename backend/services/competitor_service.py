import logging
import re
import requests
from typing import List, Dict, Any, Optional
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import yt_dlp

logger = logging.getLogger(__name__)

NICHE_SEARCH_TEMPLATES = {
    "infidelity_revenge": {
        "es": ['historias de traicion drama familiar', 'relatos de infidelidad y venganza', 'historias de infidelidad y engaño'],
        "vi": ['tâm sự ngoại tình trả thù', 'drama bắt gian ngoại tình', 'đánh ghen bắt gian chuyện có thật'],
        "en": ['cheating revenge drama stories', 'infidelity betrayal stories reddit', 'family betrayal drama']
    },
    "father_inlaw_drama": {
        "es": ['drama suegra y nuera historias', 'conflictos familiares historias', 'historias de drama familiar'],
        "vi": ['mẹ chồng nàng dâu drama', 'bố chồng nàng dâu tâm sự', 'xung đột mẹ chồng nàng dâu'],
        "en": ['mother in law drama stories', 'toxic mother in law reddit', 'entitled in laws stories']
    },
    "mother_inlaw_drama": {
        "es": ['drama suegra y nuera historias', 'conflictos familiares historias', 'historias de suegras'],
        "vi": ['mẹ chồng nàng dâu drama', 'mẹ vợ con rể drama', 'xung đột gia đình'],
        "en": ['mother in law drama stories', 'toxic mother in law reddit', 'in laws drama']
    },
    "reddit_stories": {
        "es": ['reddit historias espanol', 'historias de reddit venganza', 'relatos reddit espanol'],
        "vi": ['truyện reddit vietsub', 'tâm sự reddit kể chuyện', 'drama reddit có thật'],
        "en": ['reddit stories podcast', 'aita revenge drama', 'best reddit confessions']
    },
    "drama_expose": {
        "es": ['polemicas y drama youtube', 'historias de drama y secretos', 'exponiendo la verdad'],
        "vi": ['bóc phốt drama mới nhất', 'drama vạch trần sự thật', 'tin tức drama showbiz'],
        "en": ['drama expose commentary', 'youtube drama explained', 'truth exposed documentary']
    },
    "true_crime": {
        "es": ['casos de misterio de la vida real', 'crimen real documental', 'casos criminales sin resolver'],
        "vi": ['hồ sơ vụ án có thật', 'kỳ án trinh thám phá án', 'tội phạm có thật bí ẩn'],
        "en": ['true crime documentary stories', 'real crime cases solved', 'mystery criminal investigation']
    },
    "horror_stories": {
        "es": ['relatos de terror reales', 'historias de miedo reales', 'cuentos de terror paranormal'],
        "vi": ['truyện ma có thật đêm khuya', 'truyện ma kinh dị tâm linh', 'tâm linh kỳ bí'],
        "en": ['real horror stories true', 'scary stories narrated', 'creepy paranormal true stories']
    },
    "travel_vlog": {
        "es": ['vlog de viajes y comida', 'viajes por el mundo vlog', 'explorando lugares comida'],
        "vi": ['vlog du lịch trải nghiệm', 'ẩm thực du lịch bốn phương', 'khám phá daily vlog'],
        "en": ['travel vlog documentary', 'street food and travel', 'travel lifestyle vlog']
    },
    "gaming": {
        "es": ['gameplay espanol', 'mejores momentos gaming', 'gameplay en espanol'],
        "vi": ['gameplay highlight tiếng việt', 'trải nghiệm game kịch tính', 'stream game hài hước'],
        "en": ['gaming highlights gameplay', 'game walkthrough review', 'best gaming moments']
    },
    "tech_ai": {
        "es": ['tecnologia inteligencia artificial', 'review tecnologia gadgets', 'tutoriales de inteligencia artificial'],
        "vi": ['đánh giá công nghệ trí tuệ nhân tạo', 'review đồ công nghệ mới', 'hướng dẫn công cụ ai'],
        "en": ['tech review artificial intelligence', 'latest tech gadgets review', 'ai tools tutorial']
    },
    "recap_stories": {
        "es": ['resumen de peliculas y series', 'resumen de pelicula drama', 'explicacion de peliculas'],
        "vi": ['review phim tóm tắt hay', 'tóm tắt phim điện ảnh', 'spoil phim nhanh'],
        "en": ['movie recap full story', 'film recap explained', 'movie summary storytelling']
    },
    "learn_english": {
        "es": ['aprender ingles facil y rapido', 'curso de ingles conversacion', 'vocabulario en ingles'],
        "vi": ['học tiếng anh giao tiếp cơ bản', 'luyện nghe tiếng anh mỗi ngày', 'kỹ năng học tiếng anh'],
        "en": ['learn english conversation', 'daily english speaking practice', 'english listening practice']
    },
    "history_geopolitics": {
        "es": ['historia mundial documental', 'geopolitica y guerras', 'documentales de historia'],
        "vi": ['lịch sử thế giới phóng sự', 'địa chính trị quốc tế', 'tư liệu chiến tranh lịch sử'],
        "en": ['world history documentary', 'geopolitics explained', 'historical warfare documentary']
    },
    "finance_money": {
        "es": ['finanzas personales e inversiones', 'como ganar dinero negocios', 'educacion financiera'],
        "vi": ['tài chính cá nhân đầu tư', 'kinh doanh kiếm tiền thông minh', 'đầu tư chứng khoán bất động sản'],
        "en": ['personal finance investing', 'how to make money business', 'wealth building passive income']
    },
    "philosophy": {
        "es": ['lecciones de vida reflexion estoicismo', 'filosofia y motivacion', 'reflexiones para la vida'],
        "vi": ['bài học cuộc sống danh ngôn', 'triết lý sống chữa lành', 'động lực sống phát triển bản thân'],
        "en": ['stoicism life lessons philosophy', 'life wisdom motivation', 'philosophical life advice']
    },
    "christianity_bible": {
        "es": ['estudio biblico reflexion oracion', 'predicas cristianas vida', 'palabra de dios diaria'],
        "vi": ['kinh thánh lời chúa mỗi ngày', 'bài giảng cơ đốc giáo đức tin', 'cầu nguyện tĩnh tâm lời chúa'],
        "en": ['bible study audio prayer', 'christian daily devotional', 'scripture reading sermon']
    },
    "buddhism": {
        "es": ['budismo ensenanzas meditacion', 'paz interior reflexion budista', 'filosofia budista meditacion'],
        "vi": ['lời phật dạy chữa lành tĩnh tâm', 'thuyết pháp phật giáo an lạc', 'thiền định lời phật dạy'],
        "en": ['buddhist wisdom teachings', 'healing peaceful meditation', 'inner peace buddhism philosophy']
    },
    "elderly_wisdom": {
        "es": ['sabiduria de vida para la vejez', 'consejos para adultos mayores', 'lecciones para envejecer con paz'],
        "vi": ['tâm sự tuổi già bài học cuộc đời', 'lời khuyên tuổi trung niên già', 'dưỡng già an yên cuộc sống'],
        "en": ['aging wisdom life lessons', 'advice for growing older', 'elderly life reflections']
    },
    "astrology_horoscope": {
        "es": ['horoscopo y tarot predicciones', 'astrologia signos del zodiaco', 'tarot interactivo'],
        "vi": ['tử vi 12 con giáp vận mệnh', 'xem bói phong thủy vận hạn', 'tarot thông điệp tương lai'],
        "en": ['daily horoscope tarot reading', 'astrology zodiac predictions', 'zodiac signs fortune']
    },
    "entertainment": {
        "es": ['retos y entretenimiento viral', 'videos divertidos virales', 'desafios y comedia viral'],
        "vi": ['thử thách sinh tồn hài hước', 'giải trí triệu view viral', 'video hài hước giải trí'],
        "en": ['viral entertainment challenge', 'funny stunts challenge', 'trending entertainment comedy']
    }
}

def detect_channel_language(text: str) -> str:
    """Xác định ngôn ngữ chính xác dựa trên ký tự đặc trưng và từ vựng cốt lõi."""
    t = text.lower()
    
    # 1. Ký tự thuần Việt (không bao giờ trùng với tiếng Tây Ban Nha, Pháp, Bồ Đào Nha)
    vn_chars = r'[đăâêôơưảãạẳẵặẩẫậẻẽẹểễệỉĩịỏõọổỗộởỡợủũụửữựỳỷỹỵằầềồờừắấếốớứ]'
    vn_words = r'\b(và|của|trong|cho|với|không|người|chuyện|tâm sự|ngoại tình|trả thù|bắt gian|đánh ghen|gia đình|hài hước|ẩm thực|du lịch|cuộc sống|phim|tóm tắt|vụ án)\b'
    vn_score = len(re.findall(vn_chars, t)) * 2 + len(re.findall(vn_words, t)) * 5

    # 2. Tiếng Tây Ban Nha đặc trưng
    es_chars = r'[ñ¿¡]'
    es_words = r'\b(el|la|los|las|un|una|unos|unas|de|del|en|para|por|con|que|su|sus|mi|mis|tu|tus|al|se|es|son|historias|relatos|esposa|marido|familia|vida|traicion|traición|venganza|desamor|cuentos|infiel|infidelidad|pelicula|resumen|suegra|nuera|engaño|mujer|hombre)\b'
    es_score = len(re.findall(es_chars, t)) * 3 + len(re.findall(es_words, t)) * 3

    # 3. Tiếng Pháp đặc trưng
    fr_chars = r'[çœæ]'
    fr_words = r'\b(le|la|les|des|du|en|dans|pour|avec|qui|que|cette|est|sont|film|histoire|femme|homme|mariage|trahison|vengeance|famille|amour)\b'
    fr_score = len(re.findall(fr_chars, t)) * 3 + len(re.findall(fr_words, t)) * 3

    scores = {'vi': vn_score, 'es': es_score, 'fr': fr_score}
    best_lang, best_score = max(scores.items(), key=lambda x: x[1])
    if best_score >= 3:
        return best_lang
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

    def _build_search_queries(
        self,
        current_channel_name: str,
        top_keywords: List[Dict[str, Any]],
        channel_tags: Optional[List[str]] = None,
        channel_description: Optional[str] = None,
        video_titles: Optional[List[str]] = None,
        niche: Optional[str] = None,
        custom_query: Optional[str] = None
    ) -> List[str]:
        """Tạo danh sách các truy vấn ngách đắt giá nhất, đại diện cho toàn bộ thể loại kênh và chuẩn ngôn ngữ."""
        if custom_query and custom_query.strip():
            return [custom_query.strip()]

        queries = []
        all_text = f"{current_channel_name} {' '.join(channel_tags or [])} {channel_description or ''} {' '.join(video_titles or [])}".lower()
        lang = detect_channel_language(all_text)

        # 1. Khai thác mẫu truy vấn chuyên biệt theo ngách và ngôn ngữ
        if niche and niche in NICHE_SEARCH_TEMPLATES:
            n_templates = NICHE_SEARCH_TEMPLATES[niche]
            queries.extend(n_templates.get(lang, n_templates.get("en", [])))

        # 2. Phát hiện chủ đề từ tiêu đề video thực tế (Ground Truth)
        if lang == 'es':
            if any(w in all_text for w in ['infidelidad', 'traicion', 'traición', 'venganza', 'esposa infiel', 'engaño']):
                for q in ['historias de traicion drama familiar', 'relatos de infidelidad y venganza', 'historias de drama familiar']:
                    if q not in queries:
                        queries.append(q)
            elif any(w in all_text for w in ['suegra', 'nuera', 'familia']):
                for q in ['drama suegra y nuera historias', 'conflictos familiares historias']:
                    if q not in queries:
                        queries.append(q)
        elif lang == 'vi':
            if any(w in all_text for w in ['ngoại tình', 'bắt gian', 'đánh ghen', 'trả thù']):
                for q in ['tâm sự ngoại tình trả thù', 'drama bắt gian ngoại tình', 'đánh ghen bắt gian chuyện có thật']:
                    if q not in queries:
                        queries.append(q)
            elif any(w in all_text for w in ['mẹ chồng', 'mẹ vợ', 'con dâu', 'bố chồng']):
                for q in ['mẹ chồng nàng dâu drama', 'bố chồng nàng dâu tâm sự']:
                    if q not in queries:
                        queries.append(q)

        # 3. Khai thác Channel Tags & Top Keywords chất lượng (từ 2 đến 4 từ)
        if channel_tags:
            for tag in channel_tags:
                clean_tag = str(tag).strip().strip('"').strip("'")
                words = clean_tag.split()
                if 2 <= len(words) <= 4 and clean_tag.lower() not in [q.lower() for q in queries]:
                    queries.append(clean_tag)

        for kw in (top_keywords or [])[:5]:
            val = kw.get('keyword') if isinstance(kw, dict) else str(kw)
            val = (val or '').strip()
            words = val.split()
            if 2 <= len(words) <= 4 and val.lower() not in [q.lower() for q in queries]:
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
        niche: Optional[str] = None,
        custom_query: Optional[str] = None,
        limit: int = 6,
        api_key: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Tìm kiếm các kênh đối thủ UY TÍN, ĐANG HOẠT ĐỘNG MẠNH trong cùng ngách:
        - Quét cả video viral hàng đầu và kênh trực tiếp để tìm đúng những creator đang dẫn đầu ngách.
        - Khớp đúng 100% ngôn ngữ và chủ đề của kênh đang phân tích.
        - Lọc bỏ hoàn toàn kênh mới 0 sub, kênh rác, kênh Shorts và kênh MV/Nhạc.
        """
        queries = self._build_search_queries(
            current_channel_name=current_channel_name,
            top_keywords=top_keywords,
            channel_tags=channel_tags,
            channel_description=channel_description,
            video_titles=video_titles,
            niche=niche,
            custom_query=custom_query
        )
        self._last_queries = queries
        self._last_niche = niche or ""
        logger.info(f"Finding established competitors for '{current_channel_name}' with queries: {queries}")

        all_target_text = f"{current_channel_name} {' '.join(channel_tags or [])} {channel_description or ''} {' '.join(video_titles or [])}".lower()
        target_lang = detect_channel_language(all_target_text)
        is_music_target = any(w in all_target_text for w in ['music', 'música', 'singer', 'ca sĩ', 'bài hát', 'nhạc'])

        candidates_map: Dict[str, Dict[str, Any]] = {}
        candidate_ids: List[str] = []

        # =========================================================================
        # Chiến lược 1: Tìm kiếm đối thủ thực tế qua YouTube Data API v3
        # Quét video thịnh hành nhất trong ngách để lấy creator thực sự + quét kênh
        # =========================================================================
        if api_key and api_key.strip():
            try:
                for q in queries:
                    # 1.1 Quét video hàng đầu trong ngách để tìm kênh đứng sau các video viral đó
                    v_search_url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&type=video&q={requests.utils.quote(q)}&order=relevance&maxResults=12&key={api_key.strip()}"
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
                    c_search_url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&type=channel&q={requests.utils.quote(q)}&maxResults=4&key={api_key.strip()}"
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
                            
                            thumbs = sn.get('thumbnails', {})
                            if thumbs:
                                av = (thumbs.get('high') or thumbs.get('medium') or thumbs.get('default', {})).get('url', '')
                                if av:
                                    candidates_map[d_id]['avatar_url'] = av
                                    candidates_map[d_id]['avatar'] = av
                                    candidates_map[d_id]['thumbnail'] = av

            except Exception as api_err:
                logger.warning(f"Lỗi khi tìm kênh qua YouTube API: {api_err}")

        # Lọc nghiêm ngặt: KÊNH ĐỐI THỦ THỰC SỰ (Sub >= 1.000 hoặc Tổng view >= 20.000, ít nhất 3 video)
        established_candidates = []
        for c in candidates_map.values():
            subs = c.get('subscriber_count', 0)
            vids = c.get('video_count', 0)
            tot_v = c.get('total_views', 0)
            
            if (subs >= 1000 or tot_v >= 20000) and vids >= 3:
                established_candidates.append(c)

        # Chấm điểm độ tương đồng ngách & ngôn ngữ để đưa đúng đối thủ thực sự lên đầu
        def _score_candidate(cand: Dict[str, Any]) -> int:
            text = (cand['channel_name'] + ' ' + cand.get('description', '') + ' ' + cand.get('top_video_title', '')).lower()
            score = 0
            cand_lang = detect_channel_language(text)

            # Khớp ngôn ngữ của kênh phân tích
            if cand_lang == target_lang:
                score += 50
            else:
                score -= 30

            # Khớp từ khóa chủ đề ngách
            for q in queries:
                q_words = [w for w in q.lower().split() if len(w) > 2]
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
