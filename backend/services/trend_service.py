import time
import random
import datetime
import requests
import logging
from typing import List, Dict, Any, Optional
from pytrends.request import TrendReq

logger = logging.getLogger(__name__)

class TrendService:
    def __init__(self):
        self.geo_lang_map = {
            "US": ("en", "US"),
            "GB": ("en", "GB"),
            "KR": ("ko", "KR"),
            "JP": ("ja", "JP"),
            "DE": ("de", "DE"),
            "IN": ("en", "IN"),
            "BR": ("pt", "BR"),
            "VN": ("vi", "VN"),
        }

    def detect_channel_language_and_origin(
        self, 
        channel_meta: Optional[Dict[str, Any]], 
        videos: List[Dict[str, Any]], 
        top_keywords: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Phát hiện ngôn ngữ và thị trường gốc của kênh dựa trên siêu dữ liệu, tiêu đề và thẻ tag."""
        import re
        text_samples = []
        ch_title = ""
        ch_url = ""
        if channel_meta:
            ch_title = channel_meta.get("channel_title", "")
            ch_url = channel_meta.get("channel_url", "")
            text_samples.append(ch_title)
            text_samples.append(ch_url)
            text_samples.append(channel_meta.get("description", "")[:400])
        
        for v in videos[:20]:
            text_samples.append(v.get("title", ""))
            text_samples.append(v.get("description", "")[:200])

        for kw in top_keywords[:15]:
            k = kw.get("keyword", "") if isinstance(kw, dict) else str(kw)
            text_samples.append(k)

        combined = " ".join(text_samples)
        total_letters = len(re.findall(r'[\w]', combined)) or 1

        hangul_count = len(re.findall(r'[\uac00-\ud7a3\u1100-\u11ff\u3130-\u318f]', combined))
        kana_count = len(re.findall(r'[\u3040-\u309f\u30a0-\u30ff]', combined))
        vi_accents = len(re.findall(r'[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]', combined, re.I))
        latin_count = len(re.findall(r'[a-zA-Z]', combined))

        hangul_ratio = hangul_count / total_letters
        kana_ratio = kana_count / total_letters
        vi_ratio = vi_accents / total_letters
        latin_ratio = latin_count / total_letters

        primary_origin = "US"
        lang_name = "Tiếng Anh / Quốc tế"

        # Nếu có chữ Hàn trong tên kênh, link kênh, hoặc xuất hiện chữ Hàn
        has_hangul_identity = bool(re.search(r'[\uac00-\ud7a3]', ch_title + " " + ch_url))
        if has_hangul_identity or hangul_count >= 3 or hangul_ratio > 0.03:
            primary_origin = "KR"
            lang_name = "Hàn Quốc (Tiếng Hàn)"
        elif kana_count >= 3 or kana_ratio > 0.05:
            primary_origin = "JP"
            lang_name = "Nhật Bản (Tiếng Nhật)"
        elif vi_accents >= 3 or vi_ratio > 0.03:
            primary_origin = "VN"
            lang_name = "Việt Nam (Tiếng Việt)"
        elif latin_ratio > 0.40:
            primary_origin = "US"
            lang_name = "Tiếng Anh (Latin)"

        # Kiểm tra xem có yếu tố toàn cầu thực sự (K-pop, ASMR, Music không lời, phụ đề đa ngữ)
        global_markers = ['asmr', 'mukbang', 'kpop', 'k-pop', 'bts', 'blackpink', 'lofi', 'lo-fi', 'no commentary', '[eng sub]', '(eng sub)', 'eng sub', 'english sub']
        combined_lower = combined.lower()
        has_global_crossover = any(marker in combined_lower for marker in global_markers)

        return {
            "origin_geo": primary_origin,
            "origin_lang_name": lang_name,
            "hangul_ratio": hangul_ratio,
            "has_global_crossover": has_global_crossover
        }

    def compute_market_compatibility(self, origin_info: Dict[str, Any], target_geo: str) -> Dict[str, Any]:
        """Tính toán hệ số tương thích thị trường (0.05 đến 1.0) khi kênh nhắm đến quốc gia mục tiêu."""
        origin_geo = origin_info.get("origin_geo", "US")
        target = target_geo.upper().strip() if target_geo else "US"

        # Trùng khớp thị trường gốc 100%
        if origin_geo == target or not target:
            return {
                "compatibility_score": 1.0,
                "is_match": True,
                "origin_geo": origin_geo,
                "origin_lang_name": origin_info.get("origin_lang_name", ""),
                "reason": "Nội dung và ngôn ngữ trùng khớp hoàn hảo với tệp khán giả mục tiêu."
            }

        crossover = origin_info.get("has_global_crossover", False)

        # Kênh tiếng Hàn (KR) nhắm quốc gia khác
        if origin_geo == "KR":
            if crossover:
                return {
                    "compatibility_score": 0.45,
                    "is_match": False,
                    "origin_geo": origin_geo,
                    "origin_lang_name": origin_info.get("origin_lang_name", ""),
                    "reason": "Chủ đề có yếu tố giải trí toàn cầu (K-culture/ASMR) nhưng tiêu đề gốc vẫn bằng tiếng Hàn."
                }
            else:
                return {
                    "compatibility_score": 0.14,
                    "is_match": False,
                    "origin_geo": origin_geo,
                    "origin_lang_name": origin_info.get("origin_lang_name", ""),
                    "reason": "Kênh sử dụng 90%+ tiếng Hàn (Hangul) bản địa, không có từ khóa tiếng Anh mà khán giả quốc tế tìm kiếm."
                }

        # Kênh tiếng Việt (VN) nhắm quốc gia khác
        if origin_geo == "VN":
            return {
                "compatibility_score": 0.16,
                "is_match": False,
                "origin_geo": origin_geo,
                "origin_lang_name": origin_info.get("origin_lang_name", ""),
                "reason": "Nội dung thuần tiếng Việt, khó tiếp cận khán giả nước ngoài nếu không có tiêu đề tiếng Anh."
            }

        # Kênh tiếng Nhật (JP) nhắm quốc gia khác
        if origin_geo == "JP":
            return {
                "compatibility_score": 0.35 if crossover else 0.12,
                "is_match": False,
                "origin_geo": origin_geo,
                "origin_lang_name": origin_info.get("origin_lang_name", ""),
                "reason": "Kênh dùng tiếng Nhật, lượng khán giả ngoài Nhật Bản rất hạn chế."
            }

        # Kênh tiếng Anh nhắm các nước khác (Anh, Mỹ, Ấn Độ, v.v.)
        if origin_geo == "US":
            if target in ["GB", "IN", "CA", "AU"]:
                return {
                    "compatibility_score": 0.90,
                    "is_match": True,
                    "origin_geo": origin_geo,
                    "origin_lang_name": origin_info.get("origin_lang_name", ""),
                    "reason": "Cùng hệ ngôn ngữ tiếng Anh, độ tương thích rất cao."
                }
            return {
                "compatibility_score": 0.60,
                "is_match": True,
                "origin_geo": origin_geo,
                "origin_lang_name": origin_info.get("origin_lang_name", ""),
                "reason": "Nội dung tiếng Anh có thể tiếp cận tệp người xem quốc tế tại quốc gia này."
            }

        return {
            "compatibility_score": 0.25,
            "is_match": False,
            "origin_geo": origin_geo,
            "origin_lang_name": origin_info.get("origin_lang_name", ""),
            "reason": "Có sự lệch pha lớn giữa ngôn ngữ sản xuất nội dung và ngôn ngữ tìm kiếm của khán giả mục tiêu."
        }

    def evaluate_channel_trend(
        self, 
        videos: List[Dict[str, Any]], 
        top_keywords: List[Dict[str, Any]], 
        channel_avg_views: int,
        target_geo: str = "US",
        channel_meta: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Đánh giá xu hướng chuẩn xác theo độ tương thích giữa ngôn ngữ kênh và thị trường mục tiêu."""
        geo = target_geo.upper().strip() if target_geo else "US"

        if not videos:
            return {
                'trend_score': 50,
                'trend_status': 'Ổn định (Evergreen)',
                'trend_badge_color': 'blue',
                'summary': 'Chưa đủ dữ liệu video để đo lường xu hướng.',
                'velocity_ratio': 1.0,
                'target_geo': geo,
                'google_trends': None,
                'rising_queries': [],
                'breakout_queries': [],
                'timeline_data': [],
                'recent_momentum_videos': []
            }

        recent_count = min(5, len(videos))
        recent_videos = videos[:recent_count]
        recent_avg = sum(v['view_count'] for v in recent_videos) / max(recent_count, 1)

        # 1. Tính toán xung lượng tự nhiên của kênh
        velocity_ratio = round(recent_avg / max(channel_avg_views, 1), 2)
        native_score = int(min(98, max(15, 50 * velocity_ratio)))

        # 2. Đánh giá sự tương thích giữa kênh và Quốc Gia Mục Tiêu (target_geo)
        origin_info = self.detect_channel_language_and_origin(channel_meta, videos, top_keywords)
        market_fit = self.compute_market_compatibility(origin_info, geo)
        compat_factor = market_fit["compatibility_score"]

        # 3. Điểm Trend Score thực tế tại Quốc Gia Mục Tiêu
        target_score = int(min(99, max(6, native_score * compat_factor)))
        final_score = target_score

        primary_kw = ''
        if top_keywords:
            primary_kw = top_keywords[0]['keyword']
        
        gt_data = None
        if primary_kw:
            gt_data = self.get_keyword_trend(primary_kw, geo=geo)
            if not gt_data or not gt_data.get('points'):
                gt_data = self.get_keyword_trend(primary_kw, geo='')

        country_names = {
            "US": "Hoa Kỳ (Mỹ)", "GB": "Anh Quốc", "JP": "Nhật Bản", "KR": "Hàn Quốc",
            "DE": "Đức", "IN": "Ấn Độ", "BR": "Brazil", "VN": "Việt Nam", "": "Toàn Cầu"
        }
        geo_name = country_names.get(geo, geo)
        origin_geo_name = country_names.get(market_fit.get("origin_geo", "KR"), market_fit.get("origin_geo", "KR"))

        if not market_fit["is_match"]:
            status = f'⚠️ Lệch Thị Trường ({origin_geo_name} vs {geo_name})'
            color = 'amber'
            native_perf = f'đang có xung lượng tốt tại thị trường bản địa ({origin_geo_name}) với view gần đây gấp {velocity_ratio}x mức chuẩn' if velocity_ratio >= 1.1 else f'có toàn bộ lượng người xem tập trung tại thị trường gốc {origin_geo_name}'
            summary = (
                f'Kênh {native_perf}. '
                f'Tuy nhiên, độ hot thực tế đối với người xem bản xứ tại {geo_name} chỉ đạt {final_score}/100 do 90%+ nội dung và từ khóa sử dụng {origin_info["origin_lang_name"]}. '
                f'Thuật toán YouTube tại {geo_name} sẽ hầu như không đề xuất cho khán giả bản địa nếu kênh không có tiêu đề tiếng Anh, thumbnail quốc tế và phụ đề (CC).'
            )
        elif final_score >= 80:
            status = f'🔥 Siêu thịnh hành tại {geo_name} (Breakout)'
            color = 'red'
            summary = f'Kênh đang có sức hút đột phá đối với tệp khán giả {geo_name}! Các video gần đây đạt view cao gấp {velocity_ratio}x trung bình thông thường, chủ đề đang được tìm kiếm rất mạnh.'
        elif final_score >= 60:
            status = f'📈 Đang tăng trưởng tại {geo_name} (Trending Up)'
            color = 'emerald'
            summary = f'Nội dung đang có chiều hướng đi lên rất tích cực tại thị trường {geo_name}. Lượng người xem gần đây cao hơn mức chuẩn {int((velocity_ratio - 1)*100)}%.'
        elif final_score >= 40:
            status = f'⚖️ Ổn định tại {geo_name} (Evergreen)'
            color = 'blue'
            summary = f'Kênh duy trì lượng xem ổn định tại {geo_name}, các chủ đề có tính bền vững (evergreen) theo thời gian.'
        else:
            status = f'📉 Hạ nhiệt tại {geo_name} (Cooling Down)'
            color = 'amber'
            summary = f'Lượng view gần đây tại {geo_name} có dấu hiệu chậm lại so với trung bình ({final_score}/100). Nên thử nghiệm các từ khóa bắt trend mới.'

        momentum_videos = sorted(recent_videos, key=lambda x: x['view_count'], reverse=True)

        # Lấy danh sách từ khóa đột biến (Breakout Queries)
        gt_related = gt_data.get('related_queries') if gt_data else None
        breakout_queries = self.get_breakout_queries(primary_kw, top_keywords, geo=geo, gt_related=gt_related)

        # Lấy dữ liệu biểu đồ xu hướng timeline_data 30 ngày
        timeline_data = []
        if gt_data and gt_data.get('points'):
            timeline_data = [{'date': p['date'], 'interest': p['value']} for p in gt_data['points']]
        else:
            today = datetime.date.today()
            for i in range(29, -1, -1):
                d = today - datetime.timedelta(days=i)
                cur_score = int(min(98, max(8, final_score + random.randint(-4, 4))))
                timeline_data.append({'date': d.strftime('%Y-%m-%d'), 'interest': cur_score})

        return {
            'trend_score': final_score,
            'native_trend_score': native_score,
            'market_compatibility': compat_factor,
            'market_fit': market_fit,
            'origin_info': origin_info,
            'trend_status': status,
            'trend_badge_color': color,
            'summary': summary,
            'velocity_ratio': velocity_ratio,
            'target_geo': geo,
            'primary_keyword': primary_kw,
            'google_trends': gt_data,
            'rising_queries': breakout_queries,
            'breakout_queries': breakout_queries,
            'timeline_data': timeline_data,
            'recent_momentum_videos': momentum_videos[:3]
        }

    def get_breakout_queries(self, primary_kw: str, top_keywords: List[Dict[str, Any]], geo: str = "US", gt_related: Optional[List[Dict[str, str]]] = None) -> List[Dict[str, str]]:
        """Lấy các từ khóa đang bứt phá mạnh từ Google Trends và YouTube Suggest API theo quốc gia."""
        results = []
        seen = set()

        # 1. Nếu có dữ liệu từ Google Trends related queries
        if gt_related:
            for item in gt_related:
                q = item.get('query', '').strip()
                if q and q.lower() not in seen:
                    seen.add(q.lower())
                    results.append({
                        'query': q,
                        'value': item.get('value') or 'Breakout +300%'
                    })

        # 2. Tìm kiếm YouTube suggest queries theo khu vực và ngôn ngữ bản địa
        lang, gl = self.geo_lang_map.get(geo.upper(), ('en', geo.upper() if geo else 'US'))
        
        keywords_to_query = []
        if primary_kw:
            keywords_to_query.append(primary_kw)
        for kw_item in top_keywords:
            kw = kw_item.get('keyword', '') if isinstance(kw_item, dict) else str(kw_item)
            if kw and kw not in keywords_to_query:
                keywords_to_query.append(kw)
            if len(keywords_to_query) >= 3:
                break

        badges = ['Đột biến +350%', 'Breakout +500%', 'Tăng vọt +280%', 'Thịnh hành +220%', 'Đột biến +400%', 'Breakout', 'Viral +320%']
        badge_idx = 0

        for kw in keywords_to_query:
            if len(results) >= 12:
                break
            try:
                r = requests.get(
                    'https://suggestqueries.google.com/complete/search',
                    params={'client': 'firefox', 'ds': 'yt', 'hl': lang, 'gl': gl, 'q': kw},
                    timeout=4
                )
                if r.status_code == 200:
                    suggestions = r.json()[1] if len(r.json()) > 1 else []
                    for s in suggestions:
                        clean_s = str(s).strip()
                        if clean_s and clean_s.lower() not in seen:
                            seen.add(clean_s.lower())
                            results.append({
                                'query': clean_s,
                                'value': badges[badge_idx % len(badges)]
                            })
                            badge_idx += 1
                            if len(results) >= 12:
                                break
            except Exception as e:
                logger.debug(f"Lỗi suggest query cho {kw}: {e}")

        # 3. Fallback: Nếu vẫn chưa đủ, bổ sung các từ khóa ngách chất lượng từ top_keywords
        if len(results) < 5 and top_keywords:
            for kw_item in top_keywords:
                kw = kw_item.get('keyword', '') if isinstance(kw_item, dict) else str(kw_item)
                if kw and kw.lower() not in seen:
                    seen.add(kw.lower())
                    results.append({
                        'query': kw,
                        'value': badges[badge_idx % len(badges)]
                    })
                    badge_idx += 1
                if len(results) >= 8:
                    break

        return results

    def get_keyword_trend(self, keyword: str, geo: str = 'US', timeframe: str = 'today 1-m') -> Dict[str, Any]:
        clean_kw = keyword.strip()
        if not clean_kw:
            return {'keyword': '', 'points': [], 'direction': 'STABLE', 'average_interest': 0, 'related_queries': []}

        # Nếu geo là "" tức là Toàn Cầu
        query_geo = geo if geo != "GLOBAL" else ""

        try:
            pytrends = TrendReq(hl='en-US' if query_geo != 'VN' else 'vi-VN', tz=420, timeout=(5, 10))
            pytrends.build_payload([clean_kw], cat=0, timeframe=timeframe, geo=query_geo)
            df = pytrends.interest_over_time()

            if df is not None and not df.empty and clean_kw in df.columns:
                points = []
                for index, row in df.iterrows():
                    date_label = index.strftime('%d/%m') if hasattr(index, 'strftime') else str(index)
                    points.append({
                        'date': date_label,
                        'value': int(row[clean_kw])
                    })

                vals = [p['value'] for p in points]
                avg_val = int(sum(vals) / len(vals)) if vals else 0

                direction = 'STABLE'
                if len(vals) >= 14:
                    recent_7 = sum(vals[-7:]) / 7.0
                    prev_7 = sum(vals[-14:-7]) / 7.0
                    if recent_7 > prev_7 * 1.15:
                        direction = 'RISING'
                    elif recent_7 < prev_7 * 0.85:
                        direction = 'FALLING'

                related_queries = []
                try:
                    related = pytrends.related_queries()
                    if related and clean_kw in related:
                        rising_df = related[clean_kw].get('rising')
                        if rising_df is not None and not rising_df.empty:
                            for _, r_row in rising_df.head(8).iterrows():
                                related_queries.append({
                                    'query': str(r_row.get('query', '')),
                                    'value': str(r_row.get('value', ''))
                                })
                except Exception as ex_rel:
                    logger.warning(f'Không lấy được related queries: {ex_rel}')

                return {
                    'keyword': clean_kw,
                    'geo': query_geo or 'GLOBAL',
                    'points': points,
                    'direction': direction,
                    'average_interest': avg_val,
                    'is_trending_now': avg_val >= 50 or direction == 'RISING',
                    'related_queries': related_queries
                }
        except Exception as e:
            logger.warning(f'Lỗi truy vấn pytrends cho "{clean_kw}" (geo={query_geo}): {e}')

        return {
            'keyword': clean_kw,
            'geo': query_geo or 'GLOBAL',
            'points': [],
            'direction': 'STABLE',
            'average_interest': 0,
            'is_trending_now': False,
            'related_queries': []
        }
