from backend.channel.executors import _project


def test_unmapped_keys_pass_through_and_mapped_keys_are_renamed() -> None:
    rows, error = _project(
        [{"product_code": "a", "name": "n"}],
        [{"attribute": "sku", "key": "product_code"}],
    )
    assert error is None
    assert rows == [{"name": "n", "sku": "a"}]


def test_mapping_wins_over_same_named_source_key() -> None:
    rows, _ = _project(
        [{"sku": "old", "code": "new"}],
        [{"attribute": "sku", "key": "code"}],
    )
    assert rows == [{"sku": "new"}]


def test_empty_mapping_writes_source_as_is() -> None:
    rows, _ = _project([{"sku": "a"}], [])
    assert rows == [{"sku": "a"}]


def test_missing_mapped_key_names_object_and_key() -> None:
    _, error = _project(
        [{"code": "a"}, {"other": 1}],
        [{"attribute": "sku", "key": "code"}],
    )
    assert error is not None
    assert error.error_message == "Source object 1 has no key 'code' for attribute 'sku'"
