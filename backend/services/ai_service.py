import re
import json
import logging
import os
from typing import List, Dict, Any, Optional
import requests

logger = logging.getLogger(__name__)

VALID_NICHES = {
    "entertainment": "🎉 Giải Trí & Hài Hước (Thử thách sinh tồn, Viral stunts, Cuộc thi tiền thưởng, Hài hước)",
    "travel_vlog": "✈️ Du Lịch, Ẩm Thực & Vlog Đời Sống (Khám phá trải nghiệm, Daily vlog, Địa điểm du lịch)",
    "gaming": "🎮 Gaming & Esports (Gameplay, Highlight game, Streamer, Trò chơi điện tử)",
    "tech_ai": "🤖 Công Nghệ & Trí Tuệ Nhân Tạo (AI, Review thiết bị, Lập trình, Đồ công nghệ)",
    "recap_stories": "🎬 Tóm Tắt Phim & Truyện (Review phim, Spoil phim, Tóm tắt truyện tranh/điện ảnh)",
    "learn_english": "🎓 Học Tiếng Anh & Kỹ Năng (Ngoại ngữ, Giao tiếp, Kỹ năng mềm, Bài giảng)",
    "infidelity_revenge": "💔 Ngoại Tình & Báo Thù (Mâu thuẫn hôn nhân, Drama tình ái, Trả đũa)",
    "father_inlaw_drama": "⚡ Bố Chồng Nàng Dâu (Mâu thuẫn gia đình, Gia đình cay đắng, Xung đột thế hệ)",
    "reddit_stories": "📱 Truyện Reddit & Tâm Sự (Reddit confessions, Storytime, Tâm sự đời thực)",
    "drama_expose": "🎭 Drama & Bóc Phốt (Exposé, Scandal người nổi tiếng, Vạch trần)",
    "true_crime": "🕵️ Vụ Án Có Thật & Bí Ẩn (Hồ sơ tội phạm, Trinh thám, Phá án, Bí ẩn chưa lời giải)",
    "horror_stories": "👻 Kinh Dị & Truyện Đêm Muộn (Truyện ma, Tâm linh kỳ bí, Quái đàm)",
    "history_geopolitics": "⚔️ Lịch Sử & Địa Chính Trị (Chiến tranh, Tư liệu lịch sử, Địa chính trị quốc tế)",
    "finance_money": "💰 Tài Chính & Kiếm Tiền (Đầu tư, Kinh doanh, Khởi nghiệp, Quản lý tài chính cá nhân)",
    "philosophy": "🧘 Triết Lý & Động Lực Sống (Bài học cuộc sống, Danh ngôn, Phát triển bản thân)",
}

class AIService:
    def __init__(self):
        pass

    def classify_niche_with_ai(
        self,
        channel_title: str,
        channel_description: str,
        video_titles: List[str],
        api_key: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Sử dụng Google Gemini AI để đọc tên kênh, mô tả và danh sách tiêu đề video,
        từ đó phân tích ngữ cảnh và phân loại vào đúng 1 ngách nội dung phù hợp nhất.
        """
        key = (api_key or os.environ.get("GEMINI_API_KEY") or "").strip()
        if not key:
            return None

        # Rút gọn thông tin để tối ưu token và độ trễ (< 500ms)
        clean_title = (channel_title or "Không rõ").strip()
        clean_desc = (channel_description or "")[:350].strip()
        sample_titles = [t.strip() for t in (video_titles or [])[:15] if t and t.strip()]

        if not sample_titles and not clean_desc:
            return None

        niches_formatted = "\n".join([f"- {code}: {desc}" for code, desc in VALID_NICHES.items()])

        system_instruction = (
            "Bạn là chuyên gia phân tích dữ liệu YouTube hàng đầu thế giới. "
            "Nhiệm vụ của bạn là dựa vào Tên kênh, Mô tả và Danh sách tiêu đề video gần đây "
            "để xác định kênh này thuộc ngách nội dung nào trong danh sách được cấp.\n\n"
            "Danh sách ngách hợp lệ:\n"
            f"{niches_formatted}\n\n"
            "Quy tắc quan trọng:\n"
            "1. Phải xem xét tổng thể các tiêu đề video (ví dụ: các video thử thách sinh tồn, tiền thưởng, "
            "trốn cảnh sát, người cuối cùng rời khỏi... như của MrBeast PHẢI thuộc ngách 'entertainment', "
            "kể cả khi bio có nhắc đến kênh phụ Gaming hoặc có 1 video mời streamer).\n"
            "2. Chỉ trả về duy nhất một chuỗi JSON hợp lệ với cấu trúc sau, không kèm bất kỳ giải thích nào bên ngoài:\n"
            "{\n"
            '  "niche_code": "<mã_ngách_hợp_lệ_trong_danh_sách>",\n'
            '  "confidence": <số_thực_từ_0_đến_1>,\n'
            '  "reason": "<1 câu ngắn gọn giải thích bằng tiếng Việt lý do phân loại>"\n'
            "}"
        )

        user_content = (
            f"Tên kênh: {clean_title}\n"
            f"Mô tả kênh: {clean_desc if clean_desc else 'Không có'}\n"
            f"15 Tiêu đề video gần nhất:\n" + "\n".join([f"- {t}" for t in sample_titles])
        )

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": system_instruction + "\n\n" + user_content}
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 200,
                "responseMimeType": "application/json"
            }
        }

        # Ưu tiên các model nhẹ, quota riêng biệt
        models = ["gemini-1.5-flash", "gemini-1.5-flash-8b", "gemini-2.0-flash"]
        rate_limited_count = 0
        for model in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
            try:
                resp = requests.post(url, json=payload, timeout=4.0)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if not candidates:
                        continue
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if not parts:
                        continue
                    raw_text = parts[0].get("text", "").strip()

                    # Làm sạch nếu model bọc trong ```json ... ```
                    if raw_text.startswith("```"):
                        raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
                        raw_text = re.sub(r"\s*```$", "", raw_text)

                    parsed = json.loads(raw_text)
                    niche_code = parsed.get("niche_code", "").strip().lower()
                    if niche_code in VALID_NICHES:
                        return {
                            "niche_code": niche_code,
                            "niche_name": VALID_NICHES[niche_code],
                            "confidence": float(parsed.get("confidence", 0.95)),
                            "reason": parsed.get("reason", f"Phân loại AI tự động qua mô hình {model}"),
                            "model_used": model
                        }
                    else:
                        logger.warning(f"AI returned invalid niche code: {niche_code}")
                elif resp.status_code == 429:
                    rate_limited_count += 1
                    logger.warning(f"Gemini API rate limit (429) on model {model}. Trying next model or fallback.")
                    continue
                elif resp.status_code in [400, 403]:
                    logger.warning(f"Gemini API error ({resp.status_code}): {resp.text[:150]}")
                    break
            except requests.exceptions.Timeout:
                logger.warning(f"Gemini API timeout with model {model}")
                continue
            except Exception as e:
                logger.warning(f"Error calling Gemini AI: {e}")
                continue

        if rate_limited_count > 0:
            return {"rate_limited": True}
        return None
