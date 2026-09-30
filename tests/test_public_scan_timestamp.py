import re

from tools.scan_public_repo import inside_frame_timestamp


def test_capture_timestamp_is_not_a_phone_number():
    line = '"path": "frames/step_after_20260914T13140987147.png"'
    match = re.search(r"1[3-9]\d{9}", line)
    assert match and inside_frame_timestamp(line, match)


def test_phone_beside_capture_timestamp_is_still_detected():
    line = 'frames/20260914T13140987147.png contact=' + '138' + '00000000'
    matches = list(re.finditer(r"1[3-9]\d{9}", line))
    assert inside_frame_timestamp(line, matches[0])
    assert not inside_frame_timestamp(line, matches[1])


def test_invalid_date_is_not_treated_as_a_capture_time():
    line = 'frames/20261314T' + '131409' + '87147.png'
    match = re.search(r"1[3-9]\d{9}", line)
    assert match and not inside_frame_timestamp(line, match)
