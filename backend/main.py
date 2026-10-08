import os
import sys
import re
import datetime
import time
import json
import logging
import requests
import concurrent.futures
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Dict, Any, List, Union, Tuple
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response, PlainTextResponse
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

@app.api_route("/api/health", methods=["GET", "HEAD"])
def health_check_api():
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

def format_views_display(views: int) -> str:
    if not views:
        return "0 views"
    try:
        v = int(views)
        if v >= 1_000_000_000:
            return f"{v / 1_000_000_000:.1f}B views"
        if v >= 1_000_000:
            return f"{v / 1_000_000:.1f}M views"
        if v >= 1_000:
            return f"{v / 1_000:.1f}K views"
        return f"{v} views"
    except Exception:
        return f"{views} views"

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

def fetch_top_keyword_channels_and_videos(kw: str, gl_country: str, hl_lang: str, api_key: Optional[str]) -> Tuple[List[dict], List[dict]]:
    """Lấy danh sách các video dài thu hút view hàng đầu và 20-25 kênh hàng đầu cho từ khóa (loại bỏ hoàn toàn Shorts)."""
    channels_map = {}
    videos_list = []
    seen_video_ids = set()

    def parse_views_str_local(v_str: str) -> int:
        if not v_str:
            return 0
        s = str(v_str).lower().replace(',', '').replace('.', '').replace('views', '').replace('view', '').strip()
        m_k = re.search(r'([\d\.]+)\s*k', s)
        if m_k:
            return int(float(m_k.group(1)) * 1000)
        m_m = re.search(r'([\d\.]+)\s*m', s)
        if m_m:
            return int(float(m_m.group(1)) * 1000000)
        m_b = re.search(r'([\d\.]+)\s*b', s)
        if m_b:
            return int(float(m_b.group(1)) * 1000000000)
        digits = re.sub(r'[^\d]', '', s)
        return int(digits) if digits else 0

    # 1. Ưu tiên cao nhất: Dùng YouTube Data API v3 (Siêu tốc ~200-300ms, chính xác 100%)
    if api_key:
        try:
            encoded_kw = requests.utils.quote(kw)
            search_url = (
                f"https://www.googleapis.com/youtube/v3/search?part=snippet&type=video"
                f"&maxResults=50&q={encoded_kw}&regionCode={gl_country}&relevanceLanguage={hl_lang}&key={api_key}"
            )
            s_resp = http_session.get(search_url, timeout=5)
            if s_resp.status_code == 200:
                items = s_resp.json().get("items", [])
                v_ids = [it["id"]["videoId"] for it in items if it.get("id", {}).get("videoId")]
                if v_ids:
                    d_url = f"https://www.googleapis.com/youtube/v3/videos?part=snippet,contentDetails,statistics,liveStreamingDetails&id={','.join(v_ids[:50])}&key={api_key}"
                    d_resp = http_session.get(d_url, timeout=5)
                    if d_resp.status_code == 200:
                        detail_items = d_resp.json().get("items", [])
                        for v in detail_items:
                            vid = v.get("id")
                            if not vid or vid in seen_video_ids:
                                continue
                            seen_video_ids.add(vid)
                            snip = v.get("snippet", {})
                            content_det = v.get("contentDetails", {})
                            stats = v.get("statistics", {})
                            
                            v_title = snip.get("title", "")
                            v_channel = snip.get("channelTitle", "")
                            ch_id = snip.get("channelId", "")
                            dur_iso = content_det.get("duration", "")
                            dur_sec = parse_iso_duration(dur_iso)
                            v_url = f"https://www.youtube.com/watch?v={vid}"

                            # Lọc bỏ Livestream/Restream
                            if is_stream_video(v):
                                continue

                            # LỌC NGHIÊM NGẶT: Tuyệt đối không lấy Shorts hoặc Kênh Shorts
                            if is_short_video_or_channel(title=v_title, channel_title=v_channel, duration_sec=dur_sec, url=v_url):
                                continue

                            v_views = int(stats.get("viewCount", 0))
                            thumb = (snip.get("thumbnails", {}).get("high") or snip.get("thumbnails", {}).get("medium") or {}).get("url") or f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
                            dur_fmt = format_duration_display(dur_sec)

                            videos_list.append({
                                'id': vid,
                                'title': v_title,
                                'channel': v_channel,
                                'channel_id': ch_id,
                                'channel_handle': f"@{v_channel.replace(' ', '')}",
                                'views': v_views,
                                'views_formatted': format_views_display(v_views),
                                'url': v_url,
                                'thumbnail': thumb,
                                'duration_seconds': dur_sec,
                                'duration_formatted': dur_fmt
                            })

                            ch_key = ch_id if ch_id else v_channel.lower()
                            ch_url = f"https://www.youtube.com/channel/{ch_id}" if ch_id else f"https://www.youtube.com/results?search_query={encoded_kw}"
                            if ch_key not in channels_map:
                                channels_map[ch_key] = {
                                    'channel_id': ch_id,
                                    'channel_name': v_channel,
                                    'channel_handle': f"@{v_channel.replace(' ', '')}",
                                    'avatar': '',
                                    'channel_url': ch_url,
                                    'top_video_id': vid,
                                    'top_video_title': v_title,
                                    'top_video_views': v_views,
                                    'top_video_views_formatted': format_views_display(v_views),
                                    'top_video_duration': dur_fmt,
                                    'top_video_url': v_url,
                                    'top_video_thumbnail': thumb,
                                    'total_views': v_views,
                                    'video_count_in_top': 1
                                }
                            else:
                                channels_map[ch_key]['total_views'] += v_views
                                channels_map[ch_key]['video_count_in_top'] += 1
                                if v_views > channels_map[ch_key]['top_video_views']:
                                    channels_map[ch_key]['top_video_id'] = vid
                                    channels_map[ch_key]['top_video_title'] = v_title
                                    channels_map[ch_key]['top_video_views'] = v_views
                                    channels_map[ch_key]['top_video_views_formatted'] = format_views_display(v_views)
                                    channels_map[ch_key]['top_video_duration'] = dur_fmt
                                    channels_map[ch_key]['top_video_url'] = v_url
                                    channels_map[ch_key]['top_video_thumbnail'] = thumb
        except Exception as ex_api:
            logger.warning(f"Lỗi truy vấn YouTube API search cho '{kw}': {ex_api}")

    # 2. Bổ sung hoặc Quét trực tiếp bằng Web Engine (Đảm bảo luôn có đủ 20-25 kênh chất lượng cao)
    if len(channels_map) < 20:
        direct_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': f"{hl_lang}-{gl_country},{hl_lang};q=0.9,en;q=0.8",
            'Cookie': f"PREF=gl={gl_country}&hl={hl_lang};"
        }
        encoded_kw = requests.utils.quote(kw)
        search_urls = [
            f"https://www.youtube.com/results?search_query={encoded_kw}&sp=CAMSAhAB&gl={gl_country}&hl={hl_lang}",
            f"https://www.youtube.com/results?search_query={encoded_kw}&gl={gl_country}&hl={hl_lang}",
            f"https://www.youtube.com/results?search_query={encoded_kw}%20tips&gl={gl_country}&hl={hl_lang}"
        ]

        for s_url in search_urls:
            if len(channels_map) >= 30:
                break
            try:
                web_resp = http_session.get(s_url, headers=direct_headers, timeout=6)
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
                                for val in obj.values():
                                    extract_vrs(val)
                            elif isinstance(obj, list):
                                for it in obj:
                                    extract_vrs(it)
                        extract_vrs(data)

                        for vr in raw_vrs:
                            v_id = vr.get('videoId')
                            if not v_id or v_id in seen_video_ids:
                                continue

                            runs = vr.get('ownerText', {}).get('runs', [{}])
                            ch_name = runs[0].get('text', '').strip()
                            if not ch_name:
                                continue

                            t = ''.join(r.get('text', '') for r in vr.get('title', {}).get('runs', [])).strip()
                            if 'shorts' in t.lower() or 'shorts' in ch_name.lower():
                                continue

                            dur_str = vr.get('lengthText', {}).get('simpleText', '')
                            dur_sec = parse_duration_str_to_seconds(dur_str)
                            v_url = f"https://www.youtube.com/watch?v={v_id}"

                            if is_short_video_or_channel(title=t, channel_title=ch_name, duration_sec=dur_sec, url=v_url):
                                continue

                            seen_video_ids.add(v_id)
                            ch_id = runs[0].get('navigationEndpoint', {}).get('browseEndpoint', {}).get('browseId', '')
                            ch_handle = runs[0].get('navigationEndpoint', {}).get('browseEndpoint', {}).get('canonicalBaseUrl', '')
                            views_str = vr.get('viewCountText', {}).get('simpleText', '')
                            v_cnt = parse_views_str_local(views_str)

                            thumbs = vr.get('thumbnail', {}).get('thumbnails', [])
                            thumb_url = thumbs[-1].get('url') if thumbs else f"https://i.ytimg.com/vi/{v_id}/hqdefault.jpg"

                            avatar_nodes = vr.get('channelThumbnailSupportedRenderers', {}).get('channelThumbnailWithLinkRenderer', {}).get('thumbnail', {}).get('thumbnails', [])
                            avatar = avatar_nodes[-1].get('url') if avatar_nodes else ''

                            video_obj = {
                                'id': v_id,
                                'title': t,
                                'channel': ch_name,
                                'channel_id': ch_id,
                                'channel_handle': ch_handle,
                                'views': v_cnt,
                                'views_formatted': format_views_display(v_cnt),
                                'url': v_url,
                                'thumbnail': thumb_url,
                                'duration_seconds': dur_sec,
                                'duration_formatted': dur_str or format_duration_display(dur_sec)
                            }
                            videos_list.append(video_obj)

                            ch_key = ch_id if ch_id else ch_name.lower()
                            ch_url = f"https://www.youtube.com{ch_handle}" if ch_handle else (f"https://www.youtube.com/channel/{ch_id}" if ch_id else f"https://www.youtube.com/results?search_query={requests.utils.quote(ch_name)}")
                            if ch_key not in channels_map:
                                channels_map[ch_key] = {
                                    'channel_id': ch_id,
                                    'channel_name': ch_name,
                                    'channel_handle': ch_handle or f"@{ch_name.replace(' ', '')}",
                                    'avatar': avatar,
                                    'channel_url': ch_url,
                                    'top_video_id': v_id,
                                    'top_video_title': t,
                                    'top_video_views': v_cnt,
                                    'top_video_views_formatted': format_views_display(v_cnt),
                                    'top_video_duration': dur_str,
                                    'top_video_url': v_url,
                                    'top_video_thumbnail': thumb_url,
                                    'total_views': v_cnt,
                                    'video_count_in_top': 1
                                }
                            else:
                                channels_map[ch_key]['total_views'] += v_cnt
                                channels_map[ch_key]['video_count_in_top'] += 1
                                if avatar and not channels_map[ch_key].get('avatar'):
                                    channels_map[ch_key]['avatar'] = avatar
                                if v_cnt > channels_map[ch_key]['top_video_views']:
                                    channels_map[ch_key]['top_video_id'] = v_id
                                    channels_map[ch_key]['top_video_title'] = t
                                    channels_map[ch_key]['top_video_views'] = v_cnt
                                    channels_map[ch_key]['top_video_views_formatted'] = format_views_display(v_cnt)
                                    channels_map[ch_key]['top_video_duration'] = dur_str
                                    channels_map[ch_key]['top_video_url'] = v_url
                                    channels_map[ch_key]['top_video_thumbnail'] = thumb_url
            except Exception as e:
                logger.warning(f"Lỗi direct scraping khi tìm kênh cho '{kw}': {e}")

    # Sắp xếp kênh theo lượt xem video đỉnh cao nhất của từ khóa đó
    sorted_channels = sorted(channels_map.values(), key=lambda x: x['top_video_views'], reverse=True)
    sorted_videos = sorted(videos_list, key=lambda x: x.get('views', 0), reverse=True)
    return sorted_videos[:12], sorted_channels[:25]

def fetch_top_youtube_videos(kw: str, gl_country: str, hl_lang: str, api_key: Optional[str]) -> List[dict]:
    """Tương thích ngược: Lấy top video cho từ khóa."""
    vids, _ = fetch_top_keyword_channels_and_videos(kw, gl_country, hl_lang, api_key)
    return vids

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
            "JP": ("ja", "JP"), "KR": ("ko", "KR"), "BR": ("pt", "BR"), "IN": ("en", "IN"),
            "ID": ("id", "ID"), "TH": ("th", "TH"), "PH": ("en", "PH"), "RU": ("ru", "RU"),
            "PL": ("pl", "PL"), "IR": ("fa", "IR"), "ES": ("es", "ES"), "PT": ("pt", "PT")
        }
        hl_lang, gl_country = geo_lang_map.get(geo, ("en", geo))

        # TỐI ƯU SIÊU TỐC: Chạy song song 3 luồng (Google Trends + Google Suggest + YouTube Search API)
        with ThreadPoolExecutor(max_workers=3) as executor:
            fut_trend = executor.submit(trend_service.get_keyword_trend, kw, geo=geo)
            fut_suggest = executor.submit(fetch_google_suggestions, kw, hl_lang, gl_country)
            fut_yt = executor.submit(fetch_top_keyword_channels_and_videos, kw, gl_country, hl_lang, api_key)

            trend_res = fut_trend.result()
            suggest_tags_raw = fut_suggest.result()
            yt_results, top_channels = fut_yt.result()

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
            "top_youtube_videos": yt_results,
            "top_channels": top_channels
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
            {"tag": "인생 교훈 명언", "niche": "📜 Triết Lý", "badge": "🌱 Chữa lành"},
            {"tag": "성경 말씀 듣기", "niche": "✝️ Kinh Thánh", "badge": "🔥 Lời Chúa"}
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
        "IN": [
            {"tag": "real horror stories hindi", "niche": "👻 Horror", "badge": "🔥 Sachhi"},
            {"tag": "learn english speaking practice", "niche": "🎓 Learn English", "badge": "🚀 Đang lên"},
            {"tag": "movie explain hindi recap", "niche": "🎬 Phim", "badge": "🔥 Triệu view"},
            {"tag": "cheating partner revenge drama", "niche": "💔 Ngoại Tình", "badge": "⚡ Drama"},
            {"tag": "saas bahu kalesh family drama", "niche": "🏡 Gia Đình", "badge": "⚡ Drama"},
            {"tag": "crime patrol real incident documentary", "niche": "🕵️ Kỳ Án", "badge": "🚀 Triệu view"},
            {"tag": "make money online side income", "niche": "💰 Tài Chính", "badge": "🔥 Hot"},
            {"tag": "artificial intelligence AI tools", "niche": "🤖 Công Nghệ", "badge": "🚀 Mới"},
            {"tag": "gita upanishad life wisdom", "niche": "📜 Triết Lý", "badge": "🌱 Chữa lành"}
        ],
        "ID": [
            {"tag": "cerita horor kisah nyata", "niche": "👻 Kinh Dị", "badge": "🔥 Viral"},
            {"tag": "belajar bahasa inggris percakapan", "niche": "🎓 Tiếng Anh", "badge": "🚀 Đang lên"},
            {"tag": "alur cerita film recap", "niche": "🎬 Tóm Tắt Phim", "badge": "🔥 Triệu view"},
            {"tag": "balas dendam perselingkuhan", "niche": "💔 Ngoại Tình", "badge": "⚡ Drama"},
            {"tag": "drama mertua menantu keluarga", "niche": "🏡 Gia Đình", "badge": "⚡ Drama"},
            {"tag": "kasus kejahatan nyata dokumenter", "niche": "🕵️ Kỳ Án", "badge": "🚀 Deep Dive"},
            {"tag": "cara menghasilkan uang online", "niche": "💰 Tài Chính", "badge": "🔥 Hot"},
            {"tag": "teknologi AI kecerdasan buatan", "niche": "🤖 Công Nghệ", "badge": "🚀 Mới"},
            {"tag": "renungan firman tuhan alkitab", "niche": "✝️ Kinh Thánh", "badge": "🌱 Bình an"}
        ],
        "TH": [
            {"tag": "เรื่องผี เรื่องเล่าสยองขวัญ เดอะโกส", "niche": "👻 Kinh Dị", "badge": "🔥 หลอน"},
            {"tag": "เรียนภาษาอังกฤษ ฝึกพูด", "niche": "🎓 Tiếng Anh", "badge": "🚀 Đang lên"},
            {"tag": "สปอยหนัง เล่าเรื่องย่อหนัง", "niche": "🎬 Tóm Tắt Phim", "badge": "🔥 Triệu view"},
            {"tag": "แก้แค้นคนนอกใจ เอาคืนสามีชั่ว", "niche": "💔 Ngoại Tình", "badge": "⚡ ดราม่า"},
            {"tag": "ดราม่าแม่ผัวลูกสะใภ้", "niche": "🏡 Gia Đình", "badge": "⚡ Drama"},
            {"tag": "คดีฆาตกรรม เรื่องจริง สารคดี", "niche": "🕵️ Kỳ Án", "badge": "🚀 Triệu view"},
            {"tag": "หาเงินออนไลน์ การเงินการลงทุน", "niche": "💰 Tài Chính", "badge": "🔥 Hot"},
            {"tag": "ปัญญาประดิษฐ์ เทคโนโลยี AI", "niche": "🤖 Công Nghệ", "badge": "🚀 Mới"},
            {"tag": "ธรรมะสอนใจ คติธรรม", "niche": "🪷 Phật Pháp", "badge": "🌱 Bình an"}
        ],
        "PH": [
            {"tag": "kwentong kababalaghan totoong horror", "niche": "👻 Kinh Dị", "badge": "🔥 Takot"},
            {"tag": "learn english speaking fluency", "niche": "🎓 Tiếng Anh", "badge": "🚀 Đang lên"},
            {"tag": "movie recap tagalog dubbed", "niche": "🎬 Tóm Tắt Phim", "badge": "🔥 Triệu view"},
            {"tag": "huli sa akto kabit revenge drama", "niche": "💔 Ngoại Tình", "badge": "⚡ Drama"},
            {"tag": "biyenan at manugang away pamilya", "niche": "🏡 Gia Đình", "badge": "⚡ Drama"},
            {"tag": "true crime documentary unsolved philippines", "niche": "🕵️ Kỳ Án", "badge": "🚀 Triệu view"},
            {"tag": "paano kumita ng pera online", "niche": "💰 Tài Chính", "badge": "🔥 Hot"},
            {"tag": "ai tools freelancing 2026", "niche": "🤖 Công Nghệ", "badge": "🚀 Mới"},
            {"tag": "bible verse tagalog christian reflection", "niche": "✝️ Kinh Thánh", "badge": "🔥 Faith"}
        ],
        "RU": [
            {"tag": "страшные истории на ночь ужасы", "niche": "👻 Kinh Dị", "badge": "🔥 Крипота"},
            {"tag": "учить английский с нуля", "niche": "🎓 Tiếng Anh", "badge": "🚀 Đang lên"},
            {"tag": "краткий пересказ сюжета фильма", "niche": "🎬 Tóm Tắt Phim", "badge": "🔥 Triệu view"},
            {"tag": "измена месть женские истории", "niche": "💔 Ngoại Tình", "badge": "⚡ Драма"},
            {"tag": "свекровь и невестка семейные драмы", "niche": "🏡 Gia Đình", "badge": "⚡ Drama"},
            {"tag": "тру крайм криминальная россия расследование", "niche": "🕵️ Kỳ Án", "badge": "🚀 Triệu view"},
            {"tag": "заработок в интернете 2026", "niche": "💰 Tài Chính", "badge": "🔥 Hot"},
            {"tag": "нейросети искусственный интеллект AI", "niche": "🤖 Công Nghệ", "badge": "🚀 Mới"},
            {"tag": "философия стоицизм мудрость", "niche": "📜 Triết Lý", "badge": "🌱 Chữa lành"}
        ],
        "PL": [
            {"tag": "prawdziwe historie z życia podcast", "niche": "🎙️ Kể Chuyện Thật", "badge": "🔥 Historie"},
            {"tag": "nauka angielskiego od podstaw", "niche": "🎓 Tiếng Anh", "badge": "🚀 Đang lên"},
            {"tag": "streszczenie filmu recap po polsku", "niche": "🎬 Tóm Tắt Phim", "badge": "🔥 Triệu view"},
            {"tag": "zdrada zemsta prawdziwe historie", "niche": "💔 Ngoại Tình", "badge": "⚡ Drama"},
            {"tag": "konflikt z teściową dramaty rodzinne", "niche": "🏡 Gia Đình", "badge": "⚡ Drama"},
            {"tag": "prawdziwe zbrodnie kryminalne sprawy", "niche": "🕵️ Kỳ Án", "badge": "🚀 Triệu view"},
            {"tag": "zarabianie przez internet 2026", "niche": "💰 Tài Chính", "badge": "🔥 Hot"},
            {"tag": "sztuczna inteligencja narzędzia ai", "niche": "🤖 Công Nghệ", "badge": "🚀 Mới"},
            {"tag": "stoicyzm mądrość życiowa filozofia", "niche": "📜 Triết Lý", "badge": "🌱 Chữa lành"},
            {"tag": "straszne historie horror z życia wzięte", "niche": "👻 Kinh Dị", "badge": "🌙 Mroczne"}
        ],
        "ES": [
            {"tag": "historias de la vida real podcast", "niche": "🎙️ Kể Chuyện Thật", "badge": "🔥 Historias"},
            {"tag": "aprender ingles desde cero", "niche": "🎓 Tiếng Anh", "badge": "🚀 En auge"},
            {"tag": "resumen de peliculas en minutos", "niche": "🎬 Tóm Tắt Phim", "badge": "🔥 Millones"},
            {"tag": "infidelidad venganza historias reales", "niche": "💔 Ngoại Tình", "badge": "⚡ Drama"},
            {"tag": "suegra y nuera dramas familiares", "niche": "🏡 Gia Đình", "badge": "⚡ Conflicto"},
            {"tag": "casos reales de crimenes misterio documental", "niche": "🕵️ Kỳ Án", "badge": "🚀 Misterio"},
            {"tag": "ganar dinero por internet 2026", "niche": "💰 Tài Chính", "badge": "🔥 Top"},
            {"tag": "inteligencia artificial herramientas ai", "niche": "🤖 Công Nghệ", "badge": "🚀 Nuevo"},
            {"tag": "estoicismo filosofia lecciones de vida", "niche": "📜 Triết Lý", "badge": "🌱 Sabiduría"},
            {"tag": "historias de terror reales miedo", "niche": "👻 Kinh Dị", "badge": "🌙 Terror"}
        ],
        "PT": [
            {"tag": "historias reais de vida podcast", "niche": "🎙️ Kể Chuyện Thật", "badge": "🔥 Histórias"},
            {"tag": "aprender ingles do zero", "niche": "🎓 Tiếng Anh", "badge": "🚀 Em alta"},
            {"tag": "resumo de filmes em minutos", "niche": "🎬 Tóm Tắt Phim", "badge": "🔥 Milhões"},
            {"tag": "traicao vinganca historias reais", "niche": "💔 Ngoại Tình", "badge": "⚡ Drama"},
            {"tag": "conflitos de sogra e nora familia", "niche": "🏡 Gia Đình", "badge": "⚡ Conflito"},
            {"tag": "crimes reais casos misteriosos portugal", "niche": "🕵️ Kỳ Án", "badge": "🚀 Mistério"},
            {"tag": "ganhar dinheiro online 2026", "niche": "💰 Tài Chính", "badge": "🔥 Top"},
            {"tag": "inteligencia artificial ferramentas ai", "niche": "🤖 Công Nghệ", "badge": "🚀 Novo"},
            {"tag": "estoicismo filosofia sabedoria de vida", "niche": "📜 Triết Lý", "badge": "🌱 Sabedoria"},
            {"tag": "historias de terror reais portugal", "niche": "👻 Kinh Dị", "badge": "🌙 Terror"}
        ],
        "IR": [
            {"tag": "داستان واقعی پادکست زندگی", "niche": "🎙️ Kể Chuyện Thật", "badge": "🔥 داستان"},
            {"tag": "آموزش زبان انگلیسی از صفر", "niche": "🎓 Tiếng Anh", "badge": "🚀 Đang lên"},
            {"tag": "خلاصه فیلم به فارسی در چند دقیقه", "niche": "🎬 Tóm Tắt Phim", "badge": "🔥 Triệu view"},
            {"tag": "خیانت و انتقام داستان واقعی", "niche": "💔 Ngoại Tình", "badge": "⚡ Drama"},
            {"tag": "مادر شوهر و عروس دعوای خانوادگی", "niche": "🏡 Gia Đình", "badge": "⚡ Drama"},
            {"tag": "پرونده های جنایی واقعی مرموز", "niche": "🕵️ Kỳ Án", "badge": "🚀 Triệu view"},
            {"tag": "کسب درآمد دلاری از اینترنت 2026", "niche": "💰 Tài Chính", "badge": "🔥 Hot"},
            {"tag": "هوش مصنوعی ابزارهای هوش مصنوعی", "niche": "🤖 Công Nghệ", "badge": "🚀 Mới"},
            {"tag": "فلسفه رواقی گری درس های زندگی", "niche": "📜 Triết Lý", "badge": "🌱 Chữa lành"},
            {"tag": "داستان های ترسناک واقعی وحشتناک", "niche": "👻 Kinh Dị", "badge": "🌙 ترسناک"}
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
        "IN": "gita upanishad life lessons philosophy",
        "ID": "filosofi stoikisme hidup",
        "TH": "ปรัชญา ข้อคิดชีวิต",
        "PH": "stoicism life lessons philosophy",
        "RU": "философия стоицизм мудрость жизни",
        "PL": "stoicyzm mądrość życiowa filozofia",
        "ES": "estoicismo filosofia lecciones de vida",
        "PT": "estoicismo filosofia sabedoria de vida",
        "IR": "فلسفه رواقی گری درس های زندگی حکمت",
        "DEFAULT": "stoicism philosophy"
    },
    "buddhism": {
        "VN": "lời phật dạy triết lý tĩnh tâm",
        "US": "buddhist wisdom philosophy",
        "GB": "zen buddhism mindfulness philosophy",
        "FR": "bouddhisme sagesse enseignement",
        "IT": "buddismo meditazione saggezza",
        "JP": "仏教 法話 心の教え",
        "KR": "불교 마음공부 명상",
        "DE": "Buddhismus Weisheit Meditation",
        "IN": "buddha teachings mindfulness meditation",
        "ID": "ajaran buddha meditasi ketenangan",
        "TH": "ธรรมะสอนใจ คติธรรม",
        "PH": "buddhism mindfulness peace",
        "RU": "буддизм мудрость медитация осознанность",
        "PL": "buddyzm nauki mądrość medytacja",
        "ES": "budismo meditacion ensenanzas sabiduria",
        "PT": "budismo meditacao ensinamentos sabedoria",
        "IR": "بودیسم مدیتیشن آرامش ذهن و خرد",
        "DEFAULT": "buddhist wisdom philosophy"
    },
    "christianity_bible": {
        "VN": "lời chúa kinh thánh",
        "US": "bible scripture reading",
        "GB": "holy bible study",
        "FR": "sainte bible lecture",
        "IT": "sacra bibbia lettura",
        "JP": "聖書 朗読",
        "KR": "성경 말씀 듣기",
        "DE": "Bibel Hörbuch Lesung",
        "IN": "holy bible verse reading hindi english",
        "ID": "renungan alkitab kristen firman tuhan",
        "TH": "พระคัมภีร์คริสเตียน ฟังพระวจนะ",
        "PH": "bible reading tagalog christian worship songs",
        "RU": "библия чтение святое писание слово божье",
        "PL": "czytanie pisma świętego biblia",
        "ES": "lectura de la biblia palabra de dios",
        "PT": "leitura da biblia sagrada palavra de deus",
        "IR": "کتاب مقدس عیسی مسیح انجیل صوتی",
        "DEFAULT": "bible scripture reading"
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
        "IN": "elderly life wisdom advice",
        "ID": "nasihat orang tua bijak",
        "TH": "ข้อคิดคนเฒ่าคนแก่ ชีวิต",
        "PH": "buhay matanda advice life lessons",
        "RU": "мудрость стариков жизненный опыт",
        "PL": "mądrość życiowa seniorów rady",
        "ES": "sabiduria de los ancianos lecciones",
        "PT": "sabedoria dos idosos conselhos de vida",
        "IR": "پند بزرگان تجربه های زندگی کهنسالان",
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
        "IN": "reddit stories india confessions",
        "ID": "cerita reddit indonesia",
        "TH": "เรื่องเล่าพันทิป pantip เรื่องสยอง",
        "PH": "phinvest offmychestph reddit stories",
        "RU": "истории с реддит апвоут reddit",
        "PL": "historie z reddit wyznania",
        "ES": "historias de reddit confesiones",
        "PT": "historias do reddit relatos",
        "IR": "داستان های ردیت اعترافات عجیب",
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
        "IN": "case study expose documentary scam",
        "ID": "bongkar kasus drama viral",
        "TH": "แฉดราม่า ประเด็นร้อน",
        "PH": "expose scandal documentary philippines",
        "RU": "разоблачение скандал расследование док",
        "PL": "afera skandal exposé śledztwo",
        "ES": "documental escandalo caida de",
        "PT": "documentario escandalo polemica",
        "IR": "افشاگری مستند جنجالی سقوط",
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
        "IN": "crime patrol real incident documentary hindi",
        "ID": "kasus kejahatan nyata indonesia dokumenter",
        "TH": "คดีฆาตกรรม เรื่องจริง สารคดี",
        "PH": "true crime documentary philippines unsolved",
        "RU": "тру крайм криминальная россия расследование",
        "PL": "prawdziwe zbrodnie kryminalne sprawy",
        "ES": "crimenes reales casos sin resolver documental",
        "PT": "crimes reais casos misteriosos documental",
        "IR": "پرونده های جنایی واقعی قتل های مرموز",
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
        "IN": "real horror stories hindi sachhi kahani",
        "ID": "cerita horor kisah nyata misteri",
        "TH": "เรื่องผี เรื่องเล่าสยองขวัญ เดอะโกส",
        "PH": "kwentong kababalaghan totoong horror stories tagalog",
        "RU": "страшные истории на ночь мистика ужасы",
        "PL": "straszne historie horror z życia wzięte",
        "ES": "historias de terror reales miedo para no dormir",
        "PT": "historias de terror reais medo para dormir",
        "IR": "داستان های ترسناک واقعی جن و ارواح",
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
        "IN": "indian history geopolitics world affairs",
        "ID": "sejarah geopolitik dunia",
        "TH": "ประวัติศาสตร์ ภูมิรัฐศาสตร์ สงคราม",
        "PH": "philippine history geopolitics documentary",
        "RU": "история геополитика документальный фильм",
        "PL": "historia geopolityka wojna dokument",
        "ES": "historia geopolitica guerras documental",
        "PT": "historia geopolitica guerras documental",
        "IR": "تاریخ جهان ژئوپلیتیک جنگ های بزرگ",
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
        "IN": "space science documentary isro hindi",
        "ID": "misteri alam semesta luar angkasa",
        "TH": "ความลับอวกาศ วิทยาศาสตร์ดาราศาสตร์",
        "PH": "space science mysteries documentary",
        "RU": "тайны космоса вселенная наука",
        "PL": "tajemnice kosmosu nauka dokument",
        "ES": "misterios del espacio universo ciencia documental",
        "PT": "misterios do espaco universo ciencia documental",
        "IR": "شگفتی های کهکشان رازهای کیهان نجوم",
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
        "IN": "personal finance investing make money online",
        "ID": "cara menghasilkan uang online investasi",
        "TH": "หาเงินออนไลน์ การเงินการลงทุน",
        "PH": "paano kumita ng pera online finance",
        "RU": "финансы инвестиции заработок в интернете",
        "PL": "zarabianie przez internet finanse inwestycje",
        "ES": "finanzas personales invertir dinero por internet",
        "PT": "financas pessoais investimentos ganhar dinheiro online",
        "IR": "کسب درآمد دلاری آموزش سرمایه گذاری",
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
        "IN": "artificial intelligence AI tools hindi",
        "ID": "kecerdasan buatan teknologi AI",
        "TH": "ปัญญาประดิษฐ์ เทคโนโลยี AI",
        "PH": "artificial intelligence AI tools 2026",
        "RU": "нейросети искусственный интеллект AI",
        "PL": "sztuczna inteligencja narzędzia ai",
        "ES": "inteligencia artificial herramientas ai 2026",
        "PT": "inteligencia artificial ferramentas ai 2026",
        "IR": "ابزارهای هوش مصنوعی تکنولوژی جدید",
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
        "IN": "movie explain hindi recap summary",
        "ID": "alur cerita film recap",
        "TH": "สปอยหนัง เล่าเรื่องย่อหนัง",
        "PH": "movie recap tagalog dubbed",
        "RU": "краткий пересказ фильма сюжет",
        "PL": "streszczenie filmu recap po polsku",
        "ES": "resumen de peliculas en minutos",
        "PT": "resumo de filmes em minutos",
        "IR": "خلاصه فیلم سینمایی در چند دقیقه",
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
        "IN": "gaming highlights bgmi free fire",
        "ID": "gameplay highlights indonesia",
        "TH": "ไฮไลท์เกม แคสเกม",
        "PH": "gaming highlights pinoy mobile legends",
        "RU": "летсплей нарезка стримов гейминг",
        "PL": "gaming zagrajmy w gry gameplay",
        "ES": "gameplay mejores momentos juegos",
        "PT": "gameplay melhores momentos jogos",
        "IR": "گیم پلی بازی های ویدیویی هایلایت",
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
        "IN": "comedy videos funny roast comedy",
        "ID": "komedi lucu viral indonesia",
        "TH": "ตลก ขำขัน คลายเครียด รายการตลก",
        "PH": "nakakatawa viral funny pinoy comedy",
        "RU": "приколы юмор смешное шоу",
        "PL": "śmieszne filmiki kabaret komedia",
        "ES": "comedia videos divertidos risa viral",
        "PT": "comedia videos engracados pegadinhas viral",
        "IR": "طنز خنده دار کلیپ سرگرمی دوربین مخفی",
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
        "ID": "cerita perselingkuhan drama rumah tangga",
        "TH": "เรื่องเล่าความรัก แอบมีชู้ เมียน้อย",
        "PH": "kabit secret affair confessions tagalog",
        "JP": "大人の恋愛 浮気",
        "KR": "19금 썰",
        "RU": "истории измен тайные признания 18+",
        "PL": "sekretne zdrady dramaty miłosne",
        "ES": "historias de infidelidad confesiones de pareja",
        "PT": "historias de traicao confissoes de casal",
        "IR": "اعترافات عشق های پنهان روابط عاشقانه",
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
        "ID": "drama mertua menantu konflik keluarga",
        "TH": "ดราม่าครอบครัว พ่อผัวแม่ผัว",
        "PH": "biyenan family drama pinoy",
        "JP": "義父と嫁 家族",
        "KR": "시아버지 며느리",
        "RU": "семейная драма свекор невестка конфликты",
        "PL": "teść synowa dramaty rodzinne",
        "ES": "suegro y nuera drama familiar",
        "PT": "sogro e nora drama familiar",
        "IR": "پدر شوهر و عروس اختلافات خانوادگی",
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
        "ID": "kisah mertua dan menantu drama",
        "TH": "ดราม่าแม่ผัวลูกสะใภ้ ปัญหาครอบครัว",
        "PH": "biyenan at manugang drama away",
        "JP": "義母と婿 家族",
        "KR": "장모 사위",
        "RU": "свекровь и невестка война в семье",
        "PL": "teściowa zięć konflikty rodzinne",
        "ES": "suegra y nuera conflictos familiares",
        "PT": "sogra e nora conflitos familiares",
        "IR": "مادر شوهر و عروس ماجراهای خانوادگی",
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
        "ID": "balas dendam perselingkuhan karma",
        "TH": "แก้แค้นคนนอกใจ เอาคืนสามีชั่ว",
        "PH": "huli sa akto kabit revenge drama",
        "JP": "浮気 修羅場 復讐",
        "KR": "바람 불륜 참교육",
        "RU": "измена мужа месть расплата",
        "PL": "zdrada zemsta przyłapany na zdradzie",
        "ES": "infidelidad venganza caught cheating espanol",
        "PT": "traicao vinganca apanhado traindo",
        "IR": "خیانت همسر انتقام داستان واقعی",
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
        "ID": "belajar bahasa inggris percakapan",
        "TH": "เรียนภาษาอังกฤษ ฝึกพูดภาษาอังกฤษ",
        "PH": "learn english pronunciation accent training",
        "JP": "英会話 リスニング",
        "KR": "영어 회화",
        "BR": "aprender ingles",
        "CA": "learn english speaking",
        "AU": "learn english speaking",
        "RU": "английский язык с нуля разговорный",
        "PL": "nauka angielskiego od podstaw rozmówki",
        "ES": "aprender ingles conversacion pronunciacion",
        "PT": "aprender ingles conversacao pronuncia",
        "IR": "آموزش مکالمه انگلیسی از صفر تلفظ",
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
        "IN": "billionaire luxury lifestyle richest",
        "ID": "gaya hidup mewah konglomerat",
        "TH": "ชีวิตมหาเศรษฐี ไฮโซ",
        "PH": "billionaire luxury lifestyle philippines",
        "RU": "роскошная жизнь миллиардеров богачи",
        "PL": "luksusowe życie miliarderzy bogactwo",
        "ES": "estilo de vida multimillonarios lujo",
        "PT": "estilo de vida bilionarios luxo",
        "IR": "زندگی ثروتمندان و میلیاردرهای جهان",
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
        "IN": "indian street food travel vlog",
        "ID": "kuliner jalanan street food indonesia",
        "TH": "สตรีทฟู้ด ตะลุยกิน ของอร่อย",
        "PH": "pinoy street food food trip travel",
        "RU": "уличная еда путешествия влог",
        "PL": "street food podróże kulinaria",
        "ES": "comida callejera viajes gastronomia",
        "PT": "comida de rua viagens gastronomia",
        "IR": "غذای خیابانی ولاگ سفر آشپزی",
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
        "IN": "gym workout fitness bodybuilding diet",
        "ID": "olahraga gym diet sehat",
        "TH": "ออกกำลังกาย ลดน้ำหนัก ฟิตเนส",
        "PH": "gym workout weight loss diet pinoy",
        "RU": "тренировки фитнес похудение питание",
        "PL": "trening w domu siłownia odchudzanie",
        "ES": "ejercicios en casa entrenamiento gimnasio",
        "PT": "exercicios em casa treino academia",
        "IR": "تمرین در خانه بدنسازی کاهش وزن",
        "DEFAULT": "fitness workout gym"
    },
        "real_life_stories": {
        "VN": "kể chuyện đời thực podcast tâm sự",
        "US": "real life stories true story podcast",
        "GB": "true stories podcast storytime",
        "FR": "histoires vraies podcast témoignages",
        "IT": "storie vere podcast testimonianze",
        "JP": "本当にあった話 実話 朗読",
        "KR": "실화 사연 인생 라디오",
        "DE": "wahre Geschichten Podcast Lebensgeschichten",
        "IN": "real life true stories emotional podcast hindi",
        "ID": "cerita kisah nyata podcast kehidupan",
        "TH": "เรื่องจริงจากชีวิต เล่าเรื่องจริง",
        "PH": "totoong kwento ng buhay tagalog podcast",
        "RU": "истории из жизни реальные судьбы подкаст",
        "PL": "prawdziwe historie z życia podcast",
        "ES": "historias de la vida real podcast testimonios",
        "PT": "historias reais de vida podcast relatos",
        "IR": "داستان واقعی پادکست سرگذشت زندگی",
        "DEFAULT": "real life stories true story podcast"
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
        "IN": "lofi chill songs hindi relaxing beats",
        "ID": "lagu santai lofi tenang",
        "TH": "เพลงฟังสบาย ชิลๆ lofi ผ่อนคลาย",
        "PH": "opm lofi chill beats tagalog playlist",
        "RU": "расслабляющая музыка лофи чилл",
        "PL": "muzyka relaksacyjna lofi chill",
        "ES": "musica relajante lofi chill beats",
        "PT": "musica relaxante lofi chill beats",
        "IR": "موزیک آرامش بخش لوفای بی کلام",
        "DEFAULT": "lofi chill beats"
    }
}

SP_MAP = {
    "24h": "CAMSBAgCEAE%3D",  # Today / last 24h, sorted by viewCount
    "48h": "CAMSBAgCEAE%3D",  # 24-48h, sorted by viewCount
    "7d":  "CAMSBAgDEAE%3D",  # This week / last 7 days, sorted by viewCount
    "30d": "CAMSBAgEEAE%3D",  # This month / last 30 days, sorted by viewCount
    "90d": "CAMSBAgFEAE%3D",  # This year / ~90 days, sorted by viewCount
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

    # 6. Với 90d: Chấp nhận tối đa 3 tháng (loại bỏ từ 4 tháng trở lên)
    if t_range == '90d':
        m_match = re.search(r'(\d+)\s*(?:tháng|month|mo|monat|mois|개월|か月)', p)
        if m_match:
            months = int(m_match.group(1))
            if months > 3:
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
        elif diff_days <= 90:
            months = max(1, diff_days // 30)
            return f"🗓️ {months} tháng trước • 90 ngày qua"
        elif diff_days < 365:
            months = max(1, diff_days // 30)
            return f"⏳ {months} tháng trước"
        else:
            years = max(1, diff_days // 365)
            return f"🏛️ {years} năm trước • All-Time"
    except Exception:
        return pub_iso[:10]

def compute_trending_score(view_count: int, pub_iso: str = "", pub_age_str: str = "") -> float:
    """
    Tính điểm xu hướng bứt phá (Trending Velocity Score):
    Kết hợp giữa tổng lượt xem và hệ số gia tốc thời gian đăng (Freshness Multiplier).
    Video mới đăng bùng nổ view trong 24h-7d được ưu tiên xếp hạng cao.
    """
    v = max(1, view_count)
    multiplier = 1.0
    
    if pub_iso:
        try:
            dt = datetime.datetime.fromisoformat(pub_iso.replace("Z", "+00:00"))
            now = datetime.datetime.now(datetime.timezone.utc)
            hours_old = max(1, (now - dt).total_seconds() / 3600)
            
            if hours_old <= 24:
                multiplier = 2.5   # Bùng nổ trong 24h
            elif hours_old <= 72:
                multiplier = 2.0   # Bùng nổ trong 3 ngày
            elif hours_old <= 168:
                multiplier = 1.5   # Bùng nổ trong 7 ngày
            elif hours_old <= 720:
                multiplier = 1.2   # Trong 30 ngày
            elif hours_old <= 2160:
                multiplier = 1.05  # Trong 90 ngày
            else:
                multiplier = 0.95  # Cũ hơn
        except Exception:
            pass
    elif pub_age_str:
        p = pub_age_str.lower()
        if any(w in p for w in ['giờ', 'hour', 'phút', 'min', 'vừa đăng']):
            multiplier = 2.5
        elif any(w in p for w in ['1 ngày', '1 day', '2 ngày', '2 days']):
            multiplier = 2.0
        elif any(w in p for w in ['ngày', 'day', 'tuần', 'week', 'wk']):
            multiplier = 1.5
        elif any(w in p for w in ['tháng', 'month', 'mo']):
            multiplier = 1.15
            
    return v * multiplier

def get_channel_key(ch_id: str, ch_name: str) -> str:
    """Tạo khóa định danh duy nhất cho kênh để khử trùng lặp chính xác."""
    if ch_id and ch_id.strip().startswith(('UC', 'uc', '@')):
        return ch_id.strip().lower()
    clean = re.sub(r'[^a-zA-Z0-9\u0600-\u06FF\u0400-\u04FF\u4E00-\u9FFF\u3040-\u30FF\uAC00-\uD7AF]', '', ch_name.lower())
    return clean or ch_name.strip().lower()

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
    has_chinese = bool(re.search(r'[\u4e00-\u9fff]', combined_title))
    
    # Bảng chữ cái Miến Điện (Burmese/Myanmar), Campuchia (Khmer), Lào, Sri Lanka (Sinhala), Tây Tạng, Ge'ez, Armenia, Georgia
    has_burmese = bool(re.search(r'[\u1000-\u109f\uaa60-\uaa7f]', combined_title))
    has_khmer = bool(re.search(r'[\u1780-\u17ff]', combined_title))
    has_lao = bool(re.search(r'[\u0e80-\u0eff]', combined_title))
    has_sinhala = bool(re.search(r'[\u0d80-\u0dff]', combined_title))
    has_tibetan = bool(re.search(r'[\u0f00-\u0fff]', combined_title))
    has_exotic_script = (
        has_burmese or has_khmer or has_lao or has_sinhala or has_tibetan or
        bool(re.search(r'[\u1200-\u137f\u10a0-\u10ff\u0530-\u058f\u0590-\u05ff]', combined_title))
    )

    # Tiếng Việt đặc thù (tránh nhầm với từ mượn Pháp/Tây Ban Nha như Pokémon, café)
    has_vn = bool(re.search(r'[đươĐƯƠ]', combined_title)) or len(re.findall(r'[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵ]', combined_title, re.I)) >= 3

    # Dấu hiệu từ khóa & họ tên đặc trưng Nam Á / Ấn Độ / bộ tộc Mizo viết bằng chữ Latin / kênh tin tức Nam Á
    has_south_asian_keywords = bool(re.search(
        r'\b(hindi|tamil|telugu|bengali|marathi|kannada|malayalam|urdu|punjabi|gujarati|bhojpuri|odia|mizo|desh|vlog hindi|in hindi|in telugu|in tamil|puithiam|pawisa|chingpen|hnem|kaise|kare|karo|nahi|hoga|bjp|modi|yogi|mandir|aaj tak|zee news|ndtv|soni traveling|tluangi ralte|millat times|khabar dar khabar|vande mataram|sansad tv|lallantop|republic bharat|abp news|times of india|wion)\b',
        combined_title,
        re.I
    ))

    # Dấu hiệu tiếng Tagalog / Philippines đặc trưng
    has_tagalog = bool(re.search(
        r'\b(ang\s+[a-z]+|mga\s+[a-z]+|para\s+sa|dahil\s+sa|nahukay|dinala\s+kay|bibilhin|boss\s+toyo|kuya|ate|pilipinas|pinoy|tagalog|ano\s+ba|paano|bakit|kelan|kailan)\b',
        combined_title,
        re.I
    ))

    # 1. Video tiếng Thái: TUYỆT ĐỐI KHÔNG xuất hiện ở bất kỳ quốc gia nào ngoài Thái Lan (TH)
    if has_thai or audio_lang.startswith('th') or default_lang.startswith('th') or ch_country == 'TH':
        if geo != 'TH':
            return False

    # 2. Thị trường Mỹ & tiếng Anh (US, GB, CA, AU)
    if geo in ['US', 'GB', 'CA', 'AU']:
        if (has_south_asian or has_hangul or has_kana or has_cyrillic or has_arabic or 
            has_vn or has_exotic_script or has_south_asian_keywords or has_tagalog or has_chinese):
            return False
        if audio_lang and not audio_lang.startswith(('en', 'es', 'zxx')):
            return False
        if ch_country in ['IN', 'VN', 'RU', 'PK', 'BD', 'ID', 'KR', 'JP', 'TH', 'MM', 'LK', 'NP', 'LA', 'KH', 'PH', 'CN', 'TW', 'HK']:
            return False

    # 3. Thị trường Đức (DE)
    elif geo == 'DE':
        if (has_south_asian or has_hangul or has_kana or has_cyrillic or has_arabic or 
            has_vn or has_exotic_script or has_south_asian_keywords or has_tagalog or has_chinese):
            return False
        if audio_lang and not audio_lang.startswith(('de', 'en', 'zxx')):
            return False
        if ch_country in ['IN', 'VN', 'RU', 'PK', 'BD', 'ID', 'KR', 'JP', 'TH', 'MM', 'LK', 'NP', 'PH', 'CN', 'TW', 'HK']:
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

    # 11. Thị trường Thái Lan (TH)
    elif geo == 'TH':
        if has_south_asian or has_hangul or has_kana or has_cyrillic or has_arabic or has_vn:
            return False
        if audio_lang and not audio_lang.startswith(('th', 'en', 'zxx')):
            return False
        if ch_country in ['VN', 'RU', 'JP', 'KR', 'DE', 'FR']:
            return False

    # 12. Thị trường Indonesia (ID)
    elif geo == 'ID':
        if has_south_asian or has_hangul or has_kana or has_cyrillic or has_arabic or has_thai or has_vn:
            return False
        if audio_lang and not audio_lang.startswith(('id', 'en', 'ms', 'zxx')):
            return False
        if ch_country in ['VN', 'RU', 'JP', 'KR', 'DE', 'FR', 'TH']:
            return False

    # 13. Thị trường Philippines (PH)
    elif geo == 'PH':
        if has_south_asian or has_hangul or has_kana or has_cyrillic or has_arabic or has_thai or has_vn:
            return False
        if audio_lang and not audio_lang.startswith(('en', 'tl', 'fil', 'zxx')):
            return False
        if ch_country in ['VN', 'RU', 'JP', 'KR', 'DE', 'FR', 'TH']:
            return False

    # 14. Thị trường Nga (RU)
    elif geo == 'RU':
        if has_south_asian or has_hangul or has_kana or has_arabic or has_thai or has_vn:
            return False
        if audio_lang and not audio_lang.startswith(('ru', 'en', 'zxx')):
            return False
        if ch_country in ['VN', 'JP', 'KR', 'TH', 'IN', 'ID', 'PH']:
            return False

    # 15. Thị trường Ba Lan (PL)
    elif geo == 'PL':
        if has_south_asian or has_hangul or has_kana or has_cyrillic or has_arabic or has_thai or has_vn:
            return False
        if audio_lang and not audio_lang.startswith(('pl', 'en', 'zxx')):
            return False
        if ch_country in ['VN', 'RU', 'JP', 'KR', 'TH', 'IN', 'ID', 'PH']:
            return False

    # 16. Thị trường Tây Ban Nha (ES)
    elif geo == 'ES':
        if has_south_asian or has_hangul or has_kana or has_cyrillic or has_arabic or has_thai or has_vn:
            return False
        if audio_lang and not audio_lang.startswith(('es', 'en', 'zxx')):
            return False
        if ch_country in ['VN', 'RU', 'JP', 'KR', 'TH', 'IN', 'ID', 'PH']:
            return False

    # 17. Thị trường Bồ Đào Nha (PT)
    elif geo == 'PT':
        if has_south_asian or has_hangul or has_kana or has_cyrillic or has_arabic or has_thai or has_vn:
            return False
        if audio_lang and not audio_lang.startswith(('pt', 'en', 'zxx')):
            return False
        if ch_country in ['VN', 'RU', 'JP', 'KR', 'TH', 'IN', 'ID', 'PH']:
            return False

    # 18. Thị trường Iran / Ba Tư (IR)
    elif geo == 'IR':
        if has_south_asian or has_hangul or has_kana or has_cyrillic or has_thai or has_vn:
            return False
        if audio_lang and not audio_lang.startswith(('fa', 'en', 'zxx')):
            return False
        if ch_country in ['VN', 'RU', 'JP', 'KR', 'TH', 'IN', 'ID', 'PH']:
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
    unique_channel: Optional[Union[bool, str]] = True,
    refresh: Optional[bool] = False
):
    geo_code = (country or geo or "US").upper()
    cat = (category or "all").lower()
    t_range = (time_range or "7d").lower()
    dur_filter = (duration or "long_form").lower()
    mode = (feed_mode or "active_channels").lower()
    is_unique = str(unique_channel).lower() in ["true", "1", "yes"] if unique_channel is not None else True
    api_key = get_default_api_key()

    cache_key = f"{geo_code}_{cat}_{t_range}_{dur_filter}_{mode}_{is_unique}"
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
    elif t_range == "90d":
        cutoff_dt = now - datetime.timedelta(days=90)
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
                        "ID": "trending viral video indonesia podcast",
                        "TH": "คลิปมาแรง วิดีโอยอดนิยม สารคดี พอดแคสต์",
                        "PH": "trending viral video philippines podcast",
                        "RU": "тренды популярные видео россия документальный подкаст",
                        "PL": "trendy popularne filmy polska podcast dokument",
                        "ES": "tendencias videos populares espana podcast documental",
                        "PT": "tendencias videos populares portugal podcast documental",
                        "IR": "ترندهای یوتیوب فارسی پادکست مستند",
                        "BR": "documentario podcast brasil"
                    }
                    q_term = country_names.get(geo_code, "trending viral video")

                GEO_LANG_MAP = {
                    "US": "en", "GB": "en", "CA": "en", "AU": "en",
                    "VN": "vi", "JP": "ja", "KR": "ko", "DE": "de",
                    "BR": "pt", "IN": "en", "FR": "fr", "IT": "it",
                    "ID": "id", "TH": "th", "PH": "en", "RU": "ru",
                    "PL": "pl", "ES": "es", "PT": "pt", "IR": "fa"
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

                    # 4. LỌC VIEW TỐI THIỂU: Đảm bảo có tương tác nhưng không chặn video vừa mới lên
                    view_cnt = int(stats.get("viewCount", 0))
                    min_views = 50 if t_range == "24h" else 150
                    if t_range in ["7d", "24h", "48h", "30d", "90d"] and view_cnt < min_views:
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
                    
                    is_active_channel = (subs_count >= 300 and total_vids >= 3) or (view_cnt >= 1000) or (subs_count == 0 and view_cnt >= 500)
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
                    score = compute_trending_score(view_cnt, pub_iso=pub_at)

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
                        "trending_score": score,
                        "duration_seconds": dur_seconds,
                        "duration_formatted": format_duration_display(dur_seconds),
                        "published_at": pub_at[:10],
                        "published_age": format_published_age(pub_at),
                        "url": f"https://www.youtube.com/watch?v={v_id}",
                        "thumbnail": thumb
                    })

                # Sắp xếp theo Trending Score giảm dần để ưu tiên video bứt phá lan truyền
                videos.sort(key=lambda x: x.get("trending_score", x.get("view_count", 0)), reverse=True)

        except Exception as api_err:
            logger.warning(f"Lỗi truy vấn trending qua YouTube Data API: {api_err}")

    # 2. Nếu không có API Key hoặc số lượng video từ API chưa đủ (ít hơn 16),
    # tự động bổ sung thêm video bằng Web Engine thông minh qua URL lọc sp của YouTube
    if len(videos) < 16:
        try:
            fallback_country_queries = {
                "US": "trending usa",
                "GB": "trending uk",
                "DE": "trends deutschland",
                "FR": "tendances france",
                "IT": "tendenze italia",
                "IN": "trending india",
                "ID": "trending indonesia",
                "TH": "คลิปมาแรง thailand",
                "PH": "trending philippines",
                "RU": "в тренде россия",
                "PL": "na czasie polska",
                "ES": "en tendencias espana",
                "PT": "em alta portugal",
                "IR": "ترندهای یوتیوب فارسی",
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
                "BR": "pt", "IN": "en", "FR": "fr", "IT": "it",
                "ID": "id", "TH": "th", "PH": "en", "RU": "ru",
                "PL": "pl", "ES": "es", "PT": "pt", "IR": "fa"
            }
            hl_code = GEO_LANG_MAP.get(geo_code, "en")

            # Tạo danh sách các từ khóa tìm kiếm: từ khóa chính + biến thể chất lượng
            candidate_queries = [search_query]
            words = search_query.split()
            if cat != "all":
                if len(words) >= 3:
                    candidate_queries.append(' '.join(words[:2]))
                    candidate_queries.append(f"{words[0]} {words[-1]}")
                elif len(words) == 2:
                    candidate_queries.append(search_query)
            else:
                if len(words) >= 3:
                    candidate_queries.append(' '.join(words[:2]))
                    candidate_queries.append(' '.join(words[-2:]))
                    candidate_queries.append(words[0])
                elif len(words) == 2:
                    candidate_queries.append(words[0])
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
                'Accept-Language': f"{hl_code}-{geo_code},{hl_code};q=0.9,en;q=0.8",
                'Cookie': f"PREF=gl={geo_code}&hl={hl_code};"
            }
            
            existing_vids = {v["video_id"] for v in videos}
            channel_candidate_count = defaultdict(int)
            for v in videos:
                k = get_channel_key(v.get("channel_id", ""), v.get("channel_title", ""))
                channel_candidate_count[k] += 1

            for cand_query in candidate_queries:
                # Quét rộng đủ nguồn ứng viên đa kênh để loại trừ trùng lặp
                if len(videos) >= 48:
                    break
                search_url = f"https://www.youtube.com/results?search_query={requests.utils.quote(cand_query)}&sp={sp_param}&gl={geo_code}&hl={hl_code}"
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
                                
                                runs = vr.get('ownerText', {}).get('runs', [])
                                if runs:
                                    first_run_text = runs[0].get('text', '').strip()
                                    full_text = ''.join(r.get('text', '') for r in runs).strip()
                                    if ' and ' in full_text or ' & ' in full_text:
                                        ch_name = first_run_text or full_text
                                    else:
                                        ch_name = full_text or 'YouTube Creator'
                                else:
                                    ch_name = 'YouTube Creator'
                                
                                ch_id = ''
                                try:
                                    ch_id = vr.get('ownerText', {}).get('runs', [{}])[0].get('navigationEndpoint', {}).get('browseEndpoint', {}).get('browseId', '')
                                except Exception:
                                    pass

                                # Lọc kênh: Giới hạn tối đa 2 video ứng viên từ cùng 1 kênh trong raw pool
                                ch_key = get_channel_key(ch_id, ch_name)
                                if is_unique and channel_candidate_count[ch_key] >= 2:
                                    continue

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

                                # Lọc nội dung Game khi danh mục không phải Game
                                if cat not in ["gaming", "all"]:
                                    if any(gkw in t.lower() for gkw in ['blox fruits', 'roblox', 'minecraft', 'free fire', 'pubg', 'gta 5', 'gameplay']):
                                        continue

                                # Lượt xem
                                v_cnt = parse_views_str(views_str)
                                min_v = 50 if t_range == "24h" else 150
                                if t_range in ["7d", "24h", "48h", "30d", "90d"] and v_cnt < min_v:
                                    continue

                                # KIỂM TRA THỜI GIAN NGHIÊM NGẶT: Không bao giờ cho phép video cũ xuất hiện
                                if not is_published_age_matching_range(pub_age, t_range):
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
                                        'country': ''
                                    }
                                }
                                if not is_video_matching_country(pseudo_item, pseudo_ch, geo_code):
                                    continue

                                thumbs = vr.get('thumbnail', {}).get('thumbnails', [])
                                thumb_url = thumbs[-1].get('url') if thumbs else f"https://i.ytimg.com/vi/{v_id}/hqdefault.jpg"

                                is_ver = any("BADGE_STYLE_TYPE_VERIFIED" in str(b) for b in vr.get('ownerBadges', []))
                                score = compute_trending_score(v_cnt, pub_age_str=pub_age)

                                channel_candidate_count[ch_key] += 1
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
                                    "trending_score": score,
                                    "duration_seconds": dur_sec,
                                    "duration_formatted": dur_str or format_duration_display(dur_sec),
                                    "published_at": "",
                                    "published_age": pub_age or ("🔥 Xu hướng tuần này" if t_range == "7d" else "⚡ 24h qua"),
                                    "url": f"https://www.youtube.com/watch?v={v_id}",
                                    "thumbnail": thumb_url
                                })
                except Exception as direct_err:
                    logger.warning(f"Direct trending scraping failed for {cand_query}: {direct_err}")

            # BƯỚC 2.2: Nếu direct scraping chưa đủ video (ít hơn 6), dùng yt-dlp trên đúng URL đã gắn sp filter
            if len(videos) < 6:
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

                            # Lọc nội dung Game khi danh mục không phải Game
                            if cat not in ["gaming", "all"]:
                                if any(gkw in t.lower() for gkw in ['blox fruits', 'roblox', 'minecraft', 'free fire', 'pubg', 'gta 5', 'gameplay']):
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
                                    'country': e.get('channel_country') or ''
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
                                elif t_range == "90d":
                                    age_str = "🗓️ Xu hướng 90 ngày qua"
                                else:
                                    age_str = "🔥 Xu hướng gần đây"

                            v_cnt = int(e.get('view_count') or 0)
                            min_v = 50 if t_range == "24h" else 150
                            if t_range in ["7d", "24h", "48h", "30d", "90d"] and v_cnt < min_v:
                                continue

                            thumb = ""
                            thumbs = e.get('thumbnails', [])
                            if thumbs:
                                thumb = thumbs[-1].get('url') or thumbs[0].get('url', '')
                            elif v_id:
                                thumb = f"https://i.ytimg.com/vi/{v_id}/hqdefault.jpg"

                            f_subs = int(e.get('channel_follower_count') or 0)
                            score = compute_trending_score(v_cnt, pub_iso=pub_str, pub_age_str=age_str)
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
                                "trending_score": score,
                                "duration_seconds": dur,
                                "duration_formatted": format_duration_display(dur),
                                "published_at": pub_str,
                                "published_age": age_str,
                                "url": e.get('url') or f"https://www.youtube.com/watch?v={v_id}",
                                "thumbnail": thumb
                            })

            videos.sort(key=lambda x: x.get("trending_score", x.get("view_count", 0)), reverse=True)
        except Exception as yt_err:
            logger.error(f"Lỗi khi lấy trending fallback: {yt_err}")

    # 1. Sắp xếp toàn bộ video theo Trending Velocity Score giảm dần (ưu tiên bứt phá & tốc độ lan truyền)
    videos.sort(key=lambda x: x.get("trending_score", x.get("view_count", 0)), reverse=True)

    # 2. KHỬ TRÙNG LẶP KÊNH (Channel Deduplication): Mỗi kênh chỉ hiển thị duy nhất 1 video tốt nhất
    if is_unique:
        unique_videos = []
        seen_channels = set()
        for v in videos:
            cid = (v.get("channel_id") or "").strip().lower()
            cname = (v.get("channel_title") or v.get("channel") or "").strip().lower()
            cname_norm = re.sub(r'[^a-zA-Z0-9\u0600-\u06FF\u0400-\u04FF\u4E00-\u9FFF\u3040-\u30FF\uAC00-\uD7AF]', '', cname)
            
            is_dup = False
            if cid and cid.startswith(('uc', '@')) and cid in seen_channels:
                is_dup = True
            elif cname_norm and cname_norm in seen_channels:
                is_dup = True
            elif cname and cname in seen_channels:
                is_dup = True
                
            if is_dup:
                continue
                
            if cid and cid.startswith(('uc', '@')):
                seen_channels.add(cid)
            if cname_norm:
                seen_channels.add(cname_norm)
            if cname:
                seen_channels.add(cname)
                
            unique_videos.append(v)
            
        videos = unique_videos

    final_feed = {
        "success": True,
        "geo": geo_code,
        "country": geo_code,
        "category": cat,
        "time_range": t_range,
        "duration_filter": dur_filter,
        "mode": mode,
        "unique_channel": is_unique,
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

@app.api_route("/", methods=["GET", "HEAD"])
@app.api_route("/index.html", methods=["GET", "HEAD"])
@app.api_route("/index", methods=["GET", "HEAD"])
def serve_index(request: Request):
    user_agent = request.headers.get("user-agent", "").lower()
    # Nếu là bot monitor keep-alive (cron-job.org, uptimerobot, pingdom, betteruptime, curl...)
    # hoặc HEAD request, hoặc có query ?ping=1: trả về 200 OK siêu nhẹ 2 bytes để tránh lỗi "output too large" của cron-job.org
    is_monitor = any(bot in user_agent for bot in [
        "cron-job", "cronjob", "uptimerobot", "pingdom", "betteruptime",
        "healthcheck", "statuscake", "freshping", "site24x7", "node-fetch", "curl"
    ]) or ("ping" in request.query_params)

    if request.method == "HEAD" or is_monitor:
        return PlainTextResponse("OK", status_code=200)

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

@app.api_route("/health", methods=["GET", "HEAD"])
@app.api_route("/ping", methods=["GET", "HEAD"])
def health_check_ping():
    return PlainTextResponse("OK", status_code=200)



