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
            # Tìm ảnh đại diện yt3.googleusercontent.com hoặc yt3.ggpht.com của kênh
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
        
        # YouTube tự tạo kênh - Topic cho ca sĩ
        if ch.endswith("- topic") or " - topic" in ch:
            return True
        if any(w in ch for w in ["vevo", "records", "discos", "official music"]):
            return True
        
        # Tiêu đề dạng bài hát / MV
        music_markers = [
            "official music video", "(official video)", "[official video]", 
            "(video oficial)", "[video oficial]", "videoclip oficial",
            "(audio oficial)", "[audio oficial]", "(audio)",
            "(letra)", "[letra]", "(lyrics)", "[lyrics]", "ft.", "feat."
        ]
        if any(m in t for m in music_markers):
            return True
        return False

    def _build_search_query(
        self,
        current_channel_name: str,
        top_keywords: List[Dict[str, Any]],
        channel_tags: Optional[List[str]] = None,
        niche: Optional[str] = None
    ) -> str:
        """Xây dựng chuỗi tìm kiếm thông minh từ channel tags và từ khóa nội dung."""
        # 1. Ưu tiên lấy tag đa từ giàu ngữ nghĩa từ channel metadata
        if channel_tags:
            # Lọc các tag có >= 2 từ và độ dài hợp lý
            meaningful_tags = []
            for tag in channel_tags:
                clean_tag = str(tag).strip().strip('"').strip("'")
                words = clean_tag.split()
                if len(words) >= 2 and len(clean_tag) >= 5 and len(clean_tag) <= 40:
                    meaningful_tags.append(clean_tag)
            
            if meaningful_tags:
                # Ưu tiên các tag thể loại nổi bật (relatos, historias, review, tech, podcast...)
                for tag in meaningful_tags:
                    t_lower = tag.lower()
                    if any(w in t_lower for w in ['relatos', 'historias', 'cuentos', 'drama', 'stories', 'truyện', 'tâm lý']):
                        return tag
                return meaningful_tags[0]
            elif channel_tags:
                return str(channel_tags[0]).strip().strip('"')

        # 2. Nếu không có channel tags, trích xuất từ top_keywords
        search_terms = []
        for kw in (top_keywords or [])[:4]:
            val = kw.get('keyword') if isinstance(kw, dict) else str(kw)
            val = (val or '').strip()
            # Bỏ qua từ quá ngắn hoặc số
            if val and len(val) >= 3 and not val.isdigit():
                search_terms.append(val)
        
        if search_terms:
            # Ưu tiên cụm từ ghép nếu có
            phrases = [s for s in search_terms if len(s.split()) >= 2]
            if phrases:
                return phrases[0]
            return " ".join(search_terms[:2])

        if niche and niche not in ['general', 'entertainment']:
            return f"{niche} channel"

        return current_channel_name

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
        """Tìm kiếm các kênh đối thủ cùng chủ đề và lấy ảnh đại diện logo chính thức."""
        query = self._build_search_query(
            current_channel_name=current_channel_name,
            top_keywords=top_keywords,
            channel_tags=channel_tags,
            niche=niche
        )
        logger.info(f"Finding similar channels for '{current_channel_name}' with query: '{query}'")

        is_music_target = False
        target_context = f"{current_channel_name} {' '.join(channel_tags or [])} {channel_description or ''}".lower()
        if any(w in target_context for w in ['music', 'música', 'singer', 'ca sĩ', 'bài hát', 'nhạc']):
            is_music_target = True

        candidates: List[Dict[str, Any]] = []

        # =========================================================================
        # Chiến lược 1: Tìm kiếm trực tiếp kênh qua YouTube Data API v3 (type=channel)
        # =========================================================================
        if api_key and api_key.strip():
            try:
                search_url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&type=channel&q={requests.utils.quote(query)}&maxResults={min(25, limit * 3)}&key={api_key.strip()}"
                s_res = requests.get(search_url, timeout=8).json()
                items = s_res.get('items', [])
                
                cids_to_fetch = []
                api_candidate_map = {}

                for it in items:
                    snip = it.get('snippet', {})
                    c_id = snip.get('channelId')
                    c_name = snip.get('channelTitle', '')
                    c_desc = snip.get('description', '')

                    if not c_id or not c_name:
                        continue

                    # Bỏ qua chính kênh hiện tại
                    if current_channel_name and (current_channel_name.lower() in c_name.lower() or c_name.lower() in current_channel_name.lower()):
                        continue
                    if current_channel_url and c_id in current_channel_url:
                        continue

                    # Lọc bỏ kênh Shorts
                    if self.is_short_or_shorts_channel(uploader=c_name):
                        continue

                    # Lọc bỏ kênh nhạc nếu kênh hiện tại không phải nhạc
                    if not is_music_target and self.is_music_or_topic_channel(uploader=c_name, description=c_desc):
                        continue

                    thumb = (snip.get('thumbnails', {}).get('high') or snip.get('thumbnails', {}).get('medium') or snip.get('thumbnails', {}).get('default', {})).get('url', '')

                    cids_to_fetch.append(c_id)
                    api_candidate_map[c_id] = {
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
                        'avg_views': 0,
                        'avg_views_sample': 0,
                        'sample_matched_videos': 1,
                        'top_video_title': '',
                        'top_video_views': 0,
                        'is_verified': False
                    }

                # Lấy số liệu thống kê chi tiết (Subscribers, Views, Videos)
                if cids_to_fetch:
                    detail_url = f"https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics,contentDetails&id={','.join(cids_to_fetch[:20])}&key={api_key.strip()}"
                    d_res = requests.get(detail_url, timeout=8).json()
                    for d_it in d_res.get('items', []):
                        d_id = d_it.get('id')
                        st = d_it.get('statistics', {})
                        sn = d_it.get('snippet', {})
                        if d_id in api_candidate_map:
                            subs = int(st.get('subscriberCount') or 0)
                            v_cnt = int(st.get('videoCount') or 0)
                            tot_v = int(st.get('viewCount') or 0)
                            avg_v = int(tot_v / max(v_cnt, 1)) if tot_v > 0 else 0
                            
                            api_candidate_map[d_id]['subscriber_count'] = subs
                            api_candidate_map[d_id]['avg_views'] = avg_v
                            api_candidate_map[d_id]['avg_views_sample'] = avg_v
                            api_candidate_map[d_id]['is_verified'] = subs >= 100000
                            
                            # Cập nhật avatar chất lượng cao nếu có
                            thumbs = sn.get('thumbnails', {})
                            if thumbs:
                                av = (thumbs.get('high') or thumbs.get('medium') or thumbs.get('default', {})).get('url', '')
                                if av:
                                    api_candidate_map[d_id]['avatar_url'] = av
                                    api_candidate_map[d_id]['avatar'] = av
                                    api_candidate_map[d_id]['thumbnail'] = av

                    # Lấy video tiêu biểu cho các kênh hàng đầu
                    top_cids = cids_to_fetch[:limit]
                    def _fetch_channel_top_video(ch_id: str):
                        uploads_id = 'UU' + ch_id[2:]
                        try:
                            pl_url = f"https://www.googleapis.com/youtube/v3/playlistItems?part=snippet&playlistId={uploads_id}&maxResults=1&key={api_key.strip()}"
                            p_data = requests.get(pl_url, timeout=5).json()
                            pl_items = p_data.get('items', [])
                            if pl_items:
                                return ch_id, pl_items[0].get('snippet', {}).get('title', '')
                        except Exception:
                            pass
                        return ch_id, ''

                    with ThreadPoolExecutor(max_workers=min(6, len(top_cids))) as pool:
                        results = list(pool.map(_fetch_channel_top_video, top_cids))
                        for ch_id, v_title in results:
                            if ch_id in api_candidate_map and v_title:
                                api_candidate_map[ch_id]['top_video_title'] = v_title

                    for c_id in top_cids:
                        if c_id in api_candidate_map:
                            candidates.append(api_candidate_map[c_id])

            except Exception as api_err:
                logger.warning(f"Lỗi khi tìm kênh qua YouTube API: {api_err}")

        # =========================================================================
        # Chiến lược 2: Fallback yt-dlp search nếu chưa đủ số lượng kênh
        # =========================================================================
        if len(candidates) < limit:
            competitors_map = defaultdict(lambda: {
                'channel_name': '',
                'channel_url': '',
                'channel_id': '',
                'avatar_url': '',
                'subscriber_count': 0,
                'videos': [],
                'total_views': 0
            })

            try:
                with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                    res = ydl.extract_info(f"ytsearch30:{query}", download=False)
                    if res and res.get('entries'):
                        existing_ids = {c.get('channel_id') for c in candidates if c.get('channel_id')}
                        existing_names = {c.get('channel_name', '').lower() for c in candidates}

                        for entry in res['entries']:
                            if not entry:
                                continue
                            uploader = entry.get('channel') or entry.get('uploader') or ''
                            uploader_id = entry.get('channel_id') or ''
                            uploader_handle = entry.get('uploader_id') or ''
                            if not uploader_id and uploader_handle.startswith('UC'):
                                uploader_id = uploader_handle
                            
                            uploader_url = entry.get('channel_url') or entry.get('uploader_url') or ''
                            if not uploader_url:
                                if uploader_id:
                                    uploader_url = f"https://www.youtube.com/channel/{uploader_id}"
                                elif uploader_handle and uploader_handle.startswith('@'):
                                    uploader_url = f"https://www.youtube.com/{uploader_handle}"
                            
                            if not uploader or uploader.lower() in existing_names or (uploader_id and uploader_id in existing_ids):
                                continue

                            # Bỏ qua chính kênh đang phân tích
                            if current_channel_name and (current_channel_name.lower() in uploader.lower() or uploader.lower() in current_channel_name.lower()):
                                continue
                            if current_channel_url and uploader_url and current_channel_url.lower() in uploader_url.lower():
                                continue

                            v_title = entry.get('title', '')
                            v_dur = entry.get('duration') or 0
                            v_url = entry.get('url') or f"https://www.youtube.com/watch?v={entry.get('id')}"

                            # Loại bỏ Shorts
                            if self.is_short_or_shorts_channel(title=v_title, uploader=uploader, duration_sec=v_dur, url=v_url):
                                continue

                            # Loại bỏ nhạc nếu kênh không phải nhạc
                            if not is_music_target and self.is_music_or_topic_channel(title=v_title, uploader=uploader):
                                continue

                            v_data = {
                                'title': v_title,
                                'views': entry.get('view_count') or 0,
                                'url': v_url,
                                'thumbnail': entry.get('thumbnails', [{}])[-1].get('url', '') if entry.get('thumbnails') else ''
                            }

                            comp = competitors_map[uploader]
                            comp['channel_name'] = uploader
                            if uploader_id and not comp['channel_id']:
                                comp['channel_id'] = uploader_id
                            if uploader_url and not comp['channel_url']:
                                comp['channel_url'] = uploader_url
                            comp['videos'].append(v_data)
                            comp['total_views'] += v_data['views']
            except Exception as e:
                logger.warning(f"Lỗi khi tìm kiếm kênh đối thủ qua yt-dlp: {e}")

            dlp_items = [
                item for item in competitors_map.values() 
                if item['videos'] and not self.is_short_or_shorts_channel(uploader=item['channel_name'])
            ]
            dlp_items.sort(key=lambda x: int(x['total_views'] / len(x['videos'])), reverse=True)

            needed = limit - len(candidates)
            top_dlp = dlp_items[:needed]

            # Cào avatar đa luồng cho các kênh còn thiếu
            need_scrape = [c for c in top_dlp if not c.get('avatar_url') and c.get('channel_url')]
            if need_scrape:
                with ThreadPoolExecutor(max_workers=min(6, len(need_scrape))) as executor:
                    urls = [c['channel_url'] for c in need_scrape]
                    scraped_avatars = list(executor.map(self._scrape_channel_avatar, urls))
                    for c, av in zip(need_scrape, scraped_avatars):
                        if av:
                            c['avatar_url'] = av

            for data in top_dlp:
                avg_views = int(data['total_views'] / len(data['videos']))
                name = data['channel_name']
                ch_url = data['channel_url'] or f"https://www.youtube.com/results?search_query={name}"
                av_url = data.get('avatar_url', '')

                candidates.append({
                    'channel_name': name,
                    'title': name,
                    'name': name,
                    'channel_id': data.get('channel_id', ''),
                    'channel_url': ch_url,
                    'url': ch_url,
                    'avatar_url': av_url,
                    'avatar': av_url,
                    'thumbnail': av_url,
                    'sample_matched_videos': len(data['videos']),
                    'avg_views_sample': avg_views,
                    'avg_views': avg_views,
                    'subscriber_count': data.get('subscriber_count', 0),
                    'is_verified': int(data.get('subscriber_count', 0) or 0) >= 100000,
                    'top_video_title': data['videos'][0]['title'] if data['videos'] else '',
                    'top_video_views': max([v['views'] for v in data['videos']]) if data['videos'] else 0
                })

        return candidates[:limit]
