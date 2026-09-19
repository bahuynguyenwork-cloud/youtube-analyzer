import re
import datetime
import logging
import statistics
import urllib.parse
import requests
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, List, Optional
import yt_dlp

logger = logging.getLogger(__name__)

class YouTubeService:
    def __init__(self):
        self.ydl_opts_base = {
            'quiet': True,
            'skip_download': True,
            'no_warnings': True,
            'extract_flat': True,
            'socket_timeout': 15,
        }

    def normalize_channel_input(self, channel_input: str) -> str:
        raw = urllib.parse.unquote(channel_input).strip()
        if not raw:
            raise ValueError('Vui lòng nhập URL kênh, @handle hoặc tên kênh.')

        raw = raw.split('?')[0].rstrip('/')

        if raw.startswith('http://') or raw.startswith('https://'):
            base_url = re.sub(r'/(featured|about|videos|community|shorts|streams)$', '', raw)
            return base_url
        elif raw.startswith('@'):
            return f'https://www.youtube.com/{raw}'
        elif raw.startswith('UC') and len(raw) == 24:
            return f'https://www.youtube.com/channel/{raw}'
        else:
            return f'ytsearch1:{raw}'

    def _fetch_via_api(self, channel_query: str, max_videos: int = 30, api_key: str = "") -> Optional[Dict[str, Any]]:
        raw = urllib.parse.unquote(channel_query).strip()
        ch_item = None
        
        # 1. Direct channel ID
        if '/channel/' in raw:
            cid = raw.split('/channel/')[-1].split('/')[0].split('?')[0]
            try:
                r = requests.get(f'https://www.googleapis.com/youtube/v3/channels?part=snippet,contentDetails,statistics&id={cid}&key={api_key}', timeout=8).json()
                if r.get('items'):
                    ch_item = r['items'][0]
            except Exception as e:
                logger.warning(f"Error fetching channel by id {cid}: {e}")
        elif raw.startswith('UC') and len(raw) == 24:
            try:
                r = requests.get(f'https://www.googleapis.com/youtube/v3/channels?part=snippet,contentDetails,statistics&id={raw}&key={api_key}', timeout=8).json()
                if r.get('items'):
                    ch_item = r['items'][0]
            except Exception as e:
                logger.warning(f"Error fetching channel by raw id {raw}: {e}")

        # 2. Direct handle
        if not ch_item and '@' in raw:
            handle = '@' + raw.split('@')[-1].split('/')[0].split('?')[0]
            enc_h = urllib.parse.quote(handle)
            try:
                r = requests.get(f'https://www.googleapis.com/youtube/v3/channels?part=snippet,contentDetails,statistics&forHandle={enc_h}&key={api_key}', timeout=8).json()
                if r.get('items'):
                    ch_item = r['items'][0]
                if not ch_item:
                    enc_h2 = urllib.parse.quote(handle.replace('@', ''))
                    r = requests.get(f'https://www.googleapis.com/youtube/v3/channels?part=snippet,contentDetails,statistics&forHandle={enc_h2}&key={api_key}', timeout=8).json()
                    if r.get('items'):
                        ch_item = r['items'][0]
            except Exception as e:
                logger.warning(f"Error fetching channel by handle {handle}: {e}")

        # 3. Search query fallback
        if not ch_item:
            clean_q = raw.replace('https://www.youtube.com/', '').replace('http://www.youtube.com/', '').replace('@', '').strip()
            if clean_q:
                try:
                    r = requests.get(f'https://www.googleapis.com/youtube/v3/search?part=snippet&type=channel&q={urllib.parse.quote(clean_q)}&key={api_key}', timeout=8).json()
                    if r.get('items'):
                        cid = r['items'][0]['snippet']['channelId']
                        r2 = requests.get(f'https://www.googleapis.com/youtube/v3/channels?part=snippet,contentDetails,statistics&id={cid}&key={api_key}', timeout=8).json()
                        if r2.get('items'):
                            ch_item = r2['items'][0]
                except Exception as e:
                    logger.warning(f"Error searching channel {clean_q}: {e}")

        if not ch_item:
            return None

        snip = ch_item.get('snippet', {})
        stats_raw = ch_item.get('statistics', {})
        ch_id = ch_item.get('id', '')
        custom_url = snip.get('customUrl', '')
        ch_url = f'https://www.youtube.com/{custom_url}' if custom_url else f'https://www.youtube.com/channel/{ch_id}'

        thumbs = snip.get('thumbnails', {})
        avatar = thumbs.get('high', {}).get('url') or thumbs.get('medium', {}).get('url') or thumbs.get('default', {}).get('url', '')

        channel_meta = {
            'channel_title': snip.get('title', 'YouTube Channel'),
            'channel_url': ch_url,
            'channel_id': ch_id,
            'subscriber_count': int(stats_raw.get('subscriberCount') or 0),
            'total_channel_views': int(stats_raw.get('viewCount') or 0),
            'video_count': int(stats_raw.get('videoCount') or 0),
            'avatar_url': avatar,
            'banner_url': '',
            'description': snip.get('description', ''),
            'country': snip.get('country', ''),
            'is_verified': False
        }

        uploads_id = ch_item.get('contentDetails', {}).get('relatedPlaylists', {}).get('uploads')
        videos: List[Dict[str, Any]] = []
        if uploads_id:
            try:
                p_res = requests.get(
                    f'https://www.googleapis.com/youtube/v3/playlistItems?part=snippet,contentDetails&playlistId={uploads_id}&maxResults={min(50, max_videos)}&key={api_key}', 
                    timeout=8
                ).json()
                items = p_res.get('items', [])
                v_ids = [it['contentDetails']['videoId'] for it in items if it.get('contentDetails', {}).get('videoId')]
                if v_ids:
                    ids_p = ','.join(v_ids)
                    d_res = requests.get(
                        f'https://www.googleapis.com/youtube/v3/videos?part=snippet,statistics,contentDetails&id={ids_p}&key={api_key}', 
                        timeout=8
                    ).json()
                    v_map = {item['id']: item for item in d_res.get('items', [])}
                    for it in items:
                        vid = it['contentDetails']['videoId']
                        det = v_map.get(vid, {})
                        d_snip = det.get('snippet', it.get('snippet', {}))
                        d_stats = det.get('statistics', {})
                        pub_at = d_snip.get('publishedAt', '')
                        dt_vn = None
                        v_ts = None
                        date_str = ''
                        pub_vn_str = ''
                        if pub_at:
                            try:
                                dt = datetime.datetime.fromisoformat(pub_at.replace('Z', '+00:00'))
                                v_ts = dt.timestamp()
                                dt_vn = dt.astimezone(datetime.timezone(datetime.timedelta(hours=7)))
                                date_str = dt_vn.strftime('%d/%m/%Y')
                                pub_vn_str = dt_vn.strftime('%d/%m/%Y %H:%M')
                            except Exception:
                                pass

                        v_thumbs = d_snip.get('thumbnails', {})
                        thumb_u = v_thumbs.get('high', {}).get('url') or v_thumbs.get('medium', {}).get('url') or f'https://i.ytimg.com/vi/{vid}/hqdefault.jpg'

                        videos.append({
                            'id': vid,
                            'title': d_snip.get('title', ''),
                            'url': f'https://www.youtube.com/watch?v={vid}',
                            'view_count': int(d_stats.get('viewCount') or 0),
                            'timestamp': v_ts,
                            'date': date_str,
                            'publish_time_vn': pub_vn_str,
                            'duration_seconds': 0,
                            'duration_formatted': '00:00',
                            'thumbnail': thumb_u,
                            'description': d_snip.get('description', '')
                        })
            except Exception as e:
                logger.warning(f"Error fetching uploads playlist videos via API: {e}")

        stats = self.compute_performance_metrics(videos, channel_meta['subscriber_count'])
        return {
            'channel': channel_meta,
            'videos': videos,
            'stats': stats
        }

    def get_channel_info_and_videos(self, channel_query: str, max_videos: int = 30, api_key: Optional[str] = None) -> Dict[str, Any]:
        if api_key and api_key.strip():
            api_res = self._fetch_via_api(channel_query, max_videos=max_videos, api_key=api_key.strip())
            if api_res and api_res.get('videos'):
                return api_res

        normalized = self.normalize_channel_input(channel_query)
        channel_url = normalized

        if normalized.startswith('ytsearch1:'):
            search_query = normalized
            with yt_dlp.YoutubeDL(self.ydl_opts_base) as ydl:
                search_res = ydl.extract_info(search_query, download=False)
                if not search_res or not search_res.get('entries'):
                    raise ValueError(f'Không tìm thấy kênh nào khớp với từ khóa \'{channel_query}\'.')
                first_entry = search_res['entries'][0]
                channel_url = first_entry.get('uploader_url') or first_entry.get('channel_url')
                if not channel_url:
                    uploader = first_entry.get('uploader') or ''
                    channel_url = f'https://www.youtube.com/@{uploader}' if uploader else ''
                if not channel_url:
                    raise ValueError('Không thể xác định URL kênh từ kết quả tìm kiếm.')

        channel_url = channel_url.rstrip('/')
        videos_url = f'{channel_url}/videos'
        about_url = f'{channel_url}/about'

        channel_meta: Dict[str, Any] = {
            'channel_title': 'YouTube Channel',
            'channel_url': channel_url,
            'channel_id': '',
            'subscriber_count': 0,
            'total_channel_views': 0,
            'video_count': 0,
            'avatar_url': '',
            'banner_url': '',
            'description': '',
            'country': '',
            'is_verified': False,
        }

        try:
            ydl_opts_about = dict(self.ydl_opts_base)
            ydl_opts_about['extract_flat'] = 'in_playlist'
            ydl_opts_about['playlist_items'] = '1-1'
            with yt_dlp.YoutubeDL(ydl_opts_about) as ydl:
                about_res = ydl.extract_info(about_url, download=False)
                if about_res:
                    channel_meta['channel_title'] = about_res.get('channel') or about_res.get('uploader') or about_res.get('title') or 'YouTube Channel'
                    channel_meta['channel_id'] = about_res.get('channel_id') or about_res.get('id') or ''
                    channel_meta['subscriber_count'] = about_res.get('channel_follower_count') or 0
                    channel_meta['total_channel_views'] = about_res.get('view_count') or 0
                    channel_meta['description'] = about_res.get('description') or ''
                    channel_meta['is_verified'] = bool(about_res.get('channel_is_verified'))
                    channel_meta['video_count'] = about_res.get('playlist_count') or 0

                    thumbs = about_res.get('thumbnails', [])
                    if thumbs:
                        channel_meta['avatar_url'] = thumbs[-1].get('url', '')
        except Exception as e:
            logger.warning(f'Không lấy được /about: {e}')

        ydl_opts_videos = dict(self.ydl_opts_base)
        ydl_opts_videos['extract_flat'] = True
        ydl_opts_videos['playlist_items'] = f'1-{max_videos}'

        videos: List[Dict[str, Any]] = []
        try:
            with yt_dlp.YoutubeDL(ydl_opts_videos) as ydl:
                videos_res = ydl.extract_info(videos_url, download=False)
                if not videos_res:
                    videos_res = ydl.extract_info(channel_url, download=False)

                if videos_res:
                    if not channel_meta['channel_title'] or channel_meta['channel_title'] == 'YouTube Channel':
                        channel_meta['channel_title'] = (videos_res.get('channel') or videos_res.get('uploader') or videos_res.get('title', 'YouTube Channel')).replace(' - Videos', '')
                    if not channel_meta['channel_id']:
                        channel_meta['channel_id'] = videos_res.get('channel_id') or ''
                    if not channel_meta['avatar_url']:
                        for th in videos_res.get('thumbnails', []):
                            if 'avatar' in th.get('id', '').lower() or 'avatar' in th.get('url', '').lower():
                                channel_meta['avatar_url'] = th.get('url', '')
                                break
                        if not channel_meta['avatar_url'] and videos_res.get('thumbnails'):
                            channel_meta['avatar_url'] = videos_res['thumbnails'][0].get('url', '')

                    raw_entries = videos_res.get('entries', []) or []
                    for entry in raw_entries:
                        if not entry:
                            continue
                        v_id = entry.get('id', '')
                        v_title = entry.get('title', 'Không có tiêu đề')
                        v_views = entry.get('view_count') or 0
                        v_timestamp = entry.get('timestamp')
                        v_duration = entry.get('duration') or 0
                        
                        v_date_str = ''
                        if v_timestamp:
                            try:
                                v_date_str = datetime.datetime.fromtimestamp(v_timestamp).strftime('%d/%m/%Y')
                            except Exception:
                                v_date_str = ''

                        thumb_url = ''
                        thumbs = entry.get('thumbnails', [])
                        if thumbs:
                            thumb_url = thumbs[-1].get('url') or thumbs[0].get('url', '')
                        elif v_id:
                            thumb_url = f'https://i.ytimg.com/vi/{v_id}/hqdefault.jpg'

                        videos.append({
                            'id': v_id,
                            'title': v_title,
                            'url': entry.get('url') or f'https://www.youtube.com/watch?v={v_id}',
                            'view_count': int(v_views),
                            'timestamp': v_timestamp,
                            'date': v_date_str,
                            'duration_seconds': v_duration,
                            'duration_formatted': self.format_duration(v_duration),
                            'thumbnail': thumb_url,
                            'description': entry.get('description') or '',
                        })
        except Exception as e:
            logger.error(f'Lỗi khi lấy danh sách video: {e}')

        # Bổ sung ngày giờ đăng chính xác (timestamp & publish_time_vn)
        need_ts = [v for v in videos if not v.get('timestamp') and v.get('id')]
        if need_ts:
            # 1. Nếu có API Key, truy vấn batch YouTube Data API v3 (siêu tốc ~0.2s)
            if api_key and api_key.strip():
                try:
                    for i in range(0, len(need_ts), 50):
                        batch = need_ts[i:i+50]
                        v_ids = [v['id'] for v in batch]
                        api_url = f"https://www.googleapis.com/youtube/v3/videos?part=snippet,statistics&id={','.join(v_ids)}&key={api_key.strip()}"
                        api_res = requests.get(api_url, timeout=8).json()
                        items_map = {item['id']: item for item in api_res.get('items', [])}
                        for v in batch:
                            item = items_map.get(v['id'])
                            if item:
                                pub_at = item.get('snippet', {}).get('publishedAt')
                                if pub_at:
                                    dt = datetime.datetime.fromisoformat(pub_at.replace('Z', '+00:00'))
                                    v['timestamp'] = dt.timestamp()
                                    dt_vn = dt.astimezone(datetime.timezone(datetime.timedelta(hours=7)))
                                    v['date'] = dt_vn.strftime('%d/%m/%Y')
                                    v['publish_time_vn'] = dt_vn.strftime('%d/%m/%Y %H:%M')
                                stats_data = item.get('statistics', {})
                                if stats_data.get('viewCount'):
                                    v['view_count'] = int(stats_data['viewCount'])
                except Exception as ex:
                    logger.warning(f"Lỗi lấy video datetime qua API: {ex}")

            # 2. Với các video còn thiếu timestamp, cào siêu tốc qua ThreadPoolExecutor
            still_need = [v for v in need_ts if not v.get('timestamp')]
            if still_need:
                session = requests.Session()
                session.headers.update({
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                })

                def _fetch_single_ts(v):
                    vid = v.get('id')
                    try:
                        r = session.get(f"https://www.youtube.com/watch?v={vid}", timeout=6)
                        idx = r.text.find('"publishDate":"')
                        if idx != -1:
                            date_str = r.text[idx + 15 : idx + 45].split('"')[0]
                            dt = datetime.datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                            dt_vn = dt.astimezone(datetime.timezone(datetime.timedelta(hours=7)))
                            return vid, dt.timestamp(), dt_vn.strftime('%d/%m/%Y'), dt_vn.strftime('%d/%m/%Y %H:%M')
                        else:
                            m = re.search(r'itemprop="uploadDate"\s+content="([^"]+)"', r.text)
                            if m:
                                dt = datetime.datetime.fromisoformat(m.group(1).replace('Z', '+00:00'))
                                dt_vn = dt.astimezone(datetime.timezone(datetime.timedelta(hours=7)))
                                return vid, dt.timestamp(), dt_vn.strftime('%d/%m/%Y'), dt_vn.strftime('%d/%m/%Y %H:%M')
                    except Exception:
                        pass
                    return vid, None, '', ''

                with ThreadPoolExecutor(max_workers=min(10, len(still_need))) as executor:
                    ts_results = list(executor.map(_fetch_single_ts, still_need))
                    ts_dict = {vid: (ts, d_str, dt_vn_str) for vid, ts, d_str, dt_vn_str in ts_results if ts}
                    for v in still_need:
                        if v['id'] in ts_dict:
                            ts, d_str, dt_vn_str = ts_dict[v['id']]
                            v['timestamp'] = ts
                            v['date'] = d_str
                            v['publish_time_vn'] = dt_vn_str

        # Đảm bảo các video đã có timestamp cũng có publish_time_vn
        for v in videos:
            if v.get('timestamp') and not v.get('publish_time_vn'):
                try:
                    dt_vn = datetime.datetime.fromtimestamp(v['timestamp'], tz=datetime.timezone(datetime.timedelta(hours=7)))
                    v['publish_time_vn'] = dt_vn.strftime('%d/%m/%Y %H:%M')
                    if not v.get('date'):
                        v['date'] = dt_vn.strftime('%d/%m/%Y')
                except Exception:
                    pass

        stats = self.compute_performance_metrics(videos, channel_meta.get('subscriber_count', 0))

        return {
            'channel': channel_meta,
            'videos': videos,
            'stats': stats
        }

    def format_duration(self, seconds: Optional[int]) -> str:
        if not seconds:
            return '00:00'
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f'{h:02d}:{m:02d}:{s:02d}'
        return f'{m:02d}:{s:02d}'

    def compute_performance_metrics(self, videos: List[Dict[str, Any]], subscriber_count: int) -> Dict[str, Any]:
        if not videos:
            return {
                'total_sample_videos': 0,
                'avg_views': 0,
                'median_views': 0,
                'max_views': 0,
                'min_views': 0,
                'views_to_subs_ratio': 0,
                'upload_frequency_days': 0,
                'upload_cadence_str': 'Chưa đủ dữ liệu',
                'outlier_count': 0,
                'outliers': []
            }

        views_list = [v['view_count'] for v in videos if v.get('view_count') is not None]
        if not views_list:
            views_list = [0]

        avg_views = int(statistics.mean(views_list))
        median_views = int(statistics.median(views_list))
        max_views = max(views_list)
        min_views = min(views_list)

        views_to_subs_ratio = 0.0
        if subscriber_count > 0:
            views_to_subs_ratio = round((avg_views / subscriber_count) * 100, 2)

        outlier_threshold = max(avg_views * 1.6, median_views * 1.8)
        outliers = []
        for v in videos:
            if v['view_count'] >= outlier_threshold and v['view_count'] > 500:
                outliers.append({
                    'id': v['id'],
                    'title': v['title'],
                    'view_count': v['view_count'],
                    'thumbnail': v['thumbnail'],
                    'date': v['date'],
                    'multiplier': round(v['view_count'] / max(avg_views, 1), 1)
                })

        outliers.sort(key=lambda x: x['view_count'], reverse=True)

        timestamps = [v['timestamp'] for v in videos if v.get('timestamp')]
        upload_freq_days = 0.0
        upload_cadence_str = 'Chưa xác định'
        if len(timestamps) >= 2:
            timestamps.sort(reverse=True)
            diffs = [(timestamps[i] - timestamps[i+1]) / 86400.0 for i in range(len(timestamps)-1)]
            if diffs:
                upload_freq_days = round(statistics.mean(diffs), 1)
                if upload_freq_days < 1.5:
                    upload_cadence_str = 'Khoảng 1 video / ngày'
                elif upload_freq_days <= 3.5:
                    upload_cadence_str = f'Khoảng 2-3 video / tuần (Mỗi {upload_freq_days:.1f} ngày)'
                elif upload_freq_days <= 7.5:
                    upload_cadence_str = f'Khoảng 1 video / tuần (Mỗi {upload_freq_days:.1f} ngày)'
                else:
                    upload_cadence_str = f'Mỗi {upload_freq_days:.0f} ngày / video'

        return {
            'total_sample_videos': len(videos),
            'avg_views': avg_views,
            'median_views': median_views,
            'max_views': max_views,
            'min_views': min_views,
            'views_to_subs_ratio': views_to_subs_ratio,
            'upload_frequency_days': upload_freq_days,
            'upload_cadence_str': upload_cadence_str,
            'outlier_count': len(outliers),
            'outliers': outliers[:6]
        }
