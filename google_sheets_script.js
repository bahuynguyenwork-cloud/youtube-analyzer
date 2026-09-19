// ======================================================
// YOUTUBE VIDEO PUBLISH TIME CHECKER (PRO VERSION)
// Google Sheets + YouTube Data API v3
// Tự động chuyển đổi toàn bộ giờ đăng sang Giờ Việt Nam (UTC+7)
// Hỗ trợ lấy theo Channel ID (UC...) kèm Lượt xem và Thứ trong tuần
// ======================================================

// =========================
// 1. ĐIỀN THÔNG TIN CỦA BẠN
// =========================

// Điền API Key của bạn từ Google Cloud Console (YouTube Data API v3)
const API_KEY = "DÁN_API_KEY_VÀO_ĐÂY";

// Điền Channel ID của kênh (bắt đầu bằng UC, ví dụ: UC_x5XG1OV2P6uZZ5FSM9Ttw)
const CHANNEL_ID = "DÁN_CHANNEL_ID_VÀO_ĐÂY";

// Múi giờ Việt Nam (UTC+7)
const TIMEZONE = "Asia/Ho_Chi_Minh";

// Tên Sheet sẽ ghi kết quả
const SHEET_NAME = "YouTube Publish Times";


// ======================================================
// 2. TẠO MENU TIỆN ÍCH TRÊN GOOGLE SHEETS
// ======================================================

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("🎬 YouTube Tracker")
    .addItem("📥 Lấy Toàn Bộ Giờ Đăng Video (Theo UC)", "getYouTubeVideos")
    .addItem("🔄 Cập Nhật Lại Giờ Đăng & Lượt Xem", "updatePublishTimes")
    .addToUi();
}


// ======================================================
// 3. KIỂM TRA THÔNG TIN HỢP LỆ
// ======================================================

function checkApiKey() {
  if (!API_KEY || API_KEY === "DÁN_API_KEY_VÀO_ĐÂY") {
    throw new Error("⚠️ Bạn chưa nhập API_KEY! Hãy dán YouTube Data API v3 key vào dòng const API_KEY.");
  }

  if (!CHANNEL_ID || CHANNEL_ID === "DÁN_CHANNEL_ID_VÀO_ĐÂY") {
    throw new Error("⚠️ Bạn chưa nhập CHANNEL_ID! Hãy dán mã kênh (bắt đầu bằng UC...) vào dòng const CHANNEL_ID.");
  }
}


// ======================================================
// 4. LẤY TOÀN BỘ VIDEO & GIỜ ĐĂNG THEO MÃ UC
// ======================================================

function getYouTubeVideos() {
  checkApiKey();
  const sheet = getSheet();

  // Xóa trắng bảng cũ
  sheet.clear();

  // Tiêu đề các cột
  sheet.appendRow([
    "STT",
    "Video ID",
    "Tiêu đề",
    "Ngày đăng (VN)",
    "Giờ đăng (VN)",
    "Ngày + giờ đăng",
    "Thứ",
    "Lượt xem",
    "URL Video"
  ]);

  // BƯỚC 1: LẤY UPLOADS PLAYLIST ID
  // Với mọi kênh YouTube có Channel ID là UCxxxx, Uploads Playlist ID sẽ là UUxxxx
  let uploadsPlaylistId = "";
  if (CHANNEL_ID.startsWith("UC")) {
    uploadsPlaylistId = "UU" + CHANNEL_ID.substring(2);
  } else {
    // Nếu không phải dạng UC, gọi API để lấy uploads playlist
    const channelUrl = "https://www.googleapis.com/youtube/v3/channels?part=contentDetails&id=" +
      encodeURIComponent(CHANNEL_ID) + "&key=" + encodeURIComponent(API_KEY);
    const channelResponse = UrlFetchApp.fetch(channelUrl);
    const channelData = JSON.parse(channelResponse.getContentText());

    if (!channelData.items || channelData.items.length === 0) {
      throw new Error("Không tìm thấy kênh với Channel ID: " + CHANNEL_ID);
    }
    uploadsPlaylistId = channelData.items[0].contentDetails.relatedPlaylists.uploads;
  }

  // BƯỚC 2: LẤY DANH SÁCH VIDEO ID
  let videoIds = [];
  let nextPageToken = "";

  do {
    let playlistUrl = "https://www.googleapis.com/youtube/v3/playlistItems" +
      "?part=contentDetails" +
      "&playlistId=" + encodeURIComponent(uploadsPlaylistId) +
      "&maxResults=50" +
      "&key=" + encodeURIComponent(API_KEY);

    if (nextPageToken) {
      playlistUrl += "&pageToken=" + encodeURIComponent(nextPageToken);
    }

    const response = UrlFetchApp.fetch(playlistUrl);
    const data = JSON.parse(response.getContentText());

    if (data.error) {
      throw new Error("Lỗi YouTube API: " + data.error.message);
    }

    data.items.forEach(item => {
      if (item.contentDetails && item.contentDetails.videoId) {
        videoIds.push(item.contentDetails.videoId);
      }
    });

    nextPageToken = data.nextPageToken || "";
  } while (nextPageToken);

  // BƯỚC 3: LẤY CHI TIẾT VIDEO (TIÊU ĐỀ, NGÀY ĐĂNG, LƯỢT XEM)
  let allRows = [];
  let counter = 1;
  const daysOfWeek = ["Chủ Nhật", "Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7"];

  for (let i = 0; i < videoIds.length; i += 50) {
    const batch = videoIds.slice(i, i + 50);
    const videoUrl = "https://www.googleapis.com/youtube/v3/videos" +
      "?part=snippet,statistics" +
      "&id=" + batch.join(",") +
      "&key=" + encodeURIComponent(API_KEY);

    const response = UrlFetchApp.fetch(videoUrl);
    const data = JSON.parse(response.getContentText());

    if (data.error) {
      throw new Error("Lỗi lấy thông tin video: " + data.error.message);
    }

    data.items.forEach(video => {
      const videoId = video.id;
      const title = video.snippet.title;
      const publishedAt = video.snippet.publishedAt;
      const viewCount = video.statistics ? Number(video.statistics.viewCount || 0) : 0;

      const date = new Date(publishedAt);

      // Quy đổi sang Giờ Việt Nam (Asia/Ho_Chi_Minh)
      const dateVN = Utilities.formatDate(date, TIMEZONE, "dd/MM/yyyy");
      const timeVN = Utilities.formatDate(date, TIMEZONE, "HH:mm:ss");
      const dateTimeVN = Utilities.formatDate(date, TIMEZONE, "dd/MM/yyyy HH:mm:ss");
      const dayOfWeek = daysOfWeek[date.getDay()];
      const url = "https://www.youtube.com/watch?v=" + videoId;

      allRows.push([
        counter,
        videoId,
        title,
        dateVN,
        timeVN,
        dateTimeVN,
        dayOfWeek,
        viewCount,
        url
      ]);

      counter++;
    });
  }

  // BƯỚC 4: GHI DỮ LIỆU VÀ ĐỊNH DẠNG BẢNG
  if (allRows.length > 0) {
    sheet.getRange(2, 1, allRows.length, 9).setValues(allRows);
  }

  sheet.setFrozenRows(1);
  sheet.getRange(1, 1, 1, 9).setFontWeight("bold").setBackground("#f1f5f9");
  sheet.autoResizeColumns(1, 9);

  SpreadsheetApp.getUi().alert(
    "✅ Hoàn Thành Xuất Sắc!\n\n" +
    "Đã lấy tổng cộng: " + allRows.length + " video từ kênh " + CHANNEL_ID + "\n\n" +
    "Toàn bộ giờ đăng đã được chuyển sang Giờ Việt Nam (UTC+7)."
  );
}


// ======================================================
// 5. CẬP NHẬT LẠI GIỜ ĐĂNG VÀ LƯỢT XEM
// ======================================================

function updatePublishTimes() {
  checkApiKey();
  const sheet = getSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    SpreadsheetApp.getUi().alert("Chưa có dữ liệu video để cập nhật!");
    return;
  }

  const videoIds = sheet.getRange(2, 2, lastRow - 1, 1).getValues().flat();
  let updated = 0;
  const daysOfWeek = ["Chủ Nhật", "Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7"];

  for (let i = 0; i < videoIds.length; i += 50) {
    const batch = videoIds.slice(i, i + 50).filter(String);
    if (batch.length === 0) continue;

    const url = "https://www.googleapis.com/youtube/v3/videos" +
      "?part=snippet,statistics" +
      "&id=" + batch.join(",") +
      "&key=" + encodeURIComponent(API_KEY);

    const response = UrlFetchApp.fetch(url);
    const data = JSON.parse(response.getContentText());

    data.items.forEach(video => {
      const index = videoIds.indexOf(video.id);
      if (index === -1) return;

      const row = index + 2;
      const date = new Date(video.snippet.publishedAt);
      const viewCount = video.statistics ? Number(video.statistics.viewCount || 0) : 0;

      const dateVN = Utilities.formatDate(date, TIMEZONE, "dd/MM/yyyy");
      const timeVN = Utilities.formatDate(date, TIMEZONE, "HH:mm:ss");
      const dateTimeVN = Utilities.formatDate(date, TIMEZONE, "dd/MM/yyyy HH:mm:ss");
      const dayOfWeek = daysOfWeek[date.getDay()];

      sheet.getRange(row, 3).setValue(video.snippet.title);
      sheet.getRange(row, 4).setValue(dateVN);
      sheet.getRange(row, 5).setValue(timeVN);
      sheet.getRange(row, 6).setValue(dateTimeVN);
      sheet.getRange(row, 7).setValue(dayOfWeek);
      sheet.getRange(row, 8).setValue(viewCount);

      updated++;
    });
  }

  SpreadsheetApp.getUi().alert("✅ Đã cập nhật thành công " + updated + " video!");
}

function getSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(SHEET_NAME);
  if (!sheet) {
    sheet = ss.insertSheet(SHEET_NAME);
  }
  return sheet;
}
