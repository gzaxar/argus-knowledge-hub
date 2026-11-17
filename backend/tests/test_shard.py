"""The CI shards (tests/shard.py): every test file in exactly one, the same every time, of about the same time."""
from tests.shard import shards, test_files


def test_every_file_is_in_exactly_one_shard_and_the_split_is_stable():
    files = test_files()
    split = shards(4)
    flat = [f for s in split for f in s]
    assert sorted(flat) == files and len(flat) == len(set(flat))
    assert shards(4) == split
    assert "tests/test_shard.py" in flat


def test_the_shards_have_about_the_same_time_and_a_new_file_counts_as_the_median():
    times = {"tests/test_a.py": 100.0, "tests/test_b.py": 60.0, "tests/test_c.py": 40.0, "tests/test_d.py": 10.0}
    split = shards(2, files=[*times, "tests/test_new.py"], times=times)
    load = [sum(times.get(f, 50.0) for f in s) for s in split]
    assert split == [["tests/test_a.py", "tests/test_c.py"], ["tests/test_b.py", "tests/test_d.py", "tests/test_new.py"]]
    assert load == [140.0, 120.0]
