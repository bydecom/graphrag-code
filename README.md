# CodeGraph Enterprise 🚀
**Python-native Code Knowledge Graph với thuật toán Bidirectional PPR**

*Cách duy nhất tìm được cả upstream callers lẫn downstream dependencies trong một query, kèm source code snippet thật thay vì chỉ metadata.*

## Tại sao lại là CodeGraph? (The "Why")

Năm 2026, ném toàn bộ raw files vào AI Agent là không đủ. Việc này gây lãng phí token và làm tăng tỷ lệ Hallucination (ảo giác).  
CodeGraph giải quyết bài toán này bằng cách kết hợp **Abstract Syntax Tree (AST)** với thuật toán **Bidirectional Personalized PageRank (PPR)** chạy trên in-memory graph siêu tốc.

## 📊 Benchmark (baychecker codebase, 3 test cases)

| Query type        | Token savings | Accuracy vs baseline |
|-------------------|--------------|---------------------|
| Architecture Q&A  | ~89%         | Equal or better     |
| Blast radius      | ~97%         | Needs improvement*  |

*PPR seed resolution đang được cải thiện cho các hàm nội bộ (private methods / _method) và overhead latency có thể tăng ~20% ở codebase nhỏ, bù lại sẽ phát huy sức mạnh ở codebase lớn.

### 🔥 Điểm khác biệt cốt lõi (Core Differentiators) so với GitNexus / Market:
- **Bidirectional PPR:** Tự động tìm cả "Downstream Dependencies" (ai gọi ai) và "Upstream Callers" (Blast Radius) chỉ trong 1 Query. Trọng số 0.7 cho backward context giúp LLM có bức tranh toàn cảnh.
- **Source Code Extraction:** Bơm trực tiếp code thật (snippet) vào LLM thay vì chỉ ném metadata.
- **Interface Expansion (P0-2):** Tự động truy xuất các siblings và parent class thông qua keyword `extends`.
- **Python-Native:** Best-in-class cho hệ sinh thái Python (FastAPI, Django, Data Science).
- **Zero-Ops MCP Server:** Chuẩn giao thức Model Context Protocol. Cắm thẳng vào **Cursor** hoặc **Claude Desktop** trong 3 giây.

---

## 🛠 Cài đặt (Quick Start)

Dự án hiện đang hỗ trợ chạy nguyên bản thông qua hệ sinh thái Python 3.10+:

```bash
# Cài đặt từ mã nguồn
pip install .

# Khai báo API Key (Khuyên dùng Gemini 1.5 Pro / Flash)
export GEMINI_API_KEY="your-api-key"

# Khởi chạy Agent thông minh ngay trên Terminal
codegraph-agent
```

---

## 📊 Tích hợp Native IDE
Nếu bạn là tín đồ của **Cursor IDE** hoặc **Claude Desktop**, CodeGraph cung cấp sẵn file cấu hình để biến IDE của bạn thành siêu AI.
👉 Xem hướng dẫn chi tiết tại `docs/CURSOR_CLAUDE_INTEGRATION.md`

---

## 🏗 Kiến trúc (Architecture)
Hệ thống sử dụng `tree-sitter` để bóc tách codebase Python thành một mạng lưới đỉnh/cạnh, sau đó nạp vào bộ nhớ RAM bằng thư viện lõi C-backend `rustworkx` để tăng tốc độ chạy thuật toán.

## ⚠️ Known Limitations (Sự Thật Về Hệ Thống)
- Hiện tại CodeGraph Enterprise chỉ hỗ trợ hệ sinh thái Python (Multi-language là Roadmap cho các phiên bản tiếp theo).
- **Latency overhead ~20-25% ở codebase nhỏ** (< 20 files). Việc này là do chi phí khởi động MCP Server và nạp In-memory Graph. Tuy nhiên, nó sẽ phát huy sức mạnh vượt trội và đảo chiều ở các codebase khổng lồ.
- Thuật toán **PPR Seed Resolution** đối với các hàm nội bộ (private methods bắt đầu bằng `_`) đôi khi cần độ chính xác cao hơn, đang được nhóm phát triển tinh chỉnh.
- Chưa có tính năng Community Detection (Leiden algorithm) để gom cụm module lớn (Planned cho V2).

