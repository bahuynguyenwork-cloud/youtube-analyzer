import re
from collections import Counter, defaultdict
from typing import List, Dict, Any

STOP_WORDS = {
    'và', 'của', 'là', 'có', 'cho', 'với', 'trong', 'được', 'khi', 'các', 'một',
    'những', 'để', 'ở', 'tại', 'về', 'này', 'đó', 'từ', 'sẽ', 'không', 'như',
    'đã', 'ra', 'vào', 'lại', 'làm', 'cũng', 'hay', 'rồi', 'sau', 'người', 'gì',
    'nào', 'sao', 'thì', 'lên', 'xuống', 'qua', 'nhưng', 'bị', 'bởi', 'theo',
    'tập', 'phần', 'full', 'video', 'mới', 'nhất', 'cùng', 'cực', 'quá', 'rất',
    'official', 'trailer', 'teasing', 'lyrics', 'mv', 'hd', 'review', 'vlog',
    'the', 'and', 'to', 'of', 'a', 'in', 'that', 'is', 'for', 'it', 'on', 'with',
    'as', 'this', 'was', 'at', 'by', 'an', 'be', 'from', 'or', 'are', 'your',
    'all', 'you', 'how', 'what', 'why', 'who', 'where', 'when', 'my', 'we',
    'so', 'if', 'me', 'out', 'up', 'down', 'no', 'not', 'can', 'just', 'more', 'about'
}

class KeywordService:
    def __init__(self):
        pass

    def clean_text(self, text: str) -> str:
        text = re.sub(r'https?://\S+|www\.\S+', '', text)
        # Thay thế các ký tự ngăn cách thông dụng (| / \ ㅣ - _ • · ~ ! ? , .) thành khoảng trắng
        text = re.sub(r'[\|\/\\ㅣl\-_•·~#:\!\?\,\.\[\]\(\)\{\}\<\>\"\']', ' ', text)
        text = re.sub(r'[^\w\s\dàáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]', ' ', text, flags=re.UNICODE)
        text = re.sub(r'\s+', ' ', text)
        return text.lower().strip()

    def extract_keywords_from_videos(self, videos: List[Dict[str, Any]], channel_avg_views: int) -> Dict[str, Any]:
        if not videos:
            return {
                'top_keywords': [],
                'high_impact_keywords': [],
                'low_impact_keywords': [],
                'hashtags': [],
                'topic_categories': [],
                'copyable_tags_csv': '',
                'copyable_tags_list': [],
                'ngrams_2_3': []
            }

        word_freq = Counter()
        phrase_freq = Counter()
        keyword_views = defaultdict(list)
        hashtag_freq = Counter()

        for video in videos:
            title = video.get('title', '')
            desc = video.get('description', '')
            views = video.get('view_count', 0)

            found_hashtags = re.findall(r'#(\w+)', f'{title} {desc}')
            for ht in found_hashtags:
                ht_clean = ht.lower()
                if len(ht_clean) >= 2:
                    hashtag_freq[ht_clean] += 1

            cleaned_title = self.clean_text(title)
            tokens = [w for w in cleaned_title.split() if len(w) >= 2 and w not in STOP_WORDS and not w.isdigit()]

            unique_tokens_in_title = set(tokens)
            for token in unique_tokens_in_title:
                word_freq[token] += 1
                keyword_views[token].append(views)

            for i in range(len(tokens) - 1):
                phrase = f'{tokens[i]} {tokens[i+1]}'
                phrase_freq[phrase] += 1
                keyword_views[phrase].append(views)

            for i in range(len(tokens) - 2):
                phrase3 = f'{tokens[i]} {tokens[i+1]} {tokens[i+2]}'
                phrase_freq[phrase3] += 1
                keyword_views[phrase3].append(views)

        all_candidates = Counter()
        # Thử lấy từ khóa xuất hiện >= 2 lần
        for k, v in word_freq.items():
            if v >= 2:
                all_candidates[k] = v
        for k, v in phrase_freq.items():
            if v >= 2:
                all_candidates[k] = v * 1.5

        # Nếu mẫu video nhỏ hoặc ít từ lặp lại, lấy các từ đơn nổi bật nhất
        if len(all_candidates) < 5:
            for k, v in word_freq.most_common(20):
                if k not in all_candidates:
                    all_candidates[k] = v
            for k, v in phrase_freq.most_common(10):
                if k not in all_candidates:
                    all_candidates[k] = v * 1.2

        ranked_keywords = []
        for kw, _ in all_candidates.most_common(40):
            view_list = keyword_views.get(kw, [])
            if not view_list:
                continue
            count = len(view_list)
            avg_kw_views = int(sum(view_list) / count)
            total_kw_views = sum(view_list)
            efficiency_ratio = round(avg_kw_views / max(channel_avg_views, 1), 2)

            ranked_keywords.append({
                'keyword': kw,
                'occurrences': count,
                'avg_views': avg_kw_views,
                'total_views': total_kw_views,
                'efficiency_ratio': efficiency_ratio,
                'is_high_performer': efficiency_ratio >= 1.15
            })

        high_impact = [k for k in ranked_keywords if k['efficiency_ratio'] >= 1.1]
        high_impact.sort(key=lambda x: x['avg_views'], reverse=True)

        low_impact = [k for k in ranked_keywords if k['efficiency_ratio'] <= 0.85 and k['occurrences'] >= 2]
        low_impact.sort(key=lambda x: x['efficiency_ratio'])

        top_hashtags = [{'hashtag': f'#{tag}', 'count': cnt} for tag, cnt in hashtag_freq.most_common(15)]
        topic_categories = self.categorize_channel_topic(ranked_keywords)

        # Xây dựng danh sách từ khóa bắt trend sẵn sàng 1-click copy và chuỗi dán thẳng YouTube Studio
        copyable_tags = []
        for hk in high_impact[:12]:
            if hk['keyword'] not in copyable_tags:
                copyable_tags.append(hk['keyword'])
        for tk in ranked_keywords[:25]:
            if tk['keyword'] not in copyable_tags:
                copyable_tags.append(tk['keyword'])
        for ht in top_hashtags[:8]:
            raw_tag = ht['hashtag'].replace('#', '')
            if raw_tag not in copyable_tags:
                copyable_tags.append(raw_tag)

        # Chuỗi CSV phân cách bởi dấu phẩy
        copyable_tags_csv = ", ".join(copyable_tags)

        # Xây dựng n-grams (cụm từ 2-3 chữ)
        ngrams_list = []
        for phrase, cnt in phrase_freq.most_common(20):
            views_l = keyword_views.get(phrase, [])
            avg_v = int(sum(views_l) / len(views_l)) if views_l else 0
            ngrams_list.append({
                'phrase': phrase,
                'count': cnt,
                'avg_views': avg_v
            })

        # Dự phòng nếu tiêu đề quá ngắn hoặc ít lặp cụm từ
        if not ngrams_list and len(ranked_keywords) >= 2:
            top_w = [k['keyword'] for k in ranked_keywords[:6]]
            for i in range(len(top_w) - 1):
                p = f"{top_w[i]} {top_w[i+1]}"
                ngrams_list.append({
                    'phrase': p,
                    'count': 1,
                    'avg_views': int((ranked_keywords[i]['avg_views'] + ranked_keywords[i+1]['avg_views']) / 2)
                })

        return {
            'top_keywords': ranked_keywords[:25],
            'high_impact_keywords': high_impact[:10],
            'low_impact_keywords': low_impact[:8],
            'hashtags': top_hashtags,
            'topic_categories': topic_categories,
            'copyable_tags_csv': copyable_tags_csv,
            'copyable_tags_list': copyable_tags,
            'ngrams_2_3': ngrams_list
        }

    def categorize_channel_topic(self, keywords: List[Dict[str, Any]]) -> List[str]:
        combined_text = ' '.join([k['keyword'] for k in keywords[:15]]).lower()
        topics = []

        category_rules = {
            'Công nghệ & Lập trình': ['code', 'python', 'lập trình', 'ai', 'tech', 'software', 'dev', 'web', 'javascript', 'computer', 'app'],
            'Khoa học & Giáo dục': ['khoa học', 'vũ trụ', 'bí ẩn', 'lịch sử', 'nghiên cứu', 'vật lý', 'giải thích', 'science', 'physics', 'space', 'earth', 'history', 'experiment', 'solar', 'eclipse', 'gravity'],
            'Ẩm thực & Nấu ăn': ['món ăn', 'nấu', 'ẩm thực', 'ăn', 'quán', 'cơm', 'ngon', 'street food', 'cooking', 'recipe', 'food', 'mukbang'],
            'Du lịch & Khám phá': ['du lịch', 'khám phá', 'trải nghiệm', 'chuyến đi', 'địa điểm', 'travel', 'trip', 'explore', 'vacation', 'hotel'],
            'Kinh doanh & Tài chính': ['tiền', 'kiếm tiền', 'kinh doanh', 'đầu tư', 'chứng khoán', 'crypto', 'finance', 'money', 'business', 'investing', 'passive income'],
            'Game & Esports': ['game', 'gaming', 'play', 'thử thách', 'minecraft', 'roblox', 'highlight', 'gameplay', 'walkthrough'],
            'Giải trí & Đời sống': ['hài', 'vui', 'thử thách', 'cuộc sống', 'challenge', 'vlog', 'prank', 'react', 'story']
        }

        for cat, words in category_rules.items():
            if any(w in combined_text for w in words):
                topics.append(cat)

        if not topics:
            topics.append('Chủ đề đa dạng / Tổng hợp')

        return topics
