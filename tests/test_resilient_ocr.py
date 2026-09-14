from PIL import Image

from winter_agent_v2.ocr import OCRToken, ResilientOCRBackend


class FlakyBackend:
    name = "flaky"

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    def recognize(self, image):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("temporary OCR failure")
        return (OCRToken("情报", 0.99),)


def test_resilient_ocr_recovers_with_bounded_backoff() -> None:
    waits = []
    backend = FlakyBackend(2)
    result = ResilientOCRBackend(backend, retries=2, initial_backoff=0.1, sleeper=waits.append).recognize(Image.new("RGB", (2, 2)))
    assert result[0].text == "情报"
    assert backend.calls == 3
    assert waits == [0.1, 0.2]


def test_resilient_ocr_does_not_retry_forever() -> None:
    backend = FlakyBackend(5)
    try:
        ResilientOCRBackend(backend, retries=2, initial_backoff=0, sleeper=lambda _: None).recognize(Image.new("RGB", (2, 2)))
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected bounded OCR failure")
    assert backend.calls == 3
