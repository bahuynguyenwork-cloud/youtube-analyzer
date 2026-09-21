import os
import sys
import re
import datetime
import json
import logging
import requests
from typing import Optional
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
import yt_dlp

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

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

def get_default_api_key() -> Optional[str]:
    cfg = load_saved_config()
    key = cfg.get("youtube_api_key") or os.environ.get("YOUTUBE_API_KEY")
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

class ChannelAnalysisRequest(BaseModel):
    channel_input: Optional[str] = None
    channel_identifier: Optional[str] = None
    max_videos: Optional[int] = 25
    max_results: Optional[int] = None
    target_geo: Optional[str] = None
    target_country: Optional[str] = None
    api_key: Optional[str] = None

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

        time_data = time_service.analyze_upload_times(videos, target_geo=geo)

        # Enrich time_data with friendly UI fields
        if "best_upload_time_vn" not in time_data or not time_data["best_upload_time_vn"]:
            time_data["best_upload_time_vn"] = time_data.get("best_upload_vn") or "02:00 - 04:00"
        if "peak_view_time_vn" not in time_data or not time_data["peak_view_time_vn"]:
            time_data["peak_view_time_vn"] = time_data.get("peak_view_vn") or "06:00 - 10:00"
        if "best_day_of_week" not in time_data:
            best_w = time_data.get("best_weekdays", ["Thứ Bảy"])
            time_data["best_day_of_week"] = best_w[0] if best_w else "Thứ Bảy"
        if "hour_distribution" not in time_data and "hours_distribution" in time_data:
            time_data["hour_distribution"] = {item["hour"]: item["video_count"] for item in time_data["hours_distribution"]}

        competitors = competitor_service.find_similar_channels(
            channel_meta.get("channel_title", ""),
            channel_meta.get("channel_url", ""),
            keyword_data.get("top_keywords", []),
            limit=6,
            api_key=effective_key
        )

        strategy_data = strategy_service.generate_recommendations(channel_meta, stats, keyword_data, trend_data)

        # Channel info alias
        channel_info_merged = dict(channel_meta)
        channel_info_merged["title"] = channel_meta.get("channel_title", "")
        channel_info_merged["avg_views"] = stats.get("avg_views", 0)
        channel_info_merged["cadence_days"] = stats.get("upload_frequency_days", 0)
        channel_info_merged["view_to_sub_ratio"] = stats.get("views_to_subs_ratio", 0)
        channel_info_merged["outlier_videos"] = stats.get("outliers", [])
        channel_info_merged["recent_videos"] = videos
        channel_info_merged["keywords"] = [k["keyword"] for k in keyword_data.get("top_keywords", [])]

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
            "strategy_recommendations": strategy_data
        }
    except ValueError as ve:
        logger.warning(f"Validation error: {ve}")
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Error during channel analysis: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Không thể phân tích kênh: {str(e)}")

@app.post("/api/analyze/keyword")
def analyze_keyword(req: KeywordAnalysisRequest):
    kw = req.keyword.strip()
    if not kw:
        raise HTTPException(status_code=400, detail="Vui lòng nhập từ khóa cần kiểm tra xu hướng.")

    try:
        geo = req.geo or "US"
        trend_res = trend_service.get_keyword_trend(kw, geo=geo)

        yt_results = []
        try:
            ydl_opts = {
                'quiet': True,
                'skip_download': True,
                'extract_flat': True,
                'socket_timeout': 10
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                search_res = ydl.extract_info(f"ytsearch6:{kw}", download=False)
                if search_res and search_res.get('entries'):
                    for e in search_res['entries']:
                        if not e:
                            continue
                        thumb = ""
                        thumbs = e.get('thumbnails', [])
                        if thumbs:
                            thumb = thumbs[-1].get('url') or thumbs[0].get('url', '')
                        elif e.get('id'):
                            thumb = f"https://i.ytimg.com/vi/{e.get('id')}/hqdefault.jpg"

                        yt_results.append({
                            'id': e.get('id'),
                            'title': e.get('title'),
                            'channel': e.get('channel') or e.get('uploader'),
                            'views': e.get('view_count') or 0,
                            'url': e.get('url') or f"https://www.youtube.com/watch?v={e.get('id')}",
                            'thumbnail': thumb
                        })
        except Exception as yt_err:
            logger.warning(f"Lỗi khi search YouTube cho từ khóa {kw}: {yt_err}")

        points = trend_res.get("points", [])
        avg_interest = trend_res.get("average_interest", 0)
        direction = trend_res.get("direction", "STABLE")

        hot_score = int(min(99, max(10, avg_interest)))
        if direction == "RISING":
            hot_score = min(99, hot_score + 15)

        is_trending = hot_score >= 60

        return {
            "success": True,
            "keyword": kw,
            "geo": geo,
            "trend_score": hot_score,
            "is_trending": is_trending,
            "direction": direction,
            "average_interest": avg_interest,
            "trend_points": points,
            "related_queries": trend_res.get("related_queries", []),
            "top_youtube_videos": yt_results
        }
    except Exception as e:
        logger.error(f"Error during keyword analysis: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Lỗi khi tra cứu từ khóa: {str(e)}")

NICHE_LOCALIZED_QUERIES = {
    "philosophy": {
        "VN": "triết lý cuộc sống",
        "US": "stoicism philosophy life lessons",
        "GB": "stoicism philosophy",
        "JP": "哲学 人生訓",
        "KR": "철학 인생 교훈",
        "DE": "Philosophie Stoizismus",
        "DEFAULT": "stoicism philosophy life lessons"
    },
    "buddhism": {
        "VN": "lời phật dạy phật pháp",
        "US": "buddhism teachings mindfulness",
        "GB": "buddhism mindfulness",
        "JP": "仏教 説法 禅",
        "KR": "불교 설법 명상",
        "DE": "Buddhismus Meditation",
        "DEFAULT": "buddhism teachings mindfulness"
    },
    "elderly_wisdom": {
        "VN": "tâm sự tuổi già lời khuyên người già",
        "US": "elderly wisdom senior life lessons",
        "GB": "elderly wisdom senior lessons",
        "JP": "高齢者 人生の教訓",
        "KR": "노인의 지혜 인생 교훈",
        "DE": "Lebensweisheiten älterer Menschen",
        "DEFAULT": "elderly wisdom senior life lessons"
    },
    "reddit_stories": {
        "VN": "truyện reddit tâm sự",
        "US": "reddit stories AITA update",
        "GB": "reddit stories confessions",
        "JP": "2ch スレ 面白い話",
        "KR": "레딧 썰 사연",
        "DE": "Reddit Geschichten",
        "DEFAULT": "reddit stories AITA update"
    },
    "drama_expose": {
        "VN": "drama bóc phốt showbiz",
        "US": "documentary the downfall of",
        "GB": "documentary exposé scandal",
        "JP": "炎上 事件の真相",
        "KR": "사건 폭로 이슈",
        "DE": "Skandal Doku Enthüllung",
        "DEFAULT": "documentary the downfall of"
    },
    "true_crime": {
        "VN": "vụ án có thật kỳ án",
        "US": "true crime documentary interrogation",
        "GB": "true crime documentary",
        "JP": "未解決事件 犯罪ドキュメンタリー",
        "KR": "실화 범죄 미제 사건 다큐",
        "DE": "True Crime Dokumentation",
        "DEFAULT": "true crime documentary interrogation"
    },
    "horror_stories": {
        "VN": "truyện ma đêm muộn kinh dị",
        "US": "scary horror stories creepypasta",
        "GB": "scary horror stories spooky",
        "JP": "怖い話 怪談 実話",
        "KR": "무서운 이야기 실화 괴담",
        "DE": "Gruselgeschichten Horror",
        "DEFAULT": "scary horror stories creepypasta"
    },
    "history_geopolitics": {
        "VN": "lịch sử chiến tranh địa chính trị",
        "US": "history documentary geopolitics",
        "GB": "history documentary warfare",
        "JP": "歴史 ドキュメンタリー 地政学",
        "KR": "역사 다큐멘터리 전쟁 지정학",
        "DE": "Geschichte Dokumentation Geopolitik",
        "DEFAULT": "history documentary geopolitics"
    },
    "space_science": {
        "VN": "bí ẩn vũ trụ khoa học thiên văn",
        "US": "space science documentary universe",
        "GB": "space documentary science",
        "JP": "宇宙 科学 ブラックホール 謎",
        "KR": "우주 과학 블랙홀 미스터리",
        "DE": "Weltraum Wissenschaft Universum",
        "DEFAULT": "space science documentary universe"
    },
    "finance_money": {
        "VN": "tài chính cá nhân kiếm tiền online đầu tư",
        "US": "personal finance investing make money online",
        "GB": "personal finance investing",
        "JP": "個人資産 投資 お金",
        "KR": "재테크 투자 부업",
        "DE": "Finanzen Investieren Geld",
        "DEFAULT": "personal finance investing make money online"
    },
    "tech_ai": {
        "VN": "trí tuệ nhân tạo AI công nghệ mới",
        "US": "artificial intelligence AI tools",
        "GB": "artificial intelligence AI",
        "JP": "人工知能 AIツール",
        "KR": "인공지능 AI 도구",
        "DE": "Künstliche Intelligenz AI Tools",
        "DEFAULT": "artificial intelligence AI tools"
    },
    "recap_stories": {
        "VN": "review phim tóm tắt phim",
        "US": "movie recap film summary",
        "GB": "movie recap film recap",
        "JP": "映画 要約 解説",
        "KR": "영화 요약 결말포함",
        "DE": "Film Zusammenfassung Recap",
        "DEFAULT": "movie recap film summary"
    },
    "gaming": {
        "VN": "gameplay highlights streamer việt nam",
        "US": "gaming gameplay highlights",
        "GB": "gaming gameplay walkthrough",
        "JP": "ゲーム 実況 プレイ動画",
        "KR": "게임 플레이 하이라이트",
        "DE": "Gaming Gameplay Highlights",
        "DEFAULT": "gaming gameplay highlights"
    },
    "entertainment": {
        "VN": "hài hước giải trí viral",
        "US": "entertainment funny viral comedy",
        "GB": "entertainment comedy viral",
        "JP": "エンタメ 面白い バラエティ",
        "KR": "예능 레전드 웃긴 영상",
        "DE": "Unterhaltung Comedy Viral",
        "DEFAULT": "entertainment funny viral comedy"
    }
}

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

def format_published_age(pub_iso: str) -> str:
    if not pub_iso:
        return ""
    try:
        dt = datetime.datetime.fromisoformat(pub_iso.replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
        diff_seconds = (now - dt).total_seconds()
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

@app.get("/api/trending/feed")
def get_trending_feed(
    country: Optional[str] = None, 
    geo: Optional[str] = "US", 
    category: Optional[str] = "all",
    time_range: Optional[str] = "7d",
    duration: Optional[str] = "long_form",
    feed_mode: Optional[str] = "active_channels"
):
    import requests
    geo_code = (country or geo or "US").upper()
    cat = (category or "all").lower()
    t_range = (time_range or "7d").lower()
    dur_filter = (duration or "long_form").lower()
    mode = (feed_mode or "active_channels").lower()
    api_key = get_default_api_key()

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

    # 1. Thử dùng YouTube Data API v3 chính thức nếu có API Key
    if api_key:
        try:
            video_items = []
            
            # TRƯỜNG HỢP 1: Tất cả xu hướng (Top Trending chung của quốc gia)
            if cat == "all":
                chart_url = (
                    f"https://www.googleapis.com/youtube/v3/videos?part=snippet,contentDetails,statistics"
                    f"&chart=mostPopular&regionCode={geo_code}&maxResults=50&key={api_key}"
                )
                chart_res = requests.get(chart_url, timeout=10).json()
                raw_items = chart_res.get("items", [])
                
                # Lọc theo khung thời gian (7d, 24h, 30d...)
                for it in raw_items:
                    pub_iso = it.get("snippet", {}).get("publishedAt", "")
                    if cutoff_dt and pub_iso:
                        try:
                            p_dt = datetime.datetime.fromisoformat(pub_iso.replace("Z", "+00:00"))
                            if p_dt < cutoff_dt:
                                continue
                        except Exception:
                            pass
                    video_items.append(it)
            
            # TRƯỜNG HỢP 2: Theo chủ đề / ngách cụ thể HOẶC nếu chart trả về quá ít
            if cat != "all" or (len(video_items) < 5 and published_after_str):
                v_dur_param = "medium"
                if dur_filter == "deep_dive":
                    v_dur_param = "long"

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
                        "VN": "phóng sự tài liệu podcast xu hướng"
                    }
                    q_term = country_names.get(geo_code, "trending viral video")

                GEO_LANG_MAP = {
                    "US": "en", "GB": "en", "CA": "en", "AU": "en",
                    "VN": "vi", "JP": "ja", "KR": "ko", "DE": "de",
                    "BR": "pt", "IN": "en"
                }
                lang_param = GEO_LANG_MAP.get(geo_code, "en")

                s_url = (
                    f"https://www.googleapis.com/youtube/v3/search?part=snippet&type=video"
                    f"&videoDuration={v_dur_param}&order=viewCount&regionCode={geo_code}"
                    f"&relevanceLanguage={lang_param}&q={requests.utils.quote(q_term)}&maxResults=40&key={api_key}"
                )
                if published_after_str:
                    s_url += f"&publishedAfter={published_after_str}"

                s_res = requests.get(s_url, timeout=10).json()
                s_items = s_res.get("items", [])
                v_ids = [it["id"]["videoId"] for it in s_items if it.get("id", {}).get("videoId")]

                if v_ids:
                    d_url = f"https://www.googleapis.com/youtube/v3/videos?part=snippet,statistics,contentDetails&id={','.join(v_ids[:40])}&key={api_key}"
                    d_res = requests.get(d_url, timeout=10).json()
                    video_items = d_res.get("items", [])

            if video_items:
                # Lấy thông tin kênh để xác nhận kênh còn sống và có lượng sub ổn định
                ch_ids = list(set([it["snippet"]["channelId"] for it in video_items if it.get("snippet", {}).get("channelId")]))
                ch_map = {}
                if ch_ids:
                    ch_url = f"https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics&id={','.join(ch_ids[:50])}&key={api_key}"
                    ch_res = requests.get(ch_url, timeout=10).json()
                    for ch in ch_res.get("items", []):
                        ch_map[ch["id"]] = ch

                for item in video_items:
                    v_id = item.get("id")
                    snippet = item.get("snippet", {})
                    stats = item.get("statistics", {})
                    content_det = item.get("contentDetails", {})
                    
                    # 1. BẢO VỆ MỐC THỜI GIAN NGHIÊM NGẶT: Tuyệt đối không cho video cũ lọt vào
                    pub_at = snippet.get("publishedAt", "")
                    if cutoff_dt and pub_at:
                        try:
                            p_dt = datetime.datetime.fromisoformat(pub_at.replace("Z", "+00:00"))
                            if p_dt < cutoff_dt:
                                continue
                        except Exception:
                            pass

                    # 2. LOẠI BỎ TOÀN BỘ SHORTS VÀ VIDEO QUÁ NGẮN (< 180 giây)
                    dur_iso = content_det.get("duration", "")
                    dur_seconds = parse_iso_duration(dur_iso)
                    title_raw = snippet.get("title", "")
                    
                    if dur_seconds < 180 or "#shorts" in title_raw.lower() or "shorts" in title_raw.lower().split():
                        continue
                    if dur_filter == "deep_dive" and dur_seconds < 1200:
                        continue

                    # 3. LỌC VIEW TỐI THIỂU: Đã là xu hướng (Trending) thì không thể chỉ có vài chục view
                    view_cnt = int(stats.get("viewCount", 0))
                    # Lọc bỏ các video view quá lẹt đẹt (< 500 views)
                    if t_range in ["7d", "24h", "48h", "30d"] and view_cnt < 500:
                        continue

                    # Kiểm tra kênh hoạt động & ổn định
                    ch_id = snippet.get("channelId", "")
                    ch_info = ch_map.get(ch_id, {})
                    ch_stats = ch_info.get("statistics", {})
                    subs_count = int(ch_stats.get("subscriberCount") or 0)
                    total_vids = int(ch_stats.get("videoCount") or 0)
                    
                    is_active_channel = subs_count >= 1000 and total_vids >= 5
                    is_very_stable = subs_count >= 10000 and total_vids >= 20
                    
                    if is_very_stable:
                        channel_badge_text = "🟢 Kênh Ổn Định"
                    elif is_active_channel:
                        channel_badge_text = "🟢 Kênh Hoạt Động"
                    else:
                        channel_badge_text = "📺 Kênh Mới"
                        
                    if subs_count > 0:
                        if subs_count >= 1000000:
                            channel_badge_text += f" • {subs_count / 1000000:.1f}M Subs"
                        else:
                            channel_badge_text += f" • {subs_count // 1000}K Subs"

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

    # 2. Nếu không có API Key hoặc API trả về rỗng, dùng fallback qua yt-dlp ytsearch
    if not videos:
        try:
            country_names = {
                "US": "United States", "GB": "United Kingdom", "JP": "Japan",
                "KR": "Korea", "DE": "Germany", "VN": "Việt Nam", "IN": "India",
                "BR": "Brazil", "CA": "Canada", "AU": "Australia"
            }
            c_name = country_names.get(geo_code, geo_code)
            
            if cat in NICHE_LOCALIZED_QUERIES:
                niche_dict = NICHE_LOCALIZED_QUERIES[cat]
                q_term = niche_dict.get(geo_code, niche_dict.get("DEFAULT", cat))
                search_query = f"{q_term} 2026"
            else:
                search_query = f"trending viral documentary {c_name} 2026"

            ydl_opts = {
                'quiet': True,
                'skip_download': True,
                'extract_flat': True,
                'socket_timeout': 10
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                res = ydl.extract_info(f"ytsearch30:{search_query}", download=False)
                if res and res.get('entries'):
                    for e in res['entries']:
                        if not e:
                            continue
                        dur = e.get('duration') or 0
                        t = e.get('title', '')
                        if dur > 0 and dur < 180:
                            continue
                        if dur_filter == "deep_dive" and dur > 0 and dur < 1200:
                            continue
                        if '#shorts' in t.lower() or 'shorts' in t.lower().split():
                            continue

                        v_id = e.get('id')
                        thumb = ""
                        thumbs = e.get('thumbnails', [])
                        if thumbs:
                            thumb = thumbs[-1].get('url') or thumbs[0].get('url', '')
                        elif v_id:
                            thumb = f"https://i.ytimg.com/vi/{v_id}/hqdefault.jpg"

                        videos.append({
                            "video_id": v_id,
                            "id": v_id,
                            "title": t,
                            "channel_title": e.get('channel') or e.get('uploader') or 'YouTube Creator',
                            "channel": e.get('channel') or e.get('uploader') or 'YouTube Creator',
                            "channel_badge": "🟢 Kênh Hoạt Động",
                            "is_active_channel": True,
                            "view_count": e.get('view_count') or 0,
                            "views": e.get('view_count') or 0,
                            "duration_seconds": dur,
                            "duration_formatted": format_duration_display(dur),
                            "published_age": "🔥 Xu hướng tuần này",
                            "url": e.get('url') or f"https://www.youtube.com/watch?v={v_id}",
                            "thumbnail": thumb
                        })
        except Exception as yt_err:
            logger.error(f"Lỗi khi lấy trending fallback: {yt_err}")

    return {
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

frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

@app.get("/")
def serve_index():
    index_path = os.path.join(frontend_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Frontend chưa được khởi tạo."}

@app.get("/favicon.ico")
def serve_favicon():
    fav_path = os.path.join(frontend_dir, "favicon.svg")
    if os.path.exists(fav_path):
        return FileResponse(fav_path, media_type="image/svg+xml")
    return Response(status_code=204)

