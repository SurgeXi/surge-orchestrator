# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
from sol.api.dispatch import _canonical_args_hash


def test_canonical_hash_stable_across_key_order():
    a = {"container": "aiap-portal", "cmd": "ls"}
    b = {"cmd": "ls", "container": "aiap-portal"}
    assert _canonical_args_hash(a) == _canonical_args_hash(b)


def test_canonical_hash_changes_on_value_diff():
    a = {"container": "aiap-portal", "cmd": "ls"}
    b = {"container": "aiap-portal", "cmd": "rm -rf /"}
    assert _canonical_args_hash(a) != _canonical_args_hash(b)
