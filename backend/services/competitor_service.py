import logging
import re
import requests
from typing import List, Dict, Any, Optional
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import yt_dlp

logger = logging.getLogger(__name__)

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
        niche: Optional[str] = None
    ) -> List[str]:
        """Tạo danh sách các truy vấn ngách đắt giá nhất, đại diện cho toàn bộ thể loại kênh."""
        queries = []
        all_text = f"{current_channel_name} {' '.join(channel_tags or [])} {channel_description or ''}".lower()

        # 1. Ngách Ngoại Tình & Bắt Gian Trả Thù (Infidelity & Revenge Drama)
        if niche in ['infidelity_revenge', 'drama_story'] or any(w in all_text for w in ['infidelidad', 'traición', 'traicion', 'venganza', 'esposa infiel', 'engaño']):
            if any(w in all_text for w in ['esposa', 'infiel', 'traicion', 'traición', 'relatos', 'historias']):
                return [
                    'historias de infidelidad venganza',
                    'relatos de infidelidad',
                    'traicion y venganza historias',
                    'historias de traicion drama familiar'
                ]
            elif any(w in all_text for w in ['ngoại tình', 'bắt gian', 'đánh ghen', 'trả thù']):
                return [
                    'tâm sự ngoại tình bắt gian',
                    'drama ngoại tình trả thù',
                    'đánh ghen bắt gian chuyện có thật'
                ]
            else:
                return [
                    'cheating revenge stories',
                    'infidelity drama stories',
                    'reddit cheating revenge'
                ]

        # 2. Ngách Kể Chuyện Thật / Podcast Đời Thực (Real Life Stories)
        if niche in ['real_life_stories', 'life_stories', 'audio_stories']:
            if any(w in all_text for w in ['relatos', 'historias', 'vida']):
                return [
                    'relatos de vida',
                    'historias para reflexionar',
                    'historias de la vida real'
                ]
            elif any(w in all_text for w in ['kể chuyện', 'tâm sự', 'chuyện đời']):
                return [
                    'kể chuyện đời có thật',
                    'truyện tâm sự đêm muộn',
                    'tâm sự đời thực'
                ]
            else:
                return [
                    'real life stories podcast',
                    'emotional life stories',
                    'true stories narrated'
                ]

        # 3. Ngách Truyện Reddit / Confessions
        if niche == 'reddit_stories' or any(w in all_text for w in ['reddit', 'aita', 'tifu', 'confession']):
            return ['reddit stories', 'aita stories revenge', 'reddit revenge drama']

        # 4. Ngách Bố Chồng Nàng Dâu / Mẹ Chồng Con Dâu
        if niche in ['father_inlaw_drama', 'mother_inlaw_drama']:
            if any(w in all_text for w in ['bố chồng', 'nàng dâu', 'mẹ chồng', 'mẹ vợ']):
                return ['bố chồng nàng dâu tâm sự', 'mẹ chồng nàng dâu drama']
            else:
                return ['mother in law drama stories', 'toxic mother in law reddit']

        # 5. Ngách Kinh Dị / Tâm Linh
        if niche in ['horror_stories', 'horror'] or any(w in all_text for w in ['horror', 'terror', 'truyện ma', 'kinh dị']):
            if any(w in all_text for w in ['terror', 'relatos', 'miedo']):
                return ['relatos de terror', 'historias de terror reales']
            return ['truyện ma có thật', 'horror stories true']

        # 6. Khai thác Channel Tags chính thức
        if channel_tags:
            for tag in channel_tags:
                clean_tag = str(tag).strip().strip('"').strip("'")
                words = clean_tag.split()
                if 2 <= len(words) <= 3 and clean_tag not in queries:
                    queries.append(clean_tag)

        # 7. Dự phòng từ top_keywords
        for kw in (top_keywords or [])[:4]:
            val = kw.get('keyword') if isinstance(kw, dict) else str(kw)
            val = (val or '').strip()
            words = val.split()
            if 2 <= len(words) <= 3 and val not in queries:
                queries.append(val)

        if not queries:
            queries = [current_channel_name]

        return queries[:3]

    def find_similar_channels(
        self,
        current_channel_name: str,
        current_channel_url: str,
        top_keywords: List[Dict[str, Any]],
        channel_tags: Optional[List[str]] = None,
        channel_description: Optional[str] = None,
        niche: Optional[str] = None,
        limit: int = 6,
        api_key: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Tìm kiếm các kênh đối thủ UY TÍN, ĐANG HOẠT ĐỘNG MẠNH trong cùng ngách (loại bỏ hoàn toàn kênh mới 0 sub)."""
        queries = self._build_search_queries(
            current_channel_name=current_channel_name,
            top_keywords=top_keywords,
            channel_tags=channel_tags,
            channel_description=channel_description,
            niche=niche
        )
        logger.info(f"Finding established competitors for '{current_channel_name}' with queries: {queries}")

        is_music_target = False
        target_context = f"{current_channel_name} {' '.join(channel_tags or [])} {channel_description or ''}".lower()
        if any(w in target_context for w in ['music', 'música', 'singer', 'ca sĩ', 'bài hát', 'nhạc']):
            is_music_target = True

        candidates_map: Dict[str, Dict[str, Any]] = {}

        # =========================================================================
        # Chiến lược 1: Tìm kiếm trực tiếp kênh qua YouTube Data API v3 (type=channel)
        # =========================================================================
        if api_key and api_key.strip():
            try:
                candidate_ids = []
                for q in queries:
                    search_url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&type=channel&q={requests.utils.quote(q)}&maxResults=10&key={api_key.strip()}"
                    s_res = requests.get(search_url, timeout=7).json()
                    for it in s_res.get('items', []):
                        snip = it.get('snippet', {})
                        c_id = snip.get('channelId')
                        c_name = snip.get('channelTitle', '')
                        c_desc = snip.get('description', '')

                        if not c_id or not c_name or c_id in candidate_ids:
                            continue

                        # Bỏ qua chính kênh hiện tại
                        if current_channel_name and (current_channel_name.lower() in c_name.lower() or c_name.lower() in current_channel_name.lower()):
                            continue
                        if current_channel_url and c_id in current_channel_url:
                            continue

                        # Lọc bỏ Shorts & Nhạc
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
                            'avg_views': 0,
                            'avg_views_sample': 0,
                            'sample_matched_videos': 1,
                            'top_video_title': '',
                            'top_video_views': 0,
                            'is_verified': False
                        }

                # Lấy số liệu thống kê chi tiết và LỌC KÊNH UY TÍN
                if candidate_ids:
                    chunk = candidate_ids[:40]
                    detail_url = f"https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics,contentDetails&id={','.join(chunk)}&key={api_key.strip()}"
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

        # Chấm điểm độ tương đồng ngách để đưa đúng đối thủ thực sự lên đầu
        def _score_candidate(cand: Dict[str, Any]) -> int:
            text = (cand['channel_name'] + ' ' + cand['description']).lower()
            score = 0
            # Trùng từ khóa ngách chính
            if any(w in text for w in ['infidelidad', 'infiel', 'infidelidade', 'ngoại tình', 'bắt gian', 'cheating']):
                score += 50
            if any(w in text for w in ['traición', 'traicion', 'venganza', 'trả thù', 'revenge', 'betrayal']):
                score += 40
            if any(w in text for w in ['drama', 'secretos familiares', 'reddit', 'confesiones', 'tâm sự']):
                score += 25
            if any(w in text for w in ['historias', 'relatos', 'cuentos', 'chuyện']):
                score += 15
            
            # Ưu tiên kênh có quy mô vừa & lớn hoạt động ổn định (5K - 800K subs)
            subs = cand.get('subscriber_count', 0)
            if 3000 <= subs <= 800000:
                score += 30
            elif subs > 800000:
                score += 15

            # Cộng điểm lượt xem trung bình
            avg_v = cand.get('avg_views', 0)
            score += min(20, avg_v // 5000)
            return score

        established_candidates.sort(key=_score_candidate, reverse=True)
        final_candidates = established_candidates[:limit]

        # Lấy video tiêu biểu cho các kênh được chọn
        if api_key and api_key.strip() and final_candidates:
            def _fetch_channel_top_video(cand: Dict[str, Any]):
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
        # Chiến lược 2: Fallback yt-dlp nếu vẫn chưa đủ 6 kênh
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
