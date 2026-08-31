from app.infrastructure.auth.password_hashing import hash_password, verify_password


def test_verify_password_accepts_the_correct_password():
    hashed = hash_password("correct horse battery staple")

    assert verify_password("correct horse battery staple", hashed) is True


def test_verify_password_rejects_the_wrong_password():
    hashed = hash_password("correct horse battery staple")

    assert verify_password("wrong password", hashed) is False


def test_hash_password_never_stores_the_plaintext():
    hashed = hash_password("super-secret")

    assert "super-secret" not in hashed


def test_hash_password_is_salted_differently_each_call():
    first = hash_password("same-password")
    second = hash_password("same-password")

    assert first != second
    assert verify_password("same-password", first) is True
    assert verify_password("same-password", second) is True


def test_verify_password_rejects_a_malformed_hash():
    assert verify_password("anything", "not-a-valid-hash") is False


def test_verify_password_rejects_an_unknown_hash_scheme():
    assert verify_password("anything", "bcrypt$10$salt$hash") is False


def test_verify_password_rejects_a_hash_with_non_numeric_cost_parameters():
    # Right shape (6 `$`-separated parts, correct scheme prefix) but `n` is
    # not an integer -> exercises the `int()`/`b64decode` `ValueError` branch
    # past the shape check.
    assert verify_password("anything", "scrypt$not-a-number$8$1$c2FsdA==$aGFzaA==") is False
