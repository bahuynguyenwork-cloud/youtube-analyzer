# YouTube Trend & Channel Analyzer Pro 🚀

Ứng dụng phân tích kênh YouTube toàn diện, bóc tách từ khóa "gánh view", chấm điểm xu hướng thời gian thực và tự động phát hiện đối thủ cạnh tranh cùng ngách.

---

## 🌟 Tính Năng Nổi Bật

1. **Phân Tích Kênh Chuyên Sâu**:
   - Nhập bất kỳ URL kênh, `@handle` (ví dụ `@MrBeast`, `@KhoaPug`, `@veritasium`) hoặc tên kênh.
   - Trích xuất số lượng người đăng ký, tổng lượt xem, tần suất ra video (`upload cadence`), lượt xem trung bình và tỉ lệ view/sub.
   - Phát hiện các **Video Đột Biến View (Outliers / Viral Breakouts)** có lượng view cao vượt trội (x1.6 - x3.5 lần trung bình).

2. **Khai Phá Từ Khóa & Thẻ Tag**:
   - Bóc tách từ khóa đơn (1-gram) và cụm từ (2-gram, 3-gram) từ tiêu đề và mô tả video.
   - Phân loại **Từ khóa "Gánh View" (High Impact Keywords)** giúp kênh tăng trưởng lượt xem.
   - Phát hiện **Từ khóa kém hiệu quả (Low Impact Keywords)** để tối ưu lại.
   - Bảng tổng hợp Hashtags và phân cụm chủ đề tự động (Công nghệ, Khoa học, Du lịch, Ẩm thực, Game, Kinh doanh...).

3. **Đo Lường Xu Hướng Thời Gian Thực (Trend & Momentum Engine)**:
   - Chấm điểm **Trend Score (0 - 100)** dựa trên tốc độ tăng trưởng view gần đây (Velocity Ratio) và biến động tìm kiếm.
   - Tích hợp trực tiếp biểu đồ **Google Trends 30 ngày** qua `pytrends`.
   - Phát hiện các cụm từ tìm kiếm liên quan đang bùng nổ (**Breakout / Rising Searches**).

4. **Khám Phá Nguồn Tương Tự & Đối Thủ Cạnh Tranh (Competitor Radar)**:
   - Tự động tìm kiếm các kênh đối thủ trong cùng phân khúc nội dung.
   - Thống kê lượt xem trung bình của đối thủ đối với các chủ đề tương tự.
   - Nút phân tích 1-click để chuyển sang soi kênh đối thủ ngay lập tức.

5. **Chiến Lược Nội Dung & Ý Tưởng Tiêu Đề Bắt Trend**:
   - Nhận định chuyên sâu về độ khỏe của kênh từ AI.
   - Gợi ý **8 mẫu tiêu đề video click-worthy** sẵn sàng sử dụng (hỗ trợ 1-click sao chép).
   - Đề xuất bộ thẻ tag SEO tối ưu cho video tiếp theo.

6. **Tra Cứu Từ Khóa Độc Lập (Keyword Explorer)**:
   - Nhập bất kỳ từ khóa nào để kiểm tra độ hot, xem biểu đồ xu hướng 30 ngày qua tại Việt Nam hoặc Toàn cầu.
   - Xem ngay danh sách các video YouTube đang đứng đầu chủ đề đó.

7. **Bảng Tin Đang Thịnh Hành (Trending Feed)**:
   - Quét nhanh các video đang nằm trong Tab Thịnh Hành (YouTube Trending) hiện tại.

---

## 🛠️ Cấu Trúc Dự Án

```
d:\youtube_analysis\
├── backend\
│   ├── main.py                     # Máy chủ FastAPI & REST API Endpoints
│   ├── services\
│   │   ├── youtube_service.py       # Trích xuất dữ liệu kênh & video (yt-dlp)
│   │   ├── keyword_service.py       # Bóc tách từ khóa, hashtag, phân loại
│   │   ├── trend_service.py         # Đo lường xung lượng & Google Trends (pytrends)
│   │   ├── competitor_service.py    # Tìm kiếm đối thủ và kênh cùng ngách
│   │   └── strategy_service.py      # Gợi ý tiêu đề & chiến lược nội dung
│   └── test_api.py                 # Kịch bản kiểm thử tự động
├── frontend\
│   └── index.html                  # Giao diện Dashboard SPA hiện đại (Tailwind + Chart.js)
├── run_app.py                      # Script khởi chạy một lệnh (tự mở trình duyệt)
├── run.bat                         # File nhấp đúp khởi chạy trên Windows
├── requirements.txt                # Danh sách thư viện cần thiết
└── README.md                       # Tài liệu hướng dẫn sử dụng
```

---

## 🚀 Hướng Dẫn Khởi Chạy

### Cách 1: Chạy file Batch (Đơn giản nhất trên Windows)
Nhấp đúp chuột vào file:
```
run.bat
```

### Cách 2: Chạy bằng lệnh Python
Mở Terminal / PowerShell tại thư mục `d:\youtube_analysis`:
```bash
python run_app.py
```

Ứng dụng sẽ tự động mở trình duyệt web tại địa chỉ:
👉 **`http://localhost:8000`**
