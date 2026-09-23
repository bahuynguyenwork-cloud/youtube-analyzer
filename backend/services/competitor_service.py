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

    def find_similar_channels(self, current_channel_name: str, current_channel_url: str, top_keywords: List[Dict[str, Any]], limit: int = 6, api_key: Optional[str] = None) -> List[Dict[str, Any]]:
        """Tìm kiếm các kênh đối thủ cùng chủ đề và lấy ảnh đại diện logo chính thức (loại bỏ hoàn toàn kênh Shorts)."""
        if not top_keywords:
            return []

        # Lấy 2-3 từ khóa trọng tâm
        search_terms = []
        for kw in top_keywords[:3]:
            if isinstance(kw, dict):
                val = kw.get('keyword') or kw.get('word') or ''
            else:
                val = str(kw)
            if val.strip():
                search_terms.append(val.strip())
        
        if not search_terms:
            search_terms = [current_channel_name]

        query = " ".join(search_terms)

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
                        
                        if not uploader:
                            continue

                        # Bỏ qua chính kênh đang phân tích
                        if current_channel_name and (current_channel_name.lower() in uploader.lower() or uploader.lower() in current_channel_name.lower()):
                            continue
                        if current_channel_url and uploader_url and current_channel_url.lower() in uploader_url.lower():
                            continue

                        v_title = entry.get('title', '')
                        v_dur = entry.get('duration') or 0
                        v_url = entry.get('url') or f"https://www.youtube.com/watch?v={entry.get('id')}"

                        # TUYỆT ĐỐI BỎ QUA SHORTS VÀ KÊNH CHUYÊN SHORTS
                        if self.is_short_or_shorts_channel(title=v_title, uploader=uploader, duration_sec=v_dur, url=v_url):
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
            logger.warning(f"Lỗi khi tìm kiếm kênh đối thủ: {e}")

        # Lọc danh sách ứng viên (loại bỏ hoàn toàn các kênh có từ khóa Shorts)
        candidate_items = [
            item for item in competitors_map.values() 
            if item['videos'] and not self.is_short_or_shorts_channel(uploader=item['channel_name'])
        ]
        candidate_items.sort(key=lambda x: int(x['total_views'] / len(x['videos'])), reverse=True)
        top_candidates = candidate_items[:limit]

        # 1. Trích xuất logo chính thức qua YouTube Data API v3 nếu có API Key
        channel_ids_to_fetch = [c['channel_id'] for c in top_candidates if c.get('channel_id') and c['channel_id'].startswith('UC')]
        if api_key and channel_ids_to_fetch:
            try:
                ch_api_url = f"https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics&id={','.join(channel_ids_to_fetch)}&key={api_key}"
                ch_res = requests.get(ch_api_url, timeout=8).json()
                items = ch_res.get('items', [])
                for it in items:
                    c_id = it.get('id')
                    snippet = it.get('snippet', {})
                    stats = it.get('statistics', {})
                    
                    # Avatar logo
                    avatar = ""
                    thumbs = snippet.get('thumbnails', {})
                    if thumbs:
                        avatar = (thumbs.get('high') or thumbs.get('medium') or thumbs.get('default', {})).get('url', '')
                    subs = int(stats.get('subscriberCount', 0))

                    for c in top_candidates:
                        if c.get('channel_id') == c_id:
                            if avatar:
                                c['avatar_url'] = avatar
                            if subs:
                                c['subscriber_count'] = subs
            except Exception as api_err:
                logger.warning(f"Lỗi lấy avatar qua API: {api_err}")

        # 2. Với các kênh chưa có avatar, cào avatar siêu tốc bằng đa luồng
        need_scrape = [c for c in top_candidates if not c.get('avatar_url') and c.get('channel_url')]
        if need_scrape:
            with ThreadPoolExecutor(max_workers=min(6, len(need_scrape))) as executor:
                urls = [c['channel_url'] for c in need_scrape]
                scraped_avatars = list(executor.map(self._scrape_channel_avatar, urls))
                for c, av in zip(need_scrape, scraped_avatars):
                    if av:
                        c['avatar_url'] = av

        competitors_list = []
        for data in top_candidates:
            avg_views = int(data['total_views'] / len(data['videos']))
            name = data['channel_name']
            ch_url = data['channel_url'] or f"https://www.youtube.com/results?search_query={name}"
            av_url = data.get('avatar_url', '')

            competitors_list.append({
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

        return competitors_list
