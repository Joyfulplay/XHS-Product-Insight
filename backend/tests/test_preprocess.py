from app.preprocess.cleaner import TextCleaner


def test_cleaner_removes_extra_whitespace():
    text = "   hello   world   "
    result = TextCleaner.clean(text)
    assert result == "hello world"
