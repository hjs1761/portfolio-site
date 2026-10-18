from guard_core.parse import expand_vars, tokenize, parse_segments, norm, is_mount

def test_expand_vars_quoted_assignment():
    cmd = 'MP="/mnt/prod/shop/fo"\ncp a.php "$MP/a.php"'
    assert '/mnt/prod/shop/fo/a.php' in expand_vars(cmd)

def test_tokenize_stops_at_next_command_and_skips_flags():
    assert tokenize('-p "a b.php" /mnt/prod/x && echo hi') == ["a b.php", "/mnt/prod/x"]

def test_parse_segments_uses_leading_verb_only():
    segs = parse_segments('python3 - <<EOF\nprint("sed -i x /mnt/prod/shop/fo/coupon.php")\nEOF')
    assert all(v != "sed" for v, *_ in segs)        # heredoc 안 문자열은 명령이 아니다

def test_parse_segments_env_prefix():
    (verb, flags, args, _), = parse_segments("LANG=C sed -i s/a/b/ /mnt/prod/shop/fo/coupon.php")
    assert verb == "sed" and flags == ["-i"] and args[-1].endswith("coupon.php")

def test_norm_relative_to_cwd():
    assert norm("fo/coupon.php", "/work/shop") == "/work/shop/fo/coupon.php"

def test_is_mount():
    assert is_mount("/mnt/prod/shop/fo/coupon.php") and not is_mount("/work/shop/fo/coupon.php")


# --- 아래는 이식하며 덧붙인 것 ---

def test_norm_defaults_to_default_cwd():
    assert norm("fo/coupon.php", None) == "/work/shop/fo/coupon.php"

def test_norm_home_is_virtual():
    """실제 서버 계정의 홈·다른 계정의 홈(~root)이 응답에 새지 않도록 `~` 는 가상 홈으로만 푼다."""
    assert norm("~/shop/fo/coupon.php", "/x") == "/work/shop/fo/coupon.php"
    assert norm("~", "/x") == "/work"
    assert norm("~root/a.php", "/x") == "/x/~root/a.php"

def test_expand_vars_braced_and_chained():
    cmd = 'R=/mnt/prod\nD="${R}/shop"\ncp a.php "$D/fo/a.php"'
    assert "/mnt/prod/shop/fo/a.php" in expand_vars(cmd)

def test_tokenize_stops_at_redirect():
    assert tokenize("a.php b.php > out.txt") == ["a.php", "b.php"]
