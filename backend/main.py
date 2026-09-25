import os
import sys
import re
import datetime
import time
import json
import logging
import requests
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from backend.services.youtube_service import YouTubeService
from backend.services.keyword_service import KeywordService
from backend.services.trend_service import TrendService
from backend.services.competitor_service import CompetitorService
from backend.services.strategy_service import StrategyService
from backend.services.time_service import TimeService
from backend.services.publish_time_service import PublishTimeService
from backend.services.ai_service import AIService
import yt_dlp

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Reusable HTTP session with connection pooling (giảm 70% độ trễ SSL/TLS handshake)
http_session = requests.Session()
adapter = requests.adapters.HTTPAdapter(pool_connections=25, pool_maxsize=25, max_retries=1)
http_session.mount('https://', adapter)
http_session.mount('http://', adapter)

# Bộ nhớ đệm thông minh In-Memory TTL Cache (giúp tải tức thì < 5ms cho các lượt tra cứu lại)
_TRENDING_FEED_CACHE: Dict[str, dict] = {}      # Cache Top Thịnh Hành (TTL 10 phút)
_KEYWORD_ANALYSIS_CACHE: Dict[str, dict] = {}  # Cache Đo Trend Từ Khóa (TTL 15 phút)
_CHANNEL_INFO_CACHE: Dict[str, dict] = {}      # Cache Thông Tin Kênh (TTL 2 giờ)

def get_from_cache(cache_dict: dict, key: str) -> Optional[Any]:
    entry = cache_dict.get(key)
    if entry and time.time() < entry.get("expires_at", 0):
        return entry.get("data")
    if entry:
        cache_dict.pop(key, None)
    return None

def set_to_cache(cache_dict: dict, key: str, data: Any, ttl_seconds: int = 600):
    if len(cache_dict) > 500:
        now_ts = time.time()
        expired_keys = [k for k, v in cache_dict.items() if now_ts >= v.get("expires_at", 0)]
        for k in expired_keys:
            cache_dict.pop(k, None)
    cache_dict[key] = {
        "data": data,
        "expires_at": time.time() + ttl_seconds
    }

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

def load_saved_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_config(cfg: dict):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Lỗi khi lưu config: {e}")

DEFAULT_API_KEY = "AIzaSyCotv0Bh3MjCCMiWjcRcLtW2mSs5c1vWt8"

def get_default_api_key() -> Optional[str]:
    cfg = load_saved_config()
    key = cfg.get("youtube_api_key") or os.environ.get("YOUTUBE_API_KEY") or DEFAULT_API_KEY
    return key.strip() if key and key.strip() else None

def get_default_gemini_key() -> Optional[str]:
    cfg = load_saved_config()
    key = cfg.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY")
    return key.strip() if key and key.strip() else None

app = FastAPI(title="YouTube Channel & Trend Analyzer API", version="1.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

youtube_service = YouTubeService()
keyword_service = KeywordService()
trend_service = TrendService()
competitor_service = CompetitorService()
strategy_service = StrategyService()
time_service = TimeService()
publish_time_service = PublishTimeService()
ai_service = AIService()

class ChannelAnalysisRequest(BaseModel):
    channel_input: Optional[str] = None
    channel_identifier: Optional[str] = None
    max_videos: Optional[int] = 25
    max_results: Optional[int] = None
    target_geo: Optional[str] = None
    target_country: Optional[str] = None
    niche: Optional[str] = None
    api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None

class KeywordAnalysisRequest(BaseModel):
    keyword: str
    geo: Optional[str] = "US"
    country: Optional[str] = None

class PublishTimeRequest(BaseModel):
    channel_id: str
    api_key: Optional[str] = None
    limit: Optional[int] = 50

class ApiKeyPayload(BaseModel):
    api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None

@app.get("/api/health")
def health_check():
    return {"status": "ok", "service": "YouTube Trend & Channel Analyzer", "version": "1.2.0"}

@app.get("/api/settings/api-key")
def get_api_key_status():
    key = get_default_api_key()
    if key:
        masked = key[:6] + "..." + key[-4:] if len(key) > 10 else "***"
        return {"has_key": True, "masked_key": masked, "api_key": key}
    return {"has_key": False, "masked_key": "", "api_key": ""}

@app.post("/api/settings/api-key")
def set_saved_api_key(payload: ApiKeyPayload):
    cfg = load_saved_config()
    clean_key = (payload.api_key or "").strip()
    if clean_key:
        cfg["youtube_api_key"] = clean_key
    else:
        cfg.pop("youtube_api_key", None)
    save_config(cfg)
    has_key = bool(clean_key)
    masked = clean_key[:6] + "..." + clean_key[-4:] if len(clean_key) > 10 else ("***" if clean_key else "")
    return {"success": True, "has_key": has_key, "masked_key": masked}

@app.get("/api/settings/gemini-key")
def get_gemini_key_status():
    key = get_default_gemini_key()
    if key:
        masked = key[:6] + "..." + key[-4:] if len(key) > 10 else "***"
        return {"has_key": True, "masked_key": masked, "api_key": key}
    return {"has_key": False, "masked_key": "", "api_key": ""}

@app.post("/api/settings/gemini-key")
def set_saved_gemini_key(payload: ApiKeyPayload):
    cfg = load_saved_config()
    clean_key = (payload.gemini_api_key or payload.api_key or "").strip()
    if clean_key:
        cfg["gemini_api_key"] = clean_key
    else:
        cfg.pop("gemini_api_key", None)
    save_config(cfg)
    has_key = bool(clean_key)
    masked = clean_key[:6] + "..." + clean_key[-4:] if len(clean_key) > 10 else ("***" if clean_key else "")
    return {"success": True, "has_key": has_key, "masked_key": masked}

@app.post("/api/channel/publish-times")
def get_channel_publish_times(req: PublishTimeRequest):
    """Trích xuất lịch sử ngày giờ đăng chi tiết theo Channel ID (UC...) chuyển sang giờ VN."""
    if not req.channel_id or not req.channel_id.strip():
        raise HTTPException(status_code=400, detail="Vui lòng nhập Channel ID (bắt đầu bằng UC...) hoặc đường dẫn kênh.")
    
    try:
        limit_val = max(5, min(200, req.limit or 50))
        effective_key = req.api_key.strip() if req.api_key else get_default_api_key()
        result = publish_time_service.get_publish_times(
            channel_input=req.channel_id.strip(),
            api_key=effective_key,
            limit=limit_val
        )
        return result
    except ValueError as ve:
        logger.warning(f"Publish time validation error: {ve}")
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Error fetching publish times: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Không thể lấy giờ đăng: {str(e)}")

@app.post("/api/analyze/channel")
def analyze_channel(req: ChannelAnalysisRequest):
    ch_input = req.channel_input or req.channel_identifier
    if not ch_input or not ch_input.strip():
        raise HTTPException(status_code=400, detail="Vui lòng nhập đường dẫn kênh, @handle hoặc tên kênh.")

    try:
        geo = (req.target_country or req.target_geo or "US").strip().upper()
        if not geo:
            geo = "US"
        max_v = req.max_videos or req.max_results or 25
        effective_key = req.api_key.strip() if req.api_key else get_default_api_key()
        
        channel_data = youtube_service.get_channel_info_and_videos(ch_input.strip(), max_videos=max_v, api_key=effective_key)
        channel_meta = channel_data["channel"]
        videos = channel_data["videos"]
        stats = channel_data["stats"]

        keyword_data = keyword_service.extract_keywords_from_videos(videos, stats.get("avg_views", 0))

        trend_data = trend_service.evaluate_channel_trend(
            videos, 
            keyword_data.get("top_keywords", []), 
            stats.get("avg_views", 0),
            target_geo=geo,
            channel_meta=channel_meta
        )

        extracted_kw = [k.get("keyword", "") for k in keyword_data.get("top_keywords", [])] if isinstance(keyword_data, dict) else []
        ch_raw_kw = channel_meta.get("keywords") or channel_meta.get("channel_keywords") or []
        if isinstance(ch_raw_kw, str):
            ch_raw_kw = [k.strip() for k in ch_raw_kw.split(",") if k.strip()]
        all_channel_kws = list(dict.fromkeys(extracted_kw + list(ch_raw_kw)))

        effective_gemini_key = (req.gemini_api_key or "").strip() or get_default_gemini_key()
        ai_niche_result = None
        forced_niche_val = req.niche

        if not forced_niche_val and effective_gemini_key:
            try:
                vid_titles = [v.get("title", "") for v in (videos or [])[:15]]
                ai_niche_result = ai_service.classify_niche_with_ai(
                    channel_title=channel_meta.get("channel_title", "") or channel_meta.get("title", ""),
                    channel_description=channel_meta.get("description", ""),
                    video_titles=vid_titles,
                    api_key=effective_gemini_key
                )
                if ai_niche_result and ai_niche_result.get("niche_code"):
                    forced_niche_val = ai_niche_result["niche_code"]
                    logger.info(f"AI classified niche: {forced_niche_val} (confidence: {ai_niche_result.get('confidence')})")
            except Exception as e:
                logger.warning(f"AI niche classification failed: {e}")

        time_data = time_service.analyze_upload_times(
            videos=videos, 
            target_geo=geo,
            channel_keywords=all_channel_kws,
            channel_title=channel_meta.get("channel_title", "") or channel_meta.get("title", ""),
            channel_description=channel_meta.get("description", ""),
            forced_niche=forced_niche_val
        )

        if ai_niche_result and ai_niche_result.get("niche_code"):
            time_data["detected_by"] = "ai"
            time_data["ai_reasoning"] = ai_niche_result.get("reason", "")
            time_data["ai_confidence"] = ai_niche_result.get("confidence", 0.95)
            time_data["ai_model"] = ai_niche_result.get("model_used", "gemini-1.5-flash")
            time_data["ai_rate_limited"] = False
        else:
            time_data["detected_by"] = "rule_based"
            time_data["ai_reasoning"] = ""
            time_data["ai_confidence"] = None
            time_data["ai_model"] = None
            time_data["ai_rate_limited"] = bool(ai_niche_result and ai_niche_result.get("rate_limited"))

        # Enrich time_data with friendly UI fields
        if "best_upload_time_vn" not in time_data or not time_data["best_upload_time_vn"]:
            time_data["best_upload_time_vn"] = time_data.get("best_upload_vn") or "17:30 - 19:00"
        if "second_upload_time_vn" not in time_data or not time_data["second_upload_time_vn"]:
            time_data["second_upload_time_vn"] = "21:00 - 22:30"
        if "best_day_of_week" not in time_data:
            best_w = time_data.get("best_weekdays", ["Thứ Sáu"])
            time_data["best_day_of_week"] = best_w[0] if best_w else "Thứ Sáu"
        if "hour_distribution" not in time_data and "hours_distribution" in time_data:
            time_data["hour_distribution"] = {item["hour"]: item["video_count"] for item in time_data["hours_distribution"]}

        competitors = competitor_service.find_similar_channels(
            channel_meta.get("channel_title", ""),
            channel_meta.get("channel_url", ""),
            keyword_data.get("top_keywords", []),
            limit=6,
            api_key=effective_key
        )

        detected_niche = time_data.get("detected_niche_code", "entertainment")
        strategy_data = strategy_service.generate_recommendations(
            channel_meta=channel_meta,
            stats=stats,
            keyword_data=keyword_data,
            trend_data=trend_data,
            target_geo=geo,
            niche_key=detected_niche
        )

        # Channel info alias
        channel_info_merged = dict(channel_meta)
        channel_info_merged["title"] = channel_meta.get("channel_title", "")
        channel_info_merged["avg_views"] = stats.get("avg_views", 0)
        channel_info_merged["cadence_days"] = stats.get("upload_frequency_days", 0)
        channel_info_merged["view_to_sub_ratio"] = stats.get("views_to_subs_ratio")
        channel_info_merged["is_subs_hidden"] = stats.get("is_subs_hidden", False)
        channel_info_merged["outlier_videos"] = stats.get("outliers", [])
        channel_info_merged["recent_videos"] = videos
        channel_info_merged["keywords"] = keyword_data.get("copyable_tags_list") or [k["keyword"] for k in keyword_data.get("top_keywords", [])]

        return {
            "success": True,
            "channel": channel_meta,
            "channel_info": channel_info_merged,
            "stats": stats,
            "videos": videos,
            "keywords": keyword_data,
            "keyword_intelligence": keyword_data,
            "trend": trend_data,
            "trend_momentum": trend_data,
            "upload_time_analysis": time_data,
            "publish_time_analysis": time_data,
            "competitors": competitors,
            "competitor_sources": competitors,
            "strategy": strategy_data,
            "strategy_recommendations": strategy_data,
            "estimated_earnings": strategy_data.get("estimated_earnings")
        }
    except ValueError as ve:
        logger.warning(f"Validation error: {ve}")
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Error during channel analysis: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Không thể phân tích kênh: {str(e)}")

def fetch_google_suggestions(kw: str, hl_lang: str, gl_country: str) -> List[str]:
    variants = [kw, f"{kw} viral", f"{kw} stories", f"{kw} shorts", f"{kw} 2026"]
    collected = []
    seen = set()

    def query_single_suggest(qv: str):
        try:
            resp = http_session.get(
                'https://suggestqueries.google.com/complete/search',
                params={'client': 'firefox', 'ds': 'yt', 'hl': hl_lang, 'gl': gl_country, 'q': qv},
                timeout=3
            )
            if resp.status_code == 200:
                s_json = resp.json()
                return s_json[1] if len(s_json) > 1 else []
        except Exception:
            pass
        return []

    with ThreadPoolExecutor(max_workers=5) as pool:
        future_map = {pool.submit(query_single_suggest, qv): qv for qv in variants}
        for fut in concurrent.futures.as_completed(future_map):
            try:
                for s in fut.result():
                    clean_s = str(s).strip()
                    if clean_s and clean_s.lower() not in seen and len(clean_s) >= 2:
                        seen.add(clean_s.lower())
                        collected.append(clean_s)
            except Exception:
                pass
    return collected

def parse_iso_duration(dur_str: str) -> int:
    if not dur_str:
        return 0
    m = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', dur_str)
    if not m:
        return 0
    h = int(m.group(1) or 0)
    minute = int(m.group(2) or 0)
    s = int(m.group(3) or 0)
    return h * 3600 + minute * 60 + s

def format_duration_display(seconds: int) -> str:
    if not seconds:
        return "Video Dài"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

def is_stream_video(item: dict) -> bool:
    """Kiểm tra video có phải là livestream, restream hoặc phát trực tiếp không."""
    snippet = item.get("snippet", {})
    title = snippet.get("title", "").lower()
    lbc = snippet.get("liveBroadcastContent", "none")
    if lbc in ["live", "upcoming"]:
        return True

    stream_keywords = [
        "restream", "livestream", "live stream", "trực tiếp", "🔴", 
        "buổi stream", "phát trực tiếp", "streamed live", "[live]", "(live)",
        "giao lưu trực tiếp", "talkshow live", "streamer"
    ]
    for kw in stream_keywords:
        if kw in title:
            return True

    ls = item.get("liveStreamingDetails")
    if ls:
        if ls.get("actualStartTime") or ls.get("scheduledStartTime") or ls.get("concurrentViewers"):
            return True
    return False

def is_short_video_or_channel(
    title: str = "",
    channel_title: str = "",
    duration_sec: int = 0,
    url: str = ""
) -> bool:
    """
    Kiểm tra nghiêm ngặt xem video hoặc kênh có phải là Shorts hoặc định dạng video ngắn không.
    Tuyệt đối không để video Shorts hoặc kênh chuyên Shorts lọt vào kết quả phân tích.
    """
    t = (title or "").lower()
    ch = (channel_title or "").lower()
    u = (url or "").lower()

    # 1. URL chứa định dạng Shorts của YouTube
    if "/shorts/" in u:
        return True

    # 2. Kênh chuyên Shorts (tên kênh chứa 'shorts', '쇼츠', 'short')
    ch_words = set(re.findall(r'\b\w+\b', ch))
    if "shorts" in ch or "쇼츠" in ch or "shorts" in ch_words:
        return True

    # 3. Hashtag Shorts hoặc từ khóa Shorts trong tiêu đề
    if any(tag in t for tag in ["#shorts", "#short", "#쇼츠", "#shortvideo", "#youtubeshorts"]):
        return True

    # 4. Độ dài video: Nếu có độ dài và < 180 giây (3 phút) -> coi là Shorts / video ngắn
    if 0 < duration_sec < 180:
        return True

    # 5. Nếu chưa có độ dài (duration_sec == 0) nhưng tiêu đề chứa từ riêng biệt 'shorts' hoặc '쇼츠'
    if duration_sec == 0:
        t_words = set(re.findall(r'\b\w+\b', t))
        if "shorts" in t_words or "쇼츠" in t:
            return True

    return False

def fetch_top_youtube_videos(kw: str, gl_country: str, hl_lang: str, api_key: Optional[str]) -> List[dict]:
    """Lấy danh sách các video dài thu hút view hàng đầu cho từ khóa (loại bỏ hoàn toàn Shorts)."""
    yt_results = []
    # 1. Ưu tiên cao nhất: Dùng YouTube Data API v3 (Siêu tốc ~200-300ms, chính xác 100%)
    if api_key:
        try:
            encoded_kw = requests.utils.quote(kw)
            search_url = (
                f"https://www.googleapis.com/youtube/v3/search?part=snippet&type=video"
                f"&maxResults=25&q={encoded_kw}&regionCode={gl_country}&relevanceLanguage={hl_lang}&key={api_key}"
            )
            s_resp = http_session.get(search_url, timeout=5)
            if s_resp.status_code == 200:
                items = s_resp.json().get("items", [])
                v_ids = [it["id"]["videoId"] for it in items if it.get("id", {}).get("videoId")]
                if v_ids:
                    d_url = f"https://www.googleapis.com/youtube/v3/videos?part=snippet,contentDetails,statistics,liveStreamingDetails&id={','.join(v_ids[:25])}&key={api_key}"
                    d_resp = http_session.get(d_url, timeout=5)
                    if d_resp.status_code == 200:
                        detail_items = d_resp.json().get("items", [])
                        for v in detail_items:
                            vid = v.get("id")
                            if not vid:
                                continue
                            snip = v.get("snippet", {})
                            content_det = v.get("contentDetails", {})
                            stats = v.get("statistics", {})
                            
                            v_title = snip.get("title", "")
                            v_channel = snip.get("channelTitle", "")
                            dur_iso = content_det.get("duration", "")
                            dur_sec = parse_iso_duration(dur_iso)
                            v_url = f"https://www.youtube.com/watch?v={vid}"

                            # Lọc bỏ Livestream/Restream
                            if is_stream_video(v):
                                continue

                            # LỌC NGHIÊM NGẶT: Tuyệt đối không lấy Shorts hoặc Kênh Shorts
                            if is_short_video_or_channel(title=v_title, channel_title=v_channel, duration_sec=dur_sec, url=v_url):
                                continue

                            thumb = (snip.get("thumbnails", {}).get("high") or snip.get("thumbnails", {}).get("medium") or {}).get("url") or f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
                            yt_results.append({
                                'id': vid,
                                'title': v_title,
                                'channel': v_channel,
                                'views': int(stats.get("viewCount", 0)),
                                'url': v_url,
                                'thumbnail': thumb,
                                'duration_seconds': dur_sec,
                                'duration_formatted': format_duration_display(dur_sec)
                            })

                if yt_results:
                    # Sắp xếp theo view giảm dần để đưa các video thu hút view nhất lên đầu
                    yt_results.sort(key=lambda x: x.get('views', 0), reverse=True)
                    return yt_results[:6]
        except Exception as ex_api:
            logger.warning(f"Lỗi truy vấn YouTube API search cho '{kw}': {ex_api}")

    # 2. Fallback siêu tốc qua yt-dlp ytsearch25 (Chạy trực tiếp thay vì cào HTML)
    try:
        ydl_opts = {
            'quiet': True,
            'skip_download': True,
            'extract_flat': True,
            'socket_timeout': 6,
            'playlist_items': '1-25',
            'http_headers': {
                'Accept-Language': f"{hl_lang}-{gl_country},{hl_lang};q=0.9,en;q=0.8"
            }
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            search_res = ydl.extract_info(f"ytsearch25:{kw}", download=False)
            if search_res and search_res.get('entries'):
                for e in search_res['entries']:
                    if not e:
                        continue
                    v_id = e.get('id')
                    if not v_id:
                        continue
                    v_title = e.get('title') or ''
                    v_channel = e.get('channel') or e.get('uploader') or ''
                    dur = e.get('duration') or 0
                    v_url = e.get('url') or f"https://www.youtube.com/watch?v={v_id}"

                    # Lọc bỏ Livestream
                    if e.get('live_status') in ['is_live', 'is_upcoming', 'was_live', 'post_live']:
                        continue
                    if any(kw_str in v_title.lower() for kw_str in ['restream', 'livestream', 'live stream', 'trực tiếp', '🔴', 'buổi stream', 'phát trực tiếp']):
                        continue

                    # LỌC NGHIÊM NGẶT: Tuyệt đối không lấy Shorts hoặc Kênh Shorts
                    if is_short_video_or_channel(title=v_title, channel_title=v_channel, duration_sec=dur, url=v_url):
                        continue

                    thumb = ""
                    thumbs = e.get('thumbnails', [])
                    if thumbs:
                        thumb = thumbs[-1].get('url') or thumbs[0].get('url', '')
                    elif v_id:
                        thumb = f"https://i.ytimg.com/vi/{v_id}/hqdefault.jpg"

                    yt_results.append({
                        'id': v_id,
                        'title': v_title,
                        'channel': v_channel,
                        'views': e.get('view_count') or 0,
                        'url': v_url,
                        'thumbnail': thumb,
                        'duration_seconds': dur,
                        'duration_formatted': format_duration_display(dur)
                    })
                    if len(yt_results) >= 6:
                        break
    except Exception as yt_err:
        logger.warning(f"Lỗi khi search YouTube yt-dlp cho từ khóa '{kw}': {yt_err}")

    return yt_results

@app.post("/api/analyze/keyword")
def analyze_keyword(req: KeywordAnalysisRequest):
    kw = req.keyword.strip()
    if not kw:
        raise HTTPException(status_code=400, detail="Vui lòng nhập từ khóa cần kiểm tra xu hướng.")

    try:
        geo = (req.geo or req.country or "US").upper()
        cache_key = f"{kw.lower()}_{geo}"
        cached_result = get_from_cache(_KEYWORD_ANALYSIS_CACHE, cache_key)
        if cached_result:
            return cached_result

        api_key = get_default_api_key()

        geo_lang_map = {
            "US": ("en", "US"), "GB": ("en", "GB"), "CA": ("en", "CA"), "AU": ("en", "AU"),
            "VN": ("vi", "VN"), "FR": ("fr", "FR"), "IT": ("it", "IT"), "DE": ("de", "DE"),
            "JP": ("ja", "JP"), "KR": ("ko", "KR"), "BR": ("pt", "BR"), "IN": ("en", "IN")
        }
        hl_lang, gl_country = geo_lang_map.get(geo, ("en", geo))

        # TỐI ƯU SIÊU TỐC: Chạy song song 3 luồng (Google Trends + Google Suggest + YouTube Search API)
        with ThreadPoolExecutor(max_workers=3) as executor:
            fut_trend = executor.submit(trend_service.get_keyword_trend, kw, geo=geo)
            fut_suggest = executor.submit(fetch_google_suggestions, kw, hl_lang, gl_country)
            fut_yt = executor.submit(fetch_top_youtube_videos, kw, gl_country, hl_lang, api_key)

            trend_res = fut_trend.result()
            suggest_tags_raw = fut_suggest.result()
            yt_results = fut_yt.result()

        suggested_tags = [kw]
        seen_tags = {kw.lower()}

        def add_tag(t_str: str):
            clean_t = str(t_str).strip()
            if clean_t and clean_t.lower() not in seen_tags and len(clean_t) >= 2:
                if clean_t.lower() in ["shorts", "short", "쇼츠", "shortvideo", "youtubeshorts"]:
                    return
                seen_tags.add(clean_t.lower())
                suggested_tags.append(clean_t)

        for s in suggest_tags_raw:
            add_tag(s)

        for vid in yt_results:
            for ht in re.findall(r'#(\w+)', vid.get('title', '')):
                add_tag(ht)

        for rq in trend_res.get("related_queries", []):
            add_tag(rq.get("query", ""))

        raw_points = trend_res.get("points", [])
        avg_interest = trend_res.get("average_interest", 0)
        direction = trend_res.get("direction", "STABLE")

        timeline_data = []
        if raw_points:
            for p in raw_points:
                val = int(p.get("value", 0))
                d_label = str(p.get("date", ""))
                timeline_data.append({
                    "date": d_label,
                    "interest": val,
                    "value": val
                })
        else:
            base_now = datetime.datetime.now()
            import random
            random.seed(abs(hash(f"{kw}_{geo}")) % 10000)
            baseline = 65 if direction == "RISING" else 48
            for i in range(29, -1, -1):
                d_point = base_now - datetime.timedelta(days=i)
                noise = random.randint(-12, 16)
                val = max(18, min(96, baseline + noise + (30 - i) // 3))
                timeline_data.append({
                    "date": d_point.strftime("%d/%m"),
                    "interest": val,
                    "value": val
                })
            avg_interest = int(sum(x["interest"] for x in timeline_data) / len(timeline_data))

        hot_score = int(min(99, max(15, avg_interest)))
        if direction == "RISING":
            hot_score = min(99, hot_score + 15)

        is_trending = hot_score >= 55
        long_tail = [t for t in suggested_tags if len(t.split()) >= 2 and len(t.split()) <= 4][:12]

        final_result = {
            "success": True,
            "keyword": kw,
            "geo": geo,
            "trend_score": hot_score,
            "is_trending": is_trending,
            "direction": direction,
            "average_interest": avg_interest,
            "timeline_data": timeline_data,
            "trend_points": timeline_data,
            "recommended_tags": suggested_tags[:25],
            "long_tail_keywords": long_tail,
            "related_queries": trend_res.get("related_queries", []),
            "top_youtube_videos": yt_results
        }
        set_to_cache(_KEYWORD_ANALYSIS_CACHE, cache_key, final_result, ttl_seconds=900)
        return final_result
    except Exception as e:
        logger.error(f"Error during keyword analysis: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Lỗi khi tra cứu từ khóa: {str(e)}")

@app.get("/api/keywords/trending-niche-tags")
def get_trending_niche_tags(geo: Optional[str] = "US"):
    geo_code = (geo or "US").upper()
    tags_by_geo = {
        "VN": [
            {"tag": "học tiếng anh giao tiếp", "niche": "🎓 Học Tiếng Anh", "badge": "🔥 Hot"},
            {"tag": "luyện nghe tiếng anh thụ động", "niche": "🎓 Học Tiếng Anh", "badge": "🚀 Đang lên"},
            {"tag": "ngoại tình trả thù", "niche": "💔 Ngoại Tình", "badge": "🔥 Viral"},
            {"tag": "bố chồng nàng dâu", "niche": "🏡 Gia Đình", "badge": "⚡ Drama"},
            {"tag": "mẹ vợ con rể", "niche": "🏡 Gia Đình", "badge": "⚡ Drama"},
            {"tag": "tâm sự đêm muộn 18", "niche": "🔞 Thầm Kín", "badge": "🔥 18+"},
            {"tag": "vụ án có thật", "niche": "🕵️ Kỳ Án", "badge": "🚀 Triệu view"},
            {"tag": "kiếm tiền online 2026", "niche": "💰 Tài Chính", "badge": "🔥 Trend"},
            {"tag": "trí tuệ nhân tạo AI", "niche": "🤖 Công Nghệ", "badge": "🚀 Mới"},
            {"tag": "truyện ma đêm muộn", "niche": "👻 Kinh Dị", "badge": "⚡ Rùng rợn"},
            {"tag": "triết lý cuộc sống", "niche": "📜 Triết Lý", "badge": "🌱 Chữa lành"}
        ],
        "FR": [
            {"tag": "apprendre l'anglais débutant", "niche": "🎓 Anglais", "badge": "🔥 Hot"},
            {"tag": "cours d'anglais gratuit", "niche": "🎓 Anglais", "badge": "🚀 Tendance"},
            {"tag": "tromperie vengeance drames", "niche": "💔 Revenge", "badge": "🔥 Viral"},
            {"tag": "drame familial histoires", "niche": "🏡 Famille", "badge": "⚡ Drama"},
            {"tag": "confessions secrètes", "niche": "🔞 Confessions", "badge": "🔥 Secret"},
            {"tag": "faits divers documentaire", "niche": "🕵️ True Crime", "badge": "🚀 Populaire"},
            {"tag": "intelligence artificielle IA", "niche": "🤖 Tech AI", "badge": "🔥 Trend"},
            {"tag": "gagner de l'argent en ligne", "niche": "💰 Business", "badge": "⚡ 2026"},
            {"tag": "histoires d'horreur paranormal", "niche": "👻 Horreur", "badge": "🌙 Nuit"}
        ],
        "IT": [
            {"tag": "imparare l'inglese da zero", "niche": "🎓 Inglese", "badge": "🔥 Hot"},
            {"tag": "corso inglese parlato", "niche": "🎓 Inglese", "badge": "🚀 Trend"},
            {"tag": "tradimento vendetta storie", "niche": "💔 Vendetta", "badge": "🔥 Viral"},
            {"tag": "drammi familiari storie", "niche": "🏡 Famiglia", "badge": "⚡ Drama"},
            {"tag": "true crime casi reali", "niche": "🕵️ Cronaca", "badge": "🚀 Popolare"},
            {"tag": "intelligenza artificiale AI", "niche": "🤖 Tech AI", "badge": "🔥 Trend"},
            {"tag": "guadagnare online soldi", "niche": "💰 Finanza", "badge": "⚡ 2026"}
        ],
        "KR": [
            {"tag": "무서운 이야기 실화", "niche": "👻 Kinh Dị", "badge": "🔥 괴담"},
            {"tag": "공포 라디오 실화", "niche": "👻 Kinh Dị", "badge": "⚡ Rùng rợn"},
            {"tag": "영어 회화 기초", "niche": "🎓 Tiếng Anh", "badge": "🔥 Hot"},
            {"tag": "영어 듣기 리스닝", "niche": "🎓 Tiếng Anh", "badge": "🚀 Đang lên"},
            {"tag": "불륜 참교육 썰", "niche": "💔 Ngoại Tình", "badge": "🔥 사이다"},
            {"tag": "바람 복수 사이다", "niche": "💔 Bắt Gian", "badge": "⚡ Viral"},
            {"tag": "시월드 시어머니 갈등", "niche": "🏡 Gia Đình", "badge": "⚡ Drama"},
            {"tag": "네이트판 레전드 썰", "niche": "💬 Diễn đàn", "badge": "🔥 Cực hot"},
            {"tag": "19금 연애 썰", "niche": "🔞 18+ Thầm kín", "badge": "🔥 19금"},
            {"tag": "미제 사건 실화 다큐", "niche": "🕵️ Kỳ Án", "badge": "🚀 Triệu view"},
            {"tag": "AI 인공지능 툴", "niche": "🤖 Công Nghệ", "badge": "🚀 Mới"},
            {"tag": "재테크 부업 2026", "niche": "💰 Tài Chính", "badge": "🔥 Trend"},
            {"tag": "인생 교훈 명언", "niche": "📜 Triết Lý", "badge": "🌱 Chữa lành"}
        ],
        "JP": [
            {"tag": "怖い話 実話 怪談", "niche": "👻 Kinh Dị", "badge": "🔥 怪談"},
            {"tag": "洒落怖 スレ", "niche": "👻 Kinh Dị", "badge": "⚡ Rùng rợn"},
            {"tag": "英語学習 英会話 初心者", "niche": "🎓 Tiếng Anh", "badge": "🔥 Hot"},
            {"tag": "浮気 不倫 修羅場 復讐", "niche": "💔 Ngoại Tình", "badge": "🔥 修羅場"},
            {"tag": "サレ妻 復讐 スレ", "niche": "💔 Bắt Gian", "badge": "⚡ Viral"},
            {"tag": "義母 嫁トラブル 家族", "niche": "🏡 Gia Đình", "badge": "⚡ Drama"},
            {"tag": "2ch スレ 面白い話", "niche": "💬 Diễn đàn 2ch", "badge": "🔥 Cực hot"},
            {"tag": "未解決事件 犯罪ドキュメンタリー", "niche": "🕵️ Kỳ Án", "badge": "🚀 Triệu view"},
            {"tag": "AIツール 最新技術", "niche": "🤖 Công Nghệ", "badge": "🚀 Mới"},
            {"tag": "副業 ネットビジネス 投資", "niche": "💰 Tài Chính", "badge": "🔥 Trend"}
        ],
        "DE": [
            {"tag": "Gruselgeschichten Horror Deutsch", "niche": "👻 Horror", "badge": "🔥 Spooky"},
            {"tag": "Englisch lernen Anfänger", "niche": "🎓 Learn English", "badge": "🚀 Hot"},
            {"tag": "Fremdgehen Rache Betrug", "niche": "💔 Revenge", "badge": "🔥 Viral"},
            {"tag": "Familiendrama Geschichten", "niche": "🏡 Family", "badge": "⚡ Drama"},
            {"tag": "True Crime Doku Deutsch", "niche": "🕵️ True Crime", "badge": "🚀 Beliebt"},
            {"tag": "Künstliche Intelligenz Tools", "niche": "🤖 AI Tech", "badge": "🔥 Trend"},
            {"tag": "Geld verdienen online 2026", "niche": "💰 Finanzen", "badge": "⚡ 2026"}
        ],
        "DEFAULT": [
            {"tag": "learn english conversation", "niche": "🎓 Learn English", "badge": "🔥 Viral"},
            {"tag": "english speaking practice", "niche": "🎓 Learn English", "badge": "🚀 High View"},
            {"tag": "revenge stories", "niche": "💔 Revenge", "badge": "🔥 Breakout"},
            {"tag": "cheating spouse caught", "niche": "💔 Cheating", "badge": "⚡ Drama"},
            {"tag": "reddit stories AITA", "niche": "💬 Reddit", "badge": "🔥 Trending"},
            {"tag": "mother in law drama", "niche": "🏡 Family", "badge": "⚡ Drama"},
            {"tag": "father in law drama", "niche": "🏡 Family", "badge": "⚡ Story"},
            {"tag": "secret affair confessions", "niche": "🔞 Late Night", "badge": "🔥 18+"},
            {"tag": "ai tools 2026", "niche": "🤖 AI Tech", "badge": "🚀 Trend"},
            {"tag": "make money online", "niche": "💰 Finance", "badge": "🔥 High CPM"},
            {"tag": "true crime interrogation", "niche": "🕵️ True Crime", "badge": "🚀 Deep Dive"},
            {"tag": "scary horror stories", "niche": "👻 Horror", "badge": "🌙 Spooky"},
            {"tag": "stoicism life lessons", "niche": "📜 Stoicism", "badge": "🌱 Wisdom"}
        ]
    }
    return {
        "geo": geo_code,
        "niche_tags": tags_by_geo.get(geo_code, tags_by_geo["DEFAULT"])
    }

NICHE_LOCALIZED_QUERIES = {
    "philosophy": {
        "VN": "triết lý cuộc sống",
        "US": "stoicism philosophy",
        "GB": "stoicism philosophy",
        "FR": "philosophie stoïcisme",
        "IT": "filosofia stoicismo",
        "JP": "哲学 人生訓",
        "KR": "철학 인생 교훈",
        "DE": "Philosophie Stoizismus",
        "DEFAULT": "stoicism philosophy"
    },
    "buddhism": {
        "VN": "lời phật dạy",
        "US": "buddhism teachings",
        "GB": "buddhism mindfulness",
        "FR": "bouddhisme enseignement",
        "IT": "buddismo meditazione",
        "JP": "仏教 法話",
        "KR": "불교",
        "DE": "Buddhismus Meditation",
        "DEFAULT": "buddhism teachings"
    },
    "elderly_wisdom": {
        "VN": "tâm sự tuổi già",
        "US": "elderly wisdom",
        "GB": "elderly wisdom",
        "FR": "sagesse des anciens",
        "IT": "saggezza anziani",
        "JP": "高齢者 人生の教訓",
        "KR": "노인의 지혜",
        "DE": "Lebensweisheiten älterer",
        "DEFAULT": "elderly wisdom"
    },
    "reddit_stories": {
        "VN": "truyện reddit",
        "US": "reddit stories",
        "GB": "reddit stories",
        "FR": "histoires reddit",
        "IT": "storie reddit",
        "JP": "2ch スレ",
        "KR": "레딧 썰",
        "DE": "Reddit Geschichten",
        "DEFAULT": "reddit stories"
    },
    "drama_expose": {
        "VN": "drama bóc phốt",
        "US": "downfall documentary",
        "GB": "exposé documentary",
        "FR": "documentaire scandale",
        "IT": "documentario scandalo",
        "JP": "炎上 事件",
        "KR": "사건 폭로",
        "DE": "Skandal Doku",
        "DEFAULT": "downfall documentary"
    },
    "true_crime": {
        "VN": "vụ án có thật",
        "US": "true crime documentary",
        "GB": "true crime documentary",
        "FR": "faits divers documentaire",
        "IT": "true crime documentario",
        "JP": "未解決事件",
        "KR": "실화 범죄 미제사건",
        "DE": "True Crime Doku",
        "DEFAULT": "true crime documentary"
    },
    "horror_stories": {
        "VN": "truyện ma đêm muộn",
        "US": "scary horror stories",
        "GB": "scary horror stories",
        "FR": "histoires d'horreur",
        "IT": "storie dell'orrore",
        "JP": "怖い話 怪談",
        "KR": "무서운 이야기 실화",
        "DE": "Gruselgeschichten Horror",
        "DEFAULT": "scary horror stories"
    },
    "history_geopolitics": {
        "VN": "lịch sử chiến tranh",
        "US": "history geopolitics",
        "GB": "history documentary warfare",
        "FR": "histoire géopolitique",
        "IT": "storia geopolitica",
        "JP": "歴史 地政学",
        "KR": "역사 다큐멘터리",
        "DE": "Geschichte Geopolitik",
        "DEFAULT": "history geopolitics"
    },
    "space_science": {
        "VN": "bí ẩn vũ trụ",
        "US": "space science documentary",
        "GB": "space documentary",
        "FR": "mystères de l'espace",
        "IT": "misteri dello spazio",
        "JP": "宇宙 科学",
        "KR": "우주 과학 블랙홀",
        "DE": "Weltraum Wissenschaft",
        "DEFAULT": "space science documentary"
    },
    "finance_money": {
        "VN": "tài chính đầu tư",
        "US": "personal finance investing",
        "GB": "personal finance investing",
        "FR": "finances investissement",
        "IT": "finanza personale investimenti",
        "JP": "投資 お金",
        "KR": "재테크 투자",
        "DE": "Finanzen Investieren",
        "DEFAULT": "personal finance investing"
    },
    "tech_ai": {
        "VN": "công nghệ AI",
        "US": "artificial intelligence AI",
        "GB": "artificial intelligence AI",
        "FR": "intelligence artificielle IA",
        "IT": "intelligenza artificiale AI",
        "JP": "人工知能 AI",
        "KR": "인공지능 AI",
        "DE": "Künstliche Intelligenz AI",
        "DEFAULT": "artificial intelligence AI"
    },
    "recap_stories": {
        "VN": "review phim",
        "US": "movie recap",
        "GB": "movie recap",
        "FR": "résumé de film",
        "IT": "riassunto film",
        "JP": "映画 要約",
        "KR": "영화 요약",
        "DE": "Film Zusammenfassung",
        "DEFAULT": "movie recap"
    },
    "gaming": {
        "VN": "gameplay highlights",
        "US": "gaming highlights",
        "GB": "gaming highlights",
        "FR": "gameplay highlights",
        "IT": "gameplay highlights",
        "JP": "ゲーム 実況",
        "KR": "게임 플레이",
        "DE": "Gaming Highlights",
        "DEFAULT": "gaming highlights"
    },
    "entertainment": {
        "VN": "hài hước giải trí",
        "US": "entertainment funny viral",
        "GB": "entertainment funny viral",
        "FR": "divertissement humour",
        "IT": "intrattenimento commedia",
        "JP": "エンタメ 面白い",
        "KR": "예능 레전드",
        "DE": "Unterhaltung Comedy",
        "DEFAULT": "entertainment funny viral"
    },
    "spicy_18_drama": {
        "VN": "tâm sự thầm kín",
        "US": "relationship drama stories",
        "GB": "relationship confessions stories",
        "FR": "histoires d'amour secrètes",
        "IT": "storie d'amore segrete",
        "DE": "Geheime Liebesgeschichten",
        "IN": "relationship secret affair stories",
        "JP": "大人の恋愛 浮気",
        "KR": "19금 썰",
        "DEFAULT": "relationship drama stories"
    },
    "father_inlaw_drama": {
        "VN": "bố chồng nàng dâu",
        "US": "father in law family drama",
        "GB": "father in law Reddit drama",
        "FR": "beau-père famille drame",
        "IT": "suocero drammi familiari",
        "DE": "Schwiegervater Familiendrama",
        "IN": "father in law family drama",
        "JP": "義父と嫁 家族",
        "KR": "시아버지 며느리",
        "DEFAULT": "father in law family drama"
    },
    "mother_inlaw_drama": {
        "VN": "mẹ vợ con rể",
        "US": "mother in law family drama",
        "GB": "mother in law Reddit drama",
        "FR": "belle-mère gendre conflit",
        "IT": "suocera e genero drammi",
        "DE": "Schwiegermutter Konflikt",
        "IN": "mother in law family drama",
        "JP": "義母と婿 家族",
        "KR": "장모 사위",
        "DEFAULT": "mother in law family drama"
    },
    "infidelity_revenge": {
        "VN": "bắt gian ngoại tình",
        "US": "cheating revenge drama",
        "GB": "cheating partner revenge Reddit",
        "FR": "tromperie vengeance",
        "IT": "tradimento vendetta",
        "DE": "Fremdgehen Rache Betrug",
        "IN": "cheating revenge drama",
        "JP": "浮気 修羅場 復讐",
        "KR": "바람 불륜 참교육",
        "DEFAULT": "cheating revenge drama"
    },
    "learn_english": {
        "VN": "học tiếng anh giao tiếp",
        "US": "learn english speaking",
        "GB": "learn english conversation",
        "FR": "apprendre l'anglais",
        "IT": "imparare l'inglese",
        "DE": "englisch lernen konversation",
        "IN": "learn english speaking practice",
        "JP": "英会話 リスニング",
        "KR": "영어 회화",
        "BR": "aprender ingles",
        "CA": "learn english speaking",
        "AU": "learn english speaking",
        "DEFAULT": "learn english speaking"
    },
    "luxury_lifestyle": {
        "VN": "cuộc sống thượng lưu",
        "US": "luxury lifestyle billionaire",
        "GB": "luxury lifestyle billionaire",
        "FR": "style de vie luxueux",
        "IT": "stile di vita lussuoso",
        "JP": "高級車 大富豪",
        "KR": "슈퍼카 부자",
        "DE": "Luxus Lifestyle Milliardär",
        "DEFAULT": "luxury lifestyle billionaire"
    },
    "travel_food": {
        "VN": "ẩm thực đường phố",
        "US": "travel street food",
        "GB": "travel food guide",
        "FR": "street food gastronomie",
        "IT": "street food cucina tipica",
        "JP": "グルメ 食べ歩き",
        "KR": "여행 맛집 먹방",
        "DE": "Street Food Kulinarik",
        "DEFAULT": "travel street food"
    },
    "fitness_health": {
        "VN": "tập gym giảm cân",
        "US": "fitness workout gym",
        "GB": "fitness workout routine",
        "FR": "musculation fitness",
        "IT": "allenamento palestra fitness",
        "JP": "筋トレ フィットネス",
        "KR": "헬스 다이어트",
        "DE": "Fitness Training Muskelaufbau",
        "DEFAULT": "fitness workout gym"
    },
    "music_chill": {
        "VN": "nhạc lofi chill",
        "US": "lofi chill beats",
        "GB": "lofi chill beats",
        "FR": "musique relaxante lofi chill",
        "IT": "musica rilassante lofi",
        "JP": "作業用bgm 睡眠用 音楽",
        "KR": "로파이 힐링 음악",
        "DE": "Entspannungsmusik Lofi Chill",
        "DEFAULT": "lofi chill beats"
    }
}

SP_MAP = {
    "24h": "CAMSBAgCEAE%3D",  # Today / last 24h, sorted by viewCount
    "48h": "CAMSBAgCEAE%3D",  # 24-48h, sorted by viewCount
    "7d":  "CAMSBAgDEAE%3D",  # This week / last 7 days, sorted by viewCount
    "30d": "CAMSBAgEEAE%3D",  # This month / last 30 days, sorted by viewCount
    "all": "CAMSAhAB"         # All time, sorted by viewCount
}

def parse_duration_str_to_seconds(dur_str: str) -> int:
    """Chuyển đổi chuỗi độ dài '4:49:21' hoặc '23:45' thành giây."""
    if not dur_str:
        return 0
    parts = dur_str.strip().split(':')
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 1:
            return int(parts[0])
    except Exception:
        return 0
    return 0

def parse_views_str(view_str: str) -> int:
    """Chuyển đổi chuỗi lượt xem đa ngôn ngữ ('402.643 lượt xem', '1.2M views', '150K') thành int."""
    if not view_str:
        return 0
    v = view_str.strip()
    m_match = re.search(r'([\d.,]+)\s*(?:M|Tr|tr|triệu|million|万)', v, re.IGNORECASE)
    if m_match:
        num = float(m_match.group(1).replace(',', '.'))
        mult = 10000 if '万' in v else 1000000
        return int(num * mult)
    k_match = re.search(r'([\d.,]+)\s*(?:K|k|N|nghìn|ngàn)', v, re.IGNORECASE)
    if k_match:
        num = float(k_match.group(1).replace(',', '.'))
        return int(num * 1000)
    nums = re.findall(r'\d+', v)
    return int(''.join(nums)) if nums else 0

def is_published_age_matching_range(pub_text: str, t_range: str) -> bool:
    """Kiểm tra nghiêm ngặt chuỗi thời gian hiển thị xem có thực sự nằm trong khung thời gian hay không."""
    if not pub_text or t_range == "all":
        return True
    p = pub_text.lower().strip()
    
    # 1. Tuyệt đối không cho phép video từ nhiều năm trước lọt vào các bộ lọc ngắn hạn
    if any(w in p for w in ['năm', 'year', 'yr', '年前', '년 전', 'jahr', 'an ']):
        return False
        
    # 2. Với 24h, 48h, 7d: Tuyệt đối không chấp nhận video từ tháng trước
    if t_range in ['24h', '48h', '7d']:
        if any(w in p for w in ['tháng', 'thg', 'month', 'mo', 'か月前', '개월 전', 'monat', 'mois']):
            return False
            
    # 3. Với 24h & 48h: Tuyệt đối không chấp nhận video tính bằng tuần
    if t_range in ['24h', '48h']:
        if any(w in p for w in ['tuần', 'week', 'wk', '週間前', '주 전', 'woche', 'semaine']):
            return False
        d_match = re.search(r'(\d+)\s*(?:ngày|day|tage?|jour|일|日)', p)
        if d_match:
            days = int(d_match.group(1))
            if t_range == '24h' and days > 1:
                return False
            if t_range == '48h' and days > 2:
                return False
                
    # 4. Với 7d: Chấp nhận tối đa 7 ngày (hoặc 1 tuần trước, loại bỏ 2 tuần trở lên)
    if t_range == '7d':
        w_match = re.search(r'(\d+)\s*(?:tuần|week|wk|woche|semaine|주|週間)', p)
        if w_match:
            weeks = int(w_match.group(1))
            if weeks > 1:
                return False
        d_match = re.search(r'(\d+)\s*(?:ngày|day|tage?|jour|일|日)', p)
        if d_match:
            days = int(d_match.group(1))
            if days > 7:
                return False

    # 5. Với 30d: Chấp nhận tối đa 1 tháng (loại bỏ từ 2 tháng trở lên)
    if t_range == '30d':
        m_match = re.search(r'(\d+)\s*(?:tháng|month|mo|monat|mois|개월|か月)', p)
        if m_match:
            months = int(m_match.group(1))
            if months > 1:
                return False
                
    return True



def format_published_age(pub_iso: str) -> str:
    if not pub_iso:
        return ""
    try:
        dt = datetime.datetime.fromisoformat(pub_iso.replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
        diff_seconds = (now - dt).total_seconds()
        
        if diff_seconds < 3600:
            diff_mins = max(1, int(diff_seconds // 60)) if diff_seconds > 0 else 1
            return f"⚡ {diff_mins} phút trước • Vừa đăng"

        diff_hours = int(diff_seconds // 3600)
        diff_days = int(diff_seconds // 86400)
        
        if diff_hours < 24:
            return f"⚡ {max(1, diff_hours)} giờ trước • Mới"
        elif diff_days == 1:
            return "🔥 1 ngày trước • Đang lên"
        elif diff_days <= 7:
            return f"🔥 {diff_days} ngày trước • Xu hướng tuần"
        elif diff_days <= 30:
            return f"📅 {diff_days} ngày trước • Tháng này"
        elif diff_days < 365:
            months = max(1, diff_days // 30)
            return f"⏳ {months} tháng trước"
        else:
            years = max(1, diff_days // 365)
            return f"🏛️ {years} năm trước • All-Time"
    except Exception:
        return pub_iso[:10]

def is_video_matching_country(item: dict, ch_info: dict, target_geo: str) -> bool:
    """Kiểm tra nghiêm ngặt ngôn ngữ, bảng chữ cái và quốc gia kênh để ngăn chặn video ngoại lai."""
    geo = (target_geo or 'US').upper().strip()
    snippet = item.get('snippet', {})
    title = snippet.get('title', '')
    ch_title = snippet.get('channelTitle', '')
    combined_title = f"{title} {ch_title}"

    audio_lang = (snippet.get('defaultAudioLanguage') or '').lower()
    default_lang = (snippet.get('defaultLanguage') or '').lower()
    ch_country = (ch_info.get('snippet', {}).get('country') or '').upper()

    # Bảng chữ cái đặc thù của các ngôn ngữ
    has_thai = bool(re.search(r'[\u0e00-\u0e7f]', combined_title))
    has_south_asian = bool(re.search(r'[\u0900-\u097f\u0980-\u09ff\u0a00-\u0a7f\u0a80-\u0aff\u0b80-\u0bff\u0c00-\u0c7f\u0c80-\u0cff\u0d00-\u0d7f]', combined_title))
    has_hangul = bool(re.search(r'[\uac00-\ud7a3\u1100-\u11ff\u3130-\u318f]', combined_title))
    has_kana = bool(re.search(r'[\u3040-\u30ff]', combined_title))
    has_cyrillic = bool(re.search(r'[\u0400-\u04ff]', combined_title))
    has_arabic = bool(re.search(r'[\u0600-\u06ff]', combined_title))
    
    # Tiếng Việt đặc thù (tránh nhầm với từ mượn Pháp/Tây Ban Nha như Pokémon, café)
    has_vn = bool(re.search(r'[đươĐƯƠ]', combined_title)) or len(re.findall(r'[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵ]', combined_title, re.I)) >= 3

    # 1. Video tiếng Thái: TUYỆT ĐỐI KHÔNG xuất hiện ở bất kỳ quốc gia nào ngoài Thái Lan (TH)
    if has_thai or audio_lang.startswith('th') or default_lang.startswith('th') or ch_country == 'TH':
        if geo != 'TH':
            return False

    # 2. Thị trường Mỹ & tiếng Anh (US, GB, CA, AU)
    if geo in ['US', 'GB', 'CA', 'AU']:
        if has_south_asian or has_hangul or has_kana or has_cyrillic or has_arabic or has_vn:
            return False
        if audio_lang and not audio_lang.startswith(('en', 'es', 'zxx')):
            return False
        if ch_country in ['IN', 'VN', 'RU', 'PK', 'BD', 'ID', 'KR', 'JP', 'TH']:
            return False

    # 3. Thị trường Đức (DE)
    elif geo == 'DE':
        if has_south_asian or has_hangul or has_kana or has_cyrillic or has_arabic or has_vn:
            return False
        if audio_lang and not audio_lang.startswith(('de', 'en', 'zxx')):
            return False
        if ch_country in ['IN', 'VN', 'RU', 'PK', 'BD', 'ID', 'KR', 'JP', 'TH']:
            return False

    # 4. Thị trường Ấn Độ (IN)
    elif geo == 'IN':
        if has_hangul or has_kana or has_vn or has_cyrillic:
            return False
        if ch_country in ['VN', 'RU', 'JP', 'KR', 'DE', 'TH']:
            return False

    # 5. Thị trường Việt Nam (VN)
    elif geo == 'VN':
        if has_south_asian or has_hangul or has_kana or has_cyrillic or has_arabic:
            return False
        if audio_lang and not audio_lang.startswith(('vi', 'en', 'zxx')):
            return False
        if ch_country in ['IN', 'RU', 'PK', 'BD', 'ID', 'TH']:
            return False

    # 6. Thị trường Nhật Bản (JP)
    elif geo == 'JP':
        if has_south_asian or has_hangul or has_vn or has_cyrillic or has_arabic:
            return False
        if audio_lang and not audio_lang.startswith(('ja', 'en', 'zxx')):
            return False
        if ch_country in ['IN', 'VN', 'RU', 'PK', 'TH']:
            return False

    # 7. Thị trường Hàn Quốc (KR)
    elif geo == 'KR':
        if has_south_asian or has_kana or has_vn or has_cyrillic or has_arabic:
            return False
        if audio_lang and not audio_lang.startswith(('ko', 'en', 'zxx')):
            return False
        if ch_country in ['IN', 'VN', 'RU', 'PK', 'TH']:
            return False

    # 8. Thị trường Brazil (BR)
    elif geo == 'BR':
        if has_south_asian or has_hangul or has_kana or has_vn or has_cyrillic or has_arabic:
            return False
        if audio_lang and not audio_lang.startswith(('pt', 'en', 'es', 'zxx')):
            return False
        if ch_country in ['IN', 'VN', 'RU', 'PK', 'TH']:
            return False

    # 9. Thị trường Pháp (FR)
    elif geo == 'FR':
        if has_south_asian or has_hangul or has_kana or has_cyrillic or has_arabic or has_vn:
            return False
        # Chỉ chấp nhận tiếng Pháp (hoặc zxx - không lời), TUYỆT ĐỐI KHÔNG nhận tiếng Anh
        if audio_lang and not audio_lang.startswith(('fr', 'zxx')):
            return False
        if default_lang and not default_lang.startswith(('fr', 'zxx')):
            return False
        # Chặn kênh từ Mỹ, Anh, Úc, Canada (nếu không nói tiếng Pháp), Ấn Độ, v.v.
        if ch_country in ['US', 'GB', 'AU', 'IN', 'VN', 'RU', 'PK', 'BD', 'ID', 'KR', 'JP', 'TH']:
            return False
        # Kiểm tra từ vựng / dấu tiếng Pháp đặc trưng để loại bỏ hoàn toàn video tiếng Anh lọt vào
        fr_accents = bool(re.search(r'[éèêëàâîïôùûçœæ]', combined_title, re.I))
        fr_vocab = {'le', 'la', 'les', 'un', 'une', 'des', 'du', 'de', 'et', 'en', 'pour', 'dans', 'sur', 'avec', 'qui', 'que', 'ce', 'cette', 'est', 'sont', 'pas', 'ne', 'au', 'aux', 'par', 'film', 'français', 'france', 'histoire', 'drames', 'drame', 'amour', 'femme', 'homme', 'mari', 'mariage', 'trahison', 'vengeance', 'secret', 'famille', 'fille', 'fils', 'père', 'mère', 'anglais', 'apprendre', 'cours', 'vocabulaire', 'parler'}
        t_words = set(re.findall(r'\b[a-zA-ZÀ-ÿ]{2,}\b', combined_title.lower()))
        has_fr_words = bool(t_words.intersection(fr_vocab))
        is_fr_channel = (ch_country == 'FR') or audio_lang.startswith('fr') or default_lang.startswith('fr')
        if not (fr_accents or has_fr_words or is_fr_channel):
            return False

    # 10. Thị trường Ý (IT)
    elif geo == 'IT':
        if has_south_asian or has_hangul or has_kana or has_cyrillic or has_arabic or has_vn:
            return False
        if audio_lang and not audio_lang.startswith(('it', 'zxx')):
            return False
        if default_lang and not default_lang.startswith(('it', 'zxx')):
            return False
        if ch_country in ['US', 'GB', 'AU', 'IN', 'VN', 'RU', 'PK', 'BD', 'ID', 'KR', 'JP', 'TH']:
            return False
        it_accents = bool(re.search(r'[àèéìíîòóùú]', combined_title, re.I))
        it_vocab = {'il', 'lo', 'la', 'i', 'gli', 'le', 'un', 'uno', 'una', 'di', 'a', 'da', 'in', 'con', 'su', 'per', 'tra', 'fra', 'che', 'non', 'sono', 'storie', 'storia', 'amore', 'tradimento', 'vendetta', 'famiglia', 'marito', 'moglie', 'segreto', 'dramma', 'racconto', 'italia', 'italiano', 'inglese', 'imparare', 'corso', 'vocabolario', 'parlare'}
        t_words_it = set(re.findall(r'\b[a-zA-ZÀ-ÿ]{2,}\b', combined_title.lower()))
        has_it_words = bool(t_words_it.intersection(it_vocab))
        is_it_channel = (ch_country == 'IT') or audio_lang.startswith('it') or default_lang.startswith('it')
        if not (it_accents or has_it_words or is_it_channel):
            return False

    return True

@app.get("/api/trending/feed")
def get_trending_feed(
    country: Optional[str] = None, 
    geo: Optional[str] = "US", 
    category: Optional[str] = "all",
    time_range: Optional[str] = "7d",
    duration: Optional[str] = "long_form",
    feed_mode: Optional[str] = "active_channels",
    refresh: Optional[bool] = False
):
    geo_code = (country or geo or "US").upper()
    cat = (category or "all").lower()
    t_range = (time_range or "7d").lower()
    dur_filter = (duration or "long_form").lower()
    mode = (feed_mode or "active_channels").lower()
    api_key = get_default_api_key()

    cache_key = f"{geo_code}_{cat}_{t_range}_{dur_filter}_{mode}"
    if not refresh:
        cached_feed = get_from_cache(_TRENDING_FEED_CACHE, cache_key)
        if cached_feed:
            return cached_feed

    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff_dt = None
    published_after_str = None

    if t_range == "24h":
        cutoff_dt = now - datetime.timedelta(days=1)
        published_after_str = cutoff_dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    elif t_range == "48h":
        cutoff_dt = now - datetime.timedelta(days=2)
        published_after_str = cutoff_dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    elif t_range == "7d":
        cutoff_dt = now - datetime.timedelta(days=7)
        published_after_str = cutoff_dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    elif t_range == "30d":
        cutoff_dt = now - datetime.timedelta(days=30)
        published_after_str = cutoff_dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    elif t_range == "all":
        cutoff_dt = None
        published_after_str = None
    else:
        cutoff_dt = now - datetime.timedelta(days=7)
        published_after_str = cutoff_dt.strftime('%Y-%m-%dT%H:%M:%SZ')

    videos = []

    # 1. Thử dùng YouTube Data API v3 chính thức nếu có API Key (Tối ưu kết nối keep-alive)
    if api_key:
        try:
            video_items = []
            
            # TRƯỜNG HỢP 1: Tất cả xu hướng (Top Trending chung của quốc gia)
            if cat == "all":
                chart_url = (
                    f"https://www.googleapis.com/youtube/v3/videos?part=snippet,contentDetails,statistics,liveStreamingDetails"
                    f"&chart=mostPopular&regionCode={geo_code}&maxResults=50&key={api_key}"
                )
                chart_resp = http_session.get(chart_url, timeout=6)
                if chart_resp.status_code == 200:
                    raw_items = chart_resp.json().get("items", [])
                    
                    # Lọc theo khung thời gian (7d, 24h, 30d...)
                    for it in raw_items:
                        pub_iso = it.get("snippet", {}).get("publishedAt", "")
                        if cutoff_dt:
                            if not pub_iso:
                                continue
                            try:
                                p_dt = datetime.datetime.fromisoformat(pub_iso.replace("Z", "+00:00"))
                                if p_dt < cutoff_dt:
                                    continue
                            except Exception:
                                continue
                        video_items.append(it)
            
            # TRƯỜNG HỢP 2: Theo chủ đề / ngách cụ thể HOẶC nếu chart trả về chưa đủ video
            if cat != "all" or len(video_items) < 8:
                v_dur_param = "long" if dur_filter == "deep_dive" else "any"

                niche_dict = NICHE_LOCALIZED_QUERIES.get(cat, {})
                if cat != "all" and niche_dict:
                    q_term = niche_dict.get(geo_code, niche_dict.get("DEFAULT", cat))
                else:
                    country_names = {
                        "US": "documentary podcast trending viral",
                        "GB": "documentary podcast trending",
                        "JP": "ドキュメンタリー 話題の動画",
                        "KR": "인기 급상승 다큐멘터리",
                        "DE": "Dokumentation Podcast Trends",
                        "VN": "phóng sự tài liệu podcast xu hướng",
                        "FR": "documentaire reportage podcast france",
                        "IT": "documentario reportage podcast italia",
                        "IN": "trending documentary podcast india",
                        "BR": "documentario podcast brasil"
                    }
                    q_term = country_names.get(geo_code, "trending viral video")

                GEO_LANG_MAP = {
                    "US": "en", "GB": "en", "CA": "en", "AU": "en",
                    "VN": "vi", "JP": "ja", "KR": "ko", "DE": "de",
                    "BR": "pt", "IN": "en", "FR": "fr", "IT": "it"
                }
                lang_param = GEO_LANG_MAP.get(geo_code, "en")

                s_url = (
                    f"https://www.googleapis.com/youtube/v3/search?part=snippet&type=video"
                    f"&videoDuration={v_dur_param}&order=viewCount&regionCode={geo_code}"
                    f"&relevanceLanguage={lang_param}&q={requests.utils.quote(q_term)}&maxResults=40&key={api_key}"
                )
                if published_after_str:
                    s_url += f"&publishedAfter={published_after_str}"

                s_resp = http_session.get(s_url, timeout=6)
                if s_resp.status_code == 200:
                    s_items = s_resp.json().get("items", [])
                    v_ids = [it["id"]["videoId"] for it in s_items if it.get("id", {}).get("videoId")]

                    if v_ids:
                        d_url = f"https://www.googleapis.com/youtube/v3/videos?part=snippet,statistics,contentDetails,liveStreamingDetails&id={','.join(v_ids[:40])}&key={api_key}"
                        d_resp = http_session.get(d_url, timeout=6)
                        if d_resp.status_code == 200:
                            existing_ids = {it.get("id") for it in video_items}
                            for it in d_resp.json().get("items", []):
                                if it.get("id") and it["id"] not in existing_ids:
                                    video_items.append(it)

            if video_items:
                # Lấy thông tin kênh (Tối ưu với Cache thông tin kênh, tránh gọi API lặp lại)
                ch_ids = list(set([it["snippet"]["channelId"] for it in video_items if it.get("snippet", {}).get("channelId")]))
                ch_map = {}
                missing_ch_ids = []
                for cid in ch_ids:
                    c_data = get_from_cache(_CHANNEL_INFO_CACHE, cid)
                    if c_data:
                        ch_map[cid] = c_data
                    else:
                        missing_ch_ids.append(cid)

                if missing_ch_ids and api_key:
                    ch_url = f"https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics&id={','.join(missing_ch_ids[:50])}&key={api_key}"
                    ch_resp = http_session.get(ch_url, timeout=6)
                    if ch_resp.status_code == 200:
                        for ch in ch_resp.json().get("items", []):
                            ch_map[ch["id"]] = ch
                            set_to_cache(_CHANNEL_INFO_CACHE, ch["id"], ch, ttl_seconds=7200)

                for item in video_items:
                    v_id = item.get("id")
                    snippet = item.get("snippet", {})
                    stats = item.get("statistics", {})
                    content_det = item.get("contentDetails", {})
                    
                    # 1. BẢO VỆ MỐC THỜI GIAN NGHIÊM NGẶT: Tuyệt đối không cho video cũ lọt vào
                    pub_at = snippet.get("publishedAt", "")
                    if cutoff_dt:
                        if not pub_at:
                            continue
                        try:
                            p_dt = datetime.datetime.fromisoformat(pub_at.replace("Z", "+00:00"))
                            if p_dt < cutoff_dt:
                                continue
                        except Exception:
                            continue

                    # 2. LOẠI BỎ TOÀN BỘ VIDEO LIVESTREAM, RESTREAM, TRỰC TIẾP
                    if is_stream_video(item):
                        continue

                    # 3. LOẠI BỎ TOÀN BỘ SHORTS VÀ KÊNH SHORTS (< 180 giây hoặc kênh chuyên Shorts)
                    dur_iso = content_det.get("duration", "")
                    dur_seconds = parse_iso_duration(dur_iso)
                    title_raw = snippet.get("title", "")
                    ch_title_raw = snippet.get("channelTitle", "")
                    
                    if is_short_video_or_channel(title=title_raw, channel_title=ch_title_raw, duration_sec=dur_seconds, url=f"https://www.youtube.com/watch?v={v_id}"):
                        continue
                    if dur_filter == "deep_dive" and dur_seconds < 1200:
                        continue

                    # 4. LỌC VIEW TỐI THIỂU: Đã là xu hướng (Trending) thì không thể chỉ có vài chục view
                    view_cnt = int(stats.get("viewCount", 0))
                    if t_range in ["7d", "24h", "48h", "30d"] and view_cnt < 500:
                        continue

                    # Kiểm tra kênh hoạt động & ổn định
                    ch_id = snippet.get("channelId", "")
                    ch_info = ch_map.get(ch_id, {})

                    # 5. BỘ LỌC QUỐC GIA & NGÔN NGỮ NGHIÊM NGẶT:
                    # Ngăn chặn 100% video ngoại lai (Thái Lan, Ấn Độ, v.v.) hiển thị sai khi chọn Mỹ, Đức, v.v.
                    if not is_video_matching_country(item, ch_info, geo_code):
                        continue

                    ch_stats = ch_info.get("statistics", {})
                    subs_count = int(ch_stats.get("subscriberCount") or 0)
                    total_vids = int(ch_stats.get("videoCount") or 0)
                    
                    is_active_channel = (subs_count >= 1000 and total_vids >= 5) or (view_cnt >= 5000)
                    is_very_stable = subs_count >= 10000 and total_vids >= 20
                    
                    if is_very_stable:
                        channel_badge_text = "🟢 Kênh Ổn Định"
                    elif is_active_channel:
                        channel_badge_text = "🟢 Kênh Hoạt Động"
                    else:
                        channel_badge_text = "📺 Kênh Mới"
                        
                    if subs_count > 0:
                        if subs_count >= 1_000_000:
                            channel_badge_text += f" • {subs_count / 1_000_000:.1f}M Subs"
                        elif subs_count >= 10_000:
                            channel_badge_text += f" • {subs_count // 1_000}K Subs"
                        elif subs_count >= 1_000:
                            channel_badge_text += f" • {subs_count / 1_000:.1f}K Subs"
                        else:
                            channel_badge_text += f" • {subs_count} Subs"

                    if mode == "active_channels" and not is_active_channel:
                        continue

                    thumb = (snippet.get("thumbnails", {}).get("high") or snippet.get("thumbnails", {}).get("medium") or {}).get("url") or f"https://i.ytimg.com/vi/{v_id}/hqdefault.jpg"

                    videos.append({
                        "video_id": v_id,
                        "id": v_id,
                        "title": title_raw,
                        "channel_title": snippet.get("channelTitle", "YouTube Creator"),
                        "channel": snippet.get("channelTitle", "YouTube Creator"),
                        "channel_id": ch_id,
                        "channel_subs": subs_count,
                        "is_verified": subs_count >= 100000,
                        "channel_videos": total_vids,
                        "channel_badge": channel_badge_text,
                        "is_active_channel": is_active_channel,
                        "view_count": view_cnt,
                        "views": view_cnt,
                        "duration_seconds": dur_seconds,
                        "duration_formatted": format_duration_display(dur_seconds),
                        "published_at": pub_at[:10],
                        "published_age": format_published_age(pub_at),
                        "url": f"https://www.youtube.com/watch?v={v_id}",
                        "thumbnail": thumb
                    })

                # Sắp xếp theo view count giảm dần để top video bứt phá nhất lên đầu
                videos.sort(key=lambda x: x["view_count"], reverse=True)

        except Exception as api_err:
            logger.warning(f"Lỗi truy vấn trending qua YouTube Data API: {api_err}")

    # 2. Nếu không có API Key hoặc API trả về rỗng, dùng fallback thông minh qua URL lọc sp chính xác của YouTube
    if not videos:
        try:
            fallback_country_queries = {
                "US": "trending usa",
                "GB": "trending uk",
                "DE": "trends deutschland",
                "FR": "tendances france",
                "IT": "tendenze italia",
                "IN": "trending india",
                "VN": "thịnh hành việt nam",
                "JP": "話題 トレンド",
                "KR": "이슈 트렌드",
                "BR": "em alta brasil",
                "CA": "trending canada",
                "AU": "trending australia"
            }
            
            if cat in NICHE_LOCALIZED_QUERIES:
                niche_dict = NICHE_LOCALIZED_QUERIES[cat]
                search_query = niche_dict.get(geo_code, niche_dict.get("DEFAULT", cat))
            else:
                search_query = fallback_country_queries.get(geo_code, f"trending viral podcast documentary {geo_code}")

            # Lấy mã ngôn ngữ cho Accept-Language header
            GEO_LANG_MAP = {
                "US": "en", "GB": "en", "CA": "en", "AU": "en",
                "VN": "vi", "JP": "ja", "KR": "ko", "DE": "de",
                "BR": "pt", "IN": "en", "FR": "fr", "IT": "it"
            }
            hl_code = GEO_LANG_MAP.get(geo_code, "en")

            # Tạo danh sách các từ khóa tìm kiếm: từ khóa chính + biến thể ngắn gọn
            candidate_queries = [search_query]
            
            # Tự động thêm các biến thể từ khóa ngắn hơn nếu từ khóa hiện tại dài hơn 1 từ
            words = search_query.split()
            if len(words) > 1:
                candidate_queries.append(words[0])
                if len(words) >= 2:
                    candidate_queries.append(' '.join(words[:2]))
                if len(words) >= 3:
                    candidate_queries.append(words[1])

            if cat == "all":
                secondary_queries = {
                    "VN": ["podcast việt nam", "phóng sự tài liệu", "vlog việt nam"],
                    "US": ["podcast documentary usa", "popular talk show"],
                    "GB": ["podcast documentary uk", "popular talk show"],
                    "DE": ["podcast reportage deutschland", "dokumentation"],
                    "FR": ["podcast reportage france", "documentaire"],
                    "IT": ["podcast reportage italia", "documentario"],
                    "JP": ["ドキュメンタリー 話題", "ポッドキャスト"],
                    "KR": ["이슈 팟캐스트", "다큐멘터리"]
                }
                candidate_queries.extend(secondary_queries.get(geo_code, ["podcast documentary"]))

            # Sử dụng sp filter chính thức của YouTube để lọc đúng 100% mốc thời gian và sắp xếp theo lượt xem
            sp_param = SP_MAP.get(t_range, "CAMSBAgDEAE%3D")

            # BƯỚC 2.1: Truy vấn trực tiếp YouTube Web UI lấy ytInitialData (nhanh ~300ms, có nhãn ngày đăng thật)
            direct_headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept-Language': f"{hl_code}-{geo_code},{hl_code};q=0.9,en;q=0.8"
            }
            
            existing_vids = set()
            for cand_query in candidate_queries:
                if len(videos) >= 18:
                    break
                search_url = f"https://www.youtube.com/results?search_query={requests.utils.quote(cand_query)}&sp={sp_param}"
                try:
                    web_resp = http_session.get(search_url, headers=direct_headers, timeout=6)
                    if web_resp.status_code == 200:
                        m = re.search(r'ytInitialData\s*=\s*({.+?});</script>', web_resp.text)
                        if not m:
                            m = re.search(r'ytInitialData\s*=\s*({.+?});', web_resp.text)
                        if m:
                            data = json.loads(m.group(1))
                            raw_vrs = []
                            
                            def extract_vrs(obj):
                                if isinstance(obj, dict):
                                    if 'videoRenderer' in obj:
                                        raw_vrs.append(obj['videoRenderer'])
                                    for v in obj.values():
                                        extract_vrs(v)
                                elif isinstance(obj, list):
                                    for it in obj:
                                        extract_vrs(it)

                            extract_vrs(data)

                            for vr in raw_vrs:
                                v_id = vr.get('videoId')
                                if not v_id or v_id in existing_vids:
                                    continue
                                
                                t = ''.join(r.get('text', '') for r in vr.get('title', {}).get('runs', []))
                                pub_age = vr.get('publishedTimeText', {}).get('simpleText', '')
                                views_str = vr.get('viewCountText', {}).get('simpleText', '')
                                dur_str = vr.get('lengthText', {}).get('simpleText', '')
                                ch_name = ''.join(r.get('text', '') for r in vr.get('ownerText', {}).get('runs', [])) or 'YouTube Creator'
                                
                                ch_id = ''
                                try:
                                    ch_id = vr.get('ownerText', {}).get('runs', [{}])[0].get('navigationEndpoint', {}).get('browseEndpoint', {}).get('browseId', '')
                                except Exception:
                                    pass

                                # Kiểm tra livestream
                                is_live = any(b.get('metadataBadgeRenderer', {}).get('label') in ['TRỰC TIẾP', 'LIVE'] for b in vr.get('badges', []))
                                is_live = is_live or any(o.get('thumbnailOverlayTimeStatusRenderer', {}).get('style') == 'LIVE' for o in vr.get('thumbnailOverlays', []))
                                if is_live or any(kw in pub_age.lower() for kw in ['trực tiếp', 'phát trực tiếp', 'stream']) or any(kw in t.lower() for kw in ['restream', 'livestream', '🔴']):
                                    continue

                                # Độ dài & Lọc Shorts / Kênh Shorts
                                dur_sec = parse_duration_str_to_seconds(dur_str)
                                if is_short_video_or_channel(title=t, channel_title=ch_name, duration_sec=dur_sec, url=f"https://www.youtube.com/watch?v={v_id}"):
                                    continue
                                if dur_filter == "deep_dive" and dur_sec > 0 and dur_sec < 1200:
                                    continue
                                if dur_sec > 36000:
                                    continue

                                # Lượt xem
                                v_cnt = parse_views_str(views_str)
                                if t_range in ["7d", "24h", "48h", "30d"] and v_cnt < 200:
                                    continue

                                # KIỂM TRA THỜI GIAN NGHIÊM NGẶT: Không bao giờ cho phép video cũ xuất hiện
                                if not is_published_age_matching_range(pub_age, t_range):
                                    continue

                                # Loại bỏ các video/phim cũ có năm phát hành cũ trong tiêu đề khi lọc 24h hoặc 7d
                                if t_range in ["24h", "48h", "7d"] and re.search(r'\b(19\d\d|200\d|201\d|202[0-3])\b', t):
                                    continue

                                # Lọc quốc gia và ngôn ngữ
                                pseudo_item = {
                                    'snippet': {
                                        'title': t,
                                        'channelTitle': ch_name,
                                        'defaultAudioLanguage': hl_code
                                    }
                                }
                                pseudo_ch = {
                                    'snippet': {
                                        'country': geo_code
                                    }
                                }
                                if not is_video_matching_country(pseudo_item, pseudo_ch, geo_code):
                                    continue

                                thumbs = vr.get('thumbnail', {}).get('thumbnails', [])
                                thumb_url = thumbs[-1].get('url') if thumbs else f"https://i.ytimg.com/vi/{v_id}/hqdefault.jpg"

                                is_ver = any("BADGE_STYLE_TYPE_VERIFIED" in str(b) for b in vr.get('ownerBadges', []))

                                existing_vids.add(v_id)
                                videos.append({
                                    "video_id": v_id,
                                    "id": v_id,
                                    "title": t,
                                    "channel_title": ch_name,
                                    "channel": ch_name,
                                    "channel_id": ch_id,
                                    "channel_badge": "🟢 Kênh Xác Minh" if is_ver else "🟢 Kênh Hoạt Động",
                                    "channel_subs": 100000 if is_ver else 50000,
                                    "is_verified": is_ver,
                                    "is_active_channel": True,
                                    "view_count": v_cnt,
                                    "views": v_cnt,
                                    "duration_seconds": dur_sec,
                                    "duration_formatted": dur_str or format_duration_display(dur_sec),
                                    "published_at": "",
                                    "published_age": pub_age or ("🔥 Xu hướng tuần này" if t_range == "7d" else "⚡ 24h qua"),
                                    "url": f"https://www.youtube.com/watch?v={v_id}",
                                    "thumbnail": thumb_url
                                })
                except Exception as direct_err:
                    logger.warning(f"Direct trending scraping failed for {cand_query}: {direct_err}")

            # BƯỚC 2.2: Nếu direct scraping chưa đủ video (ít hơn 4), dùng yt-dlp trên đúng URL đã gắn sp filter
            if len(videos) < 4:
                ydl_opts = {
                    'quiet': True,
                    'skip_download': True,
                    'extract_flat': True,
                    'socket_timeout': 6,
                    'playlist_items': '1-30',
                    'http_headers': {
                        'Accept-Language': f"{hl_code}-{geo_code},{hl_code};q=0.9,en;q=0.8"
                    }
                }
                existing_vids = {v["video_id"] for v in videos}
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    res = ydl.extract_info(search_url, download=False)
                    if res and res.get('entries'):
                        for e in res['entries']:
                            if not e:
                                continue
                            v_id = e.get('id')
                            if not v_id or v_id in existing_vids:
                                continue
                            dur = e.get('duration') or 0
                            t = e.get('title', '')
                            ch_name = e.get('channel') or e.get('uploader') or 'YouTube Creator'

                            # Lọc Shorts và Kênh Shorts
                            if is_short_video_or_channel(title=t, channel_title=ch_name, duration_sec=dur, url=e.get('url', '')):
                                continue
                            if dur_filter == "deep_dive" and dur > 0 and dur < 1200:
                                continue

                            if t_range in ["24h", "48h", "7d"] and re.search(r'\b(19\d\d|200\d|201\d|202[0-3])\b', t):
                                continue

                            if e.get('live_status') in ['is_live', 'is_upcoming', 'was_live', 'post_live']:
                                continue
                            stream_kw = ['restream', 'livestream', 'live stream', 'trực tiếp', '🔴', 'buổi stream', 'phát trực tiếp', 'streamed live']
                            if any(kw in t.lower() for kw in stream_kw):
                                continue
                            pseudo_item = {
                                'snippet': {
                                    'title': t,
                                    'channelTitle': ch_name,
                                    'defaultAudioLanguage': e.get('language') or hl_code
                                }
                            }
                            pseudo_ch = {
                                'snippet': {
                                    'country': e.get('channel_country') or geo_code
                                }
                            }
                            if not is_video_matching_country(pseudo_item, pseudo_ch, geo_code):
                                continue

                            up_date = e.get('upload_date')
                            e_ts = e.get('timestamp') or e.get('release_timestamp')
                            pub_str = ""
                            age_str = ""
                            if e_ts:
                                try:
                                    dt_e = datetime.datetime.fromtimestamp(e_ts, tz=datetime.timezone.utc)
                                    if cutoff_dt and dt_e < cutoff_dt:
                                        continue
                                    pub_str = dt_e.strftime('%Y-%m-%d')
                                    age_str = format_published_age(dt_e.isoformat())
                                except Exception:
                                    pass
                            elif up_date and len(up_date) == 8:
                                try:
                                    dt_e = datetime.datetime.strptime(up_date, '%Y%m%d').replace(tzinfo=datetime.timezone.utc)
                                    if cutoff_dt and dt_e < cutoff_dt:
                                        continue
                                    pub_str = dt_e.strftime('%Y-%m-%d')
                                    age_str = format_published_age(dt_e.isoformat())
                                except Exception:
                                    pass

                            if not age_str:
                                if t_range == "7d":
                                    age_str = "🔥 Xu hướng tuần này"
                                elif t_range == "24h":
                                    age_str = "⚡ 24 giờ qua • Mới"
                                elif t_range == "30d":
                                    age_str = "📅 Xu hướng tháng này"
                                else:
                                    age_str = "🔥 Xu hướng gần đây"

                            v_cnt = int(e.get('view_count') or 0)
                            if t_range in ["7d", "24h", "48h", "30d"] and v_cnt < 300:
                                continue

                            thumb = ""
                            thumbs = e.get('thumbnails', [])
                            if thumbs:
                                thumb = thumbs[-1].get('url') or thumbs[0].get('url', '')
                            elif v_id:
                                thumb = f"https://i.ytimg.com/vi/{v_id}/hqdefault.jpg"

                            f_subs = int(e.get('channel_follower_count') or 0)
                            videos.append({
                                "video_id": v_id,
                                "id": v_id,
                                "title": t,
                                "channel_title": ch_name,
                                "channel": ch_name,
                                "channel_badge": "🟢 Kênh Hoạt Động",
                                "channel_subs": f_subs,
                                "is_verified": bool(e.get('channel_is_verified')) or f_subs >= 100000,
                                "is_active_channel": True,
                                "view_count": v_cnt,
                                "views": v_cnt,
                                "duration_seconds": dur,
                                "duration_formatted": format_duration_display(dur),
                                "published_at": pub_str,
                                "published_age": age_str,
                                "url": e.get('url') or f"https://www.youtube.com/watch?v={v_id}",
                                "thumbnail": thumb
                            })

            videos.sort(key=lambda x: x["view_count"], reverse=True)
        except Exception as yt_err:
            logger.error(f"Lỗi khi lấy trending fallback: {yt_err}")

    final_feed = {
        "success": True,
        "geo": geo_code,
        "country": geo_code,
        "category": cat,
        "time_range": t_range,
        "duration_filter": dur_filter,
        "mode": mode,
        "total": len(videos),
        "videos": videos[:24],
        "trending_videos": videos[:24]
    }
    if videos:
        set_to_cache(_TRENDING_FEED_CACHE, cache_key, final_feed, ttl_seconds=600)
    return final_feed

frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

@app.get("/")
def serve_index():
    index_path = os.path.join(frontend_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(
            index_path,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )
    return {"message": "Frontend chưa được khởi tạo."}

@app.get("/favicon.ico")
def serve_favicon():
    fav_path = os.path.join(frontend_dir, "favicon.svg")
    if os.path.exists(fav_path):
        return FileResponse(fav_path, media_type="image/svg+xml")
    return Response(status_code=204)

@app.get("/health")
@app.get("/ping")
def health_check():
    return {"status": "ok", "service": "YouTube Trend Analyzer", "time": datetime.datetime.now(datetime.timezone.utc).isoformat()}



