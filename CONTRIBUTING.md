# Contributing to CodeGraph

Cảm ơn bạn đã quan tâm đóng góp vào CodeGraph Enterprise! Dưới đây là hướng dẫn nhanh để bắt đầu:

## 1. Môi trường Development
Dự án yêu cầu Python 3.10+. Khuyên dùng `venv`:

```bash
python -m venv venv
source venv/bin/activate  # Hoặc venv\Scripts\activate trên Windows
pip install -e .
pip install -r requirements.txt
```

## 2. Cách chạy Tests
Trước khi tạo Pull Request, vui lòng đảm bảo mọi test đều vượt qua:

```bash
python -m unittest discover -s tests -v
```

## 3. Quy trình Submit PR
1. Fork repository.
2. Tạo branch mới cho tính năng/bugfix (`git checkout -b feature/awesome-feature`).
3. Commit code với thông điệp rõ ràng (`git commit -m "feat: Thêm tính năng awesome"`).
4. Đẩy branch lên fork của bạn (`git push origin feature/awesome-feature`).
5. Mở Pull Request trên repository gốc và mô tả chi tiết thay đổi của bạn.

Mọi đóng góp đều được trân trọng!
