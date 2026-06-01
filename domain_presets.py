"""
Bộ thuật ngữ theo lĩnh vực — tự động nạp khi người dùng chọn domain.
Mỗi domain: {"terms": [(từ_gốc, dịch_vi), ...], "context": "mô tả ngắn cho AI prompt"}
"""

DOMAINS: dict = {
    "Chung (không chọn)": {
        "context": "",
        "terms": [],
    },

    # ── Cầu lông ────────────────────────────────────────────────────────────────
    "🏸  Cầu lông": {
        "context": (
            "Đây là video về cầu lông (badminton). "
            "Từ '球' phải dịch là 'cầu', KHÔNG phải 'bóng'. "
            "Dùng đúng thuật ngữ cầu lông tiếng Việt."
        ),
        "terms": [
            ("羽毛球", "cầu lông"),
            ("羽球",   "cầu lông"),
            ("球",     "cầu"),
            ("球拍",   "vợt"),
            ("球网",   "lưới"),
            ("发球",   "phát cầu"),
            ("接球",   "đỡ cầu"),
            ("杀球",   "smash"),
            ("扣球",   "smash"),
            ("吊球",   "cầu thả"),
            ("挑球",   "cầu nhấc"),
            ("推球",   "cầu đẩy"),
            ("搓球",   "cầu cuộn"),
            ("高远球", "cầu cao xa"),
            ("平高球", "cầu bình cao"),
            ("网前球", "cầu lưới"),
            ("后场",   "cuối sân"),
            ("前场",   "lưới sân"),
            ("中场",   "giữa sân"),
            ("单打",   "đơn"),
            ("双打",   "đôi"),
            ("混双",   "đôi nam nữ"),
            ("正手",   "thuận tay"),
            ("反手",   "trái tay"),
            ("步法",   "bộ bước chân"),
            ("发球区", "ô phát cầu"),
            ("界外",   "ngoài biên"),
            ("界内",   "trong biên"),
            ("换边",   "đổi sân"),
            ("局",     "ván"),
            ("比分",   "tỷ số"),
            ("裁判",   "trọng tài"),
            ("运动员", "vận động viên"),
            ("教练",   "huấn luyện viên"),
        ],
    },

    # ── Bóng đá ─────────────────────────────────────────────────────────────────
    "⚽  Bóng đá": {
        "context": (
            "Đây là video về bóng đá (football/soccer). "
            "Dùng đúng thuật ngữ bóng đá tiếng Việt."
        ),
        "terms": [
            ("足球",   "bóng đá"),
            ("球",     "bóng"),
            ("球门",   "cầu môn"),
            ("射门",   "sút cầu môn"),
            ("进球",   "ghi bàn"),
            ("点球",   "phạt đền"),
            ("越位",   "việt vị"),
            ("红牌",   "thẻ đỏ"),
            ("黄牌",   "thẻ vàng"),
            ("角球",   "phạt góc"),
            ("任意球", "đá phạt"),
            ("上半场", "hiệp 1"),
            ("下半场", "hiệp 2"),
            ("加时赛", "hiệp phụ"),
            ("点球大战","loạt đá penalty"),
            ("守门员", "thủ môn"),
            ("后卫",   "hậu vệ"),
            ("中场",   "tiền vệ"),
            ("前锋",   "tiền đạo"),
            ("教练",   "huấn luyện viên"),
            ("裁判",   "trọng tài"),
        ],
    },

    # ── Bóng rổ ─────────────────────────────────────────────────────────────────
    "🏀  Bóng rổ": {
        "context": (
            "Đây là video về bóng rổ (basketball). "
            "Dùng đúng thuật ngữ bóng rổ tiếng Việt."
        ),
        "terms": [
            ("篮球",   "bóng rổ"),
            ("球",     "bóng"),
            ("投篮",   "ném rổ"),
            ("三分球", "ném 3 điểm"),
            ("上篮",   "layup"),
            ("扣篮",   "dunk"),
            ("传球",   "chuyền bóng"),
            ("运球",   "dribble"),
            ("犯规",   "phạm lỗi"),
            ("罚球",   "ném phạt"),
            ("快攻",   "phản công nhanh"),
            ("防守",   "phòng thủ"),
            ("进攻",   "tấn công"),
            ("篮板",   "bắt bảng"),
            ("球队",   "đội bóng"),
            ("教练",   "huấn luyện viên"),
        ],
    },

    # ── Cầu lông (Hàn Quốc) ─────────────────────────────────────────────────────
    "🏸  Cầu lông (Hàn)": {
        "context": (
            "Đây là video về cầu lông (배드민턴/badminton). "
            "Dùng đúng thuật ngữ cầu lông tiếng Việt."
        ),
        "terms": [
            ("배드민턴", "cầu lông"),
            ("셔틀콕",  "cầu"),
            ("라켓",    "vợt"),
            ("서브",    "phát cầu"),
            ("스매시",  "smash"),
            ("네트",    "lưới"),
            ("단식",    "đơn"),
            ("복식",    "đôi"),
            ("혼합복식","đôi nam nữ"),
            ("코치",    "huấn luyện viên"),
        ],
    },

    # ── Tennis ──────────────────────────────────────────────────────────────────
    "🎾  Tennis": {
        "context": (
            "Đây là video về tennis. "
            "Dùng đúng thuật ngữ tennis tiếng Việt."
        ),
        "terms": [
            ("网球",   "tennis"),
            ("球",     "bóng"),
            ("球拍",   "vợt"),
            ("发球",   "giao bóng"),
            ("接发球", "đỡ giao bóng"),
            ("底线球", "bóng đáy sân"),
            ("网前",   "lên lưới"),
            ("截击",   "volley"),
            ("爱司球", "ace"),
            ("双误",   "double fault"),
            ("破发",   "phá giao bóng"),
            ("比赛",   "trận đấu"),
            ("局",     "game"),
            ("盘",     "set"),
            ("教练",   "huấn luyện viên"),
        ],
    },

    # ── Bóng bàn ────────────────────────────────────────────────────────────────
    "🏓  Bóng bàn": {
        "context": (
            "Đây là video về bóng bàn (table tennis/ping pong). "
            "Dùng đúng thuật ngữ bóng bàn tiếng Việt."
        ),
        "terms": [
            ("乒乓球", "bóng bàn"),
            ("球",     "bóng"),
            ("球拍",   "vợt bàn"),
            ("发球",   "phát bóng"),
            ("搓球",   "cắt bóng"),
            ("拉球",   "topspin"),
            ("弧圈球", "bóng xoáy"),
            ("正手",   "thuận tay"),
            ("反手",   "trái tay"),
            ("台内球", "bóng trong bàn"),
            ("台外球", "bóng ngoài bàn"),
            ("教练",   "huấn luyện viên"),
        ],
    },

    # ── Gym / Thể hình ──────────────────────────────────────────────────────────
    "💪  Gym / Thể hình": {
        "context": (
            "Đây là video về tập gym, thể hình, thể dục. "
            "Dùng thuật ngữ gym/thể hình tiếng Việt tự nhiên."
        ),
        "terms": [
            ("健身",   "tập gym"),
            ("肌肉",   "cơ bắp"),
            ("胸肌",   "cơ ngực"),
            ("背肌",   "cơ lưng"),
            ("腹肌",   "cơ bụng (6 múi)"),
            ("二头肌", "bắp tay trước"),
            ("三头肌", "bắp tay sau"),
            ("卧推",   "đẩy tạ nằm"),
            ("深蹲",   "squat"),
            ("硬拉",   "deadlift"),
            ("引体向上","kéo xà"),
            ("哑铃",   "tạ đôi"),
            ("杠铃",   "tạ đòn"),
            ("组",     "hiệp"),
            ("次",     "lần"),
            ("休息",   "nghỉ"),
            ("教练",   "huấn luyện viên/PT"),
        ],
    },

    # ── Nấu ăn / Ẩm thực ────────────────────────────────────────────────────────
    "🍜  Nấu ăn / Ẩm thực": {
        "context": (
            "Đây là video về nấu ăn, ẩm thực. "
            "Dùng thuật ngữ nấu ăn tiếng Việt tự nhiên, giữ tên món ăn gốc nếu phổ biến."
        ),
        "terms": [
            ("食材",   "nguyên liệu"),
            ("调料",   "gia vị"),
            ("锅",     "chảo/nồi"),
            ("炒",     "xào"),
            ("炸",     "chiên"),
            ("蒸",     "hấp"),
            ("煮",     "nấu"),
            ("烤",     "nướng"),
            ("腌制",   "ướp"),
            ("切",     "thái/cắt"),
            ("搅拌",   "khuấy"),
        ],
    },
}


def get_terms(domain_label: str) -> list:
    """Trả về list (từ_gốc, dịch_vi) cho domain, hoặc [] nếu không có."""
    return DOMAINS.get(domain_label, {}).get("terms", [])


def get_context(domain_label: str) -> str:
    """Trả về chuỗi context ngắn để inject vào AI prompt."""
    return DOMAINS.get(domain_label, {}).get("context", "")


def domain_labels() -> list:
    """Trả về danh sách tên domain để hiển thị trong dropdown."""
    return list(DOMAINS.keys())
