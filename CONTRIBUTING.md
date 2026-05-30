# Contributing to GraphRAG-Code

Thank you for your interest in contributing to GraphRAG-Code! Here is a quick guide to getting started:

## 1. Development Environment
The project requires Python 3.10+. Using `venv` is recommended:

```bash
python -m venv venv
source venv/bin/activate  # Or venv\Scripts\activate on Windows
pip install -e .
pip install -r requirements.txt
```

## 2. Running Tests
Before submitting a Pull Request, please ensure all tests pass successfully:

```bash
python -m unittest discover -s tests -v
```

## 3. Pull Request Process
1. Fork the repository.
2. Create a new branch for your feature/bugfix (`git checkout -b feature/awesome-feature`).
3. Commit your code with a clear message (`git commit -m "feat: Add awesome feature"`).
4. Push the branch to your fork (`git push origin feature/awesome-feature`).
5. Open a Pull Request on the original repository and describe your changes in detail.

All contributions are highly appreciated!
