import re
import datetime
import requests
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Optional
import yt_dlp

logger = logging.getLogger(__name__)

VN_TZ = datetime.timezone(datetime.timedelta(hours=7))
WEEKDAYS_VN = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ Nhật"]

class PublishTimeService:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'vi,en-US;q=0.9,en;q=0.8'
        })

    def clean_channel_id(self, raw_input: str) -> str:
        """Chuẩn hóa Channel ID hoặc trích xuất từ link / handle."""
        val = raw_input.strip()
        if not val:
            raise ValueError("Vui lòng nhập Channel ID (bắt đầu bằng UC...) hoặc đường dẫn kênh.")
        
        val = val.split('?')[0].rstrip('/')

        if re.match(r'^UC[\w-]{22}$', val):
            return val
        
        match_uc = re.search(r'/channel/(UC[\w-]{22})', val)
        if match_uc:
            return match_uc.group(1)

        return val

    def get_publish_times(
        self,
        channel_input: str,
        api_key: Optional[str] = None,
        limit: int = 50
    ) -> Dict[str, Any]:
        cleaned_id = self.clean_channel_id(channel_input)
        
        # 1. Nếu người dùng cung cấp API Key
        if api_key and api_key.strip():
            try:
                return self._fetch_via_youtube_api(cleaned_id, api_key.strip(), limit)
            except Exception as e:
                logger.warning(f"Lỗi YouTube API: {e}. Đang chuyển sang Free Engine...")
        
        # 2. Free Engine (Không cần API Key)
        return self._fetch_via_free_engine(cleaned_id, limit)

    def parse_iso_duration(self, dur_str: str) -> int:
        if not dur_str:
            return 0
        m = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', dur_str)
        if not m:
            return 0
        h = int(m.group(1) or 0)
        minute = int(m.group(2) or 0)
        s = int(m.group(3) or 0)
        return h * 3600 + minute * 60 + s

    def _fetch_video_datetime(self, video_id: str) -> Optional[datetime.datetime]:
        """Lấy ngày giờ đăng chính xác từ thẻ meta của video."""
        url = f"https://www.youtube.com/watch?v={video_id}"
        try:
            res = self.session.get(url, timeout=6)
            if res.status_code == 200:
                # Tìm itemprop="uploadDate" hoặc "publishDate"
                m = re.search(r'itemprop="uploadDate"\s+content="([^"]+)"', res.text)
                if not m:
                    m = re.search(r'"publishDate":"([^"]+)"', res.text)
                if m:
                    date_str = m.group(1)
                    dt = datetime.datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    return dt.astimezone(VN_TZ)
        except Exception as e:
            logger.debug(f"Không lấy được datetime của {video_id}: {e}")
        return None

    def _fetch_via_free_engine(self, channel_input: str, limit: int = 50) -> Dict[str, Any]:
        """Sử dụng playlist uploads UU... hoặc /videos + đa luồng để lấy datetime."""
        target_url = channel_input
        if channel_input.startswith("UC") and len(channel_input) == 24:
            # Uploads playlist UU...
            target_url = f"https://www.youtube.com/playlist?list=UU{channel_input[2:]}"
        elif channel_input.startswith("@"):
            target_url = f"https://www.youtube.com/{channel_input}/videos"
        elif not channel_input.startswith("http"):
            target_url = f"https://www.youtube.com/channel/{channel_input}/videos"

        ydl_opts = {
            'quiet': True,
            'skip_download': True,
            'no_warnings': True,
            'extract_flat': True,
            'playlist_items': f"1-{limit}",
            'socket_timeout': 15,
        }

        channel_title = "YouTube Channel"
        channel_id = channel_input
        raw_items = []

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            res = ydl.extract_info(target_url, download=False)
            if not res:
                # Fallback thử URL /videos
                fallback_url = f"https://www.youtube.com/channel/{channel_input}/videos"
                res = ydl.extract_info(fallback_url, download=False)
            
            if not res:
                raise ValueError("Không tìm thấy kênh YouTube hoặc danh sách video trống.")

            channel_title = res.get("channel") or res.get("uploader") or res.get("title", "").replace(" - Videos", "")
            channel_id = res.get("channel_id") or channel_id

            entries = res.get("entries", []) or []
            for e in entries:
                if e and e.get("id"):
                    v_title = e.get("title", "Video")
                    v_dur = e.get("duration") or 0
                    if (0 < v_dur < 180) or ("#shorts" in v_title.lower()) or ("#short" in v_title.lower()) or ("#쇼츠" in v_title.lower()):
                        continue
                    raw_items.append({
                        "video_id": e.get("id"),
                        "title": v_title,
                        "views": int(e.get("view_count") or 0),
                        "timestamp": e.get("timestamp")
                    })

        # Lấy datetime chính xác cho từng video bằng ThreadPoolExecutor (max 10 luồng)
        def process_item(item):
            v_id = item["video_id"]
            dt_vn = None
            if item.get("timestamp"):
                dt_vn = datetime.datetime.fromtimestamp(item["timestamp"], tz=VN_TZ)
            else:
                dt_vn = self._fetch_video_datetime(v_id)
            
            return item, dt_vn

        rows = []
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(process_item, raw_items))

        counter = 1
        for item, dt_vn in results:
            date_vn = dt_vn.strftime("%d/%m/%Y") if dt_vn else "Chưa rõ"
            time_vn = dt_vn.strftime("%H:%M:%S") if dt_vn else "Chưa rõ"
            datetime_vn = dt_vn.strftime("%d/%m/%Y %H:%M:%S") if dt_vn else "Chưa rõ"
            weekday_vn = WEEKDAYS_VN[dt_vn.weekday()] if dt_vn else ""
            url = f"https://www.youtube.com/watch?v={item['video_id']}"

            rows.append({
                "stt": counter,
                "video_id": item["video_id"],
                "title": item["title"],
                "date_vn": date_vn,
                "time_vn": time_vn,
                "datetime_vn": datetime_vn,
                "weekday_vn": weekday_vn,
                "publish_date": date_vn,
                "publish_time": time_vn,
                "publish_datetime": datetime_vn,
                "publish_weekday": weekday_vn,
                "views": item["views"],
                "view_count": item["views"],
                "url": url,
                "hour_vn": dt_vn.hour if dt_vn else None
            })
            counter += 1

        return self._format_response(channel_id, channel_title, rows, mode="Free Engine (No API Key Required)")

    def _fetch_via_youtube_api(self, channel_id: str, api_key: str, limit: int = 50) -> Dict[str, Any]:
        """Sử dụng YouTube Data API v3 chính thức giống Google Apps Script."""
        uploads_playlist_id = "UU" + channel_id[2:] if (channel_id.startswith("UC") and len(channel_id) == 24) else ""
        channel_title = "YouTube Channel"

        # Nếu không phải dạng UC... chuẩn 24 ký tự, giải quyết qua API
        if not (channel_id.startswith("UC") and len(channel_id) == 24):
            clean_name = channel_id.lstrip("@").strip()
            try:
                # 1. Thử tìm kiếm theo forHandle
                ch_url = f"https://www.googleapis.com/youtube/v3/channels?part=snippet,contentDetails&forHandle={clean_name}&key={api_key}"
                ch_res = self.session.get(ch_url, timeout=10).json()
                if ch_res.get("items"):
                    ch_item = ch_res["items"][0]
                    channel_id = ch_item.get("id", channel_id)
                    channel_title = ch_item.get("snippet", {}).get("title", channel_title)
                    uploads_playlist_id = ch_item.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads", "")
                else:
                    # 2. Thử search kênh
                    s_url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&type=channel&q={clean_name}&key={api_key}"
                    s_res = self.session.get(s_url, timeout=10).json()
                    if s_res.get("items"):
                        c_id = s_res["items"][0]["snippet"]["channelId"]
                        ch_url2 = f"https://www.googleapis.com/youtube/v3/channels?part=snippet,contentDetails&id={c_id}&key={api_key}"
                        ch_res2 = self.session.get(ch_url2, timeout=10).json()
                        if ch_res2.get("items"):
                            ch_item = ch_res2["items"][0]
                            channel_id = ch_item.get("id", c_id)
                            channel_title = ch_item.get("snippet", {}).get("title", channel_title)
                            uploads_playlist_id = ch_item.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads", "")
            except Exception as e:
                logger.warning(f"Lỗi phân giải channel id từ handle: {e}")

        if not uploads_playlist_id and channel_id.startswith("UC"):
            uploads_playlist_id = "UU" + channel_id[2:]

        if channel_title == "YouTube Channel" and channel_id.startswith("UC"):
            try:
                ch_url = f"https://www.googleapis.com/youtube/v3/channels?part=snippet,contentDetails&id={channel_id}&key={api_key}"
                ch_res = self.session.get(ch_url, timeout=10).json()
                if ch_res.get("items"):
                    ch_item = ch_res["items"][0]
                    channel_title = ch_item.get("snippet", {}).get("title", channel_title)
                    if not uploads_playlist_id:
                        uploads_playlist_id = ch_item.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads", "")
            except Exception as e:
                logger.warning(f"Lỗi truy vấn channels API: {e}")

        video_ids = []
        next_page_token = ""
        while len(video_ids) < limit:
            batch_size = min(50, limit - len(video_ids))
            pl_url = f"https://www.googleapis.com/youtube/v3/playlistItems?part=contentDetails&playlistId={uploads_playlist_id}&maxResults={batch_size}&key={api_key}"
            if next_page_token:
                pl_url += f"&pageToken={next_page_token}"
            
            res = self.session.get(pl_url, timeout=12).json()
            if "error" in res:
                raise ValueError(f"Lỗi YouTube API: {res['error'].get('message')}")
            
            items = res.get("items", [])
            for item in items:
                v_id = item.get("contentDetails", {}).get("videoId")
                if v_id:
                    video_ids.append(v_id)
            
            next_page_token = res.get("nextPageToken")
            if not next_page_token or not items:
                break

        rows = []
        counter = 1
        for i in range(0, len(video_ids), 50):
            batch = video_ids[i:i+50]
            v_url = f"https://www.googleapis.com/youtube/v3/videos?part=snippet,contentDetails,statistics&id={','.join(batch)}&key={api_key}"
            v_res = self.session.get(v_url, timeout=12).json()
            if "error" in v_res:
                raise ValueError(f"Lỗi YouTube API Videos: {v_res['error'].get('message')}")

            for v in v_res.get("items", []):
                vid = v.get("id")
                title = v.get("snippet", {}).get("title", "")
                dur_iso = v.get("contentDetails", {}).get("duration", "")
                dur_sec = self.parse_iso_duration(dur_iso)
                
                # Loại bỏ video Shorts (< 180s hoặc có tag shorts)
                if (0 < dur_sec < 180) or ("#shorts" in title.lower()) or ("#short" in title.lower()) or ("#쇼츠" in title.lower()):
                    continue

                pub_at = v.get("snippet", {}).get("publishedAt", "")
                views = int(v.get("statistics", {}).get("viewCount", 0))

                dt_vn = None
                if pub_at:
                    try:
                        dt_utc = datetime.datetime.fromisoformat(pub_at.replace("Z", "+00:00"))
                        dt_vn = dt_utc.astimezone(VN_TZ)
                    except Exception:
                        dt_vn = None

                date_vn = dt_vn.strftime("%d/%m/%Y") if dt_vn else ""
                time_vn = dt_vn.strftime("%H:%M:%S") if dt_vn else ""
                datetime_vn = dt_vn.strftime("%d/%m/%Y %H:%M:%S") if dt_vn else ""
                weekday_vn = WEEKDAYS_VN[dt_vn.weekday()] if dt_vn else ""
                url = f"https://www.youtube.com/watch?v={vid}"

                rows.append({
                    "stt": counter,
                    "video_id": vid,
                    "title": title,
                    "date_vn": date_vn,
                    "time_vn": time_vn,
                    "datetime_vn": datetime_vn,
                    "weekday_vn": weekday_vn,
                    "publish_date": date_vn,
                    "publish_time": time_vn,
                    "publish_datetime": datetime_vn,
                    "publish_weekday": weekday_vn,
                    "views": views,
                    "view_count": views,
                    "url": url,
                    "hour_vn": dt_vn.hour if dt_vn else None
                })
                counter += 1

        return self._format_response(channel_id, channel_title, rows, mode="YouTube Data API v3")

    def _format_response(self, channel_id: str, channel_title: str, rows: List[Dict[str, Any]], mode: str) -> Dict[str, Any]:
        tsv_headers = ["STT", "Video ID", "Tiêu đề", "Ngày đăng (VN)", "Giờ đăng (VN)", "Ngày + giờ đăng", "Thứ", "Lượt xem", "URL"]
        tsv_lines = ["\t".join(tsv_headers)]
        csv_lines = [",".join([f'"{h}"' for h in tsv_headers])]

        for r in rows:
            clean_title = r["title"].replace("\t", " ").replace("\n", " ").replace('"', '""')
            tsv_row = [
                str(r["stt"]),
                r["video_id"],
                clean_title,
                r["date_vn"],
                r["time_vn"],
                r["datetime_vn"],
                r["weekday_vn"],
                str(r["views"]),
                r["url"]
            ]
            tsv_lines.append("\t".join(tsv_row))
            
            csv_row = [
                str(r["stt"]),
                f'"{r["video_id"]}"',
                f'"{clean_title}"',
                f'"{r["date_vn"]}"',
                f'"{r["time_vn"]}"',
                f'"{r["datetime_vn"]}"',
                f'"{r["weekday_vn"]}"',
                str(r["views"]),
                f'"{r["url"]}"'
            ]
            csv_lines.append(",".join(csv_row))

        tsv_data = "\n".join(tsv_lines)
        csv_data = "\ufeff" + "\n".join(csv_lines)

        hour_counts = {}
        for r in rows:
            h = r.get("hour_vn")
            if h is not None:
                hour_counts[h] = hour_counts.get(h, 0) + 1
        
        most_common_hour_str = "Chưa đủ dữ liệu"
        if hour_counts:
            best_h = max(hour_counts, key=hour_counts.get)
            most_common_hour_str = f"Khung {best_h:02d}:00 - {best_h:02d}:59 ({hour_counts[best_h]} video)"

        return {
            "success": True,
            "channel_id": channel_id,
            "channel_title": channel_title,
            "engine_mode": mode,
            "extraction_mode": mode,
            "timezone": "Asia/Ho_Chi_Minh (UTC+7)",
            "total_videos": len(rows),
            "most_common_publish_hour_vn": most_common_hour_str,
            "videos": rows,
            "tsv_data": tsv_data,
            "tsv_content": tsv_data,
            "csv_data": csv_data,
            "csv_content": csv_data
        }
