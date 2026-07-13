from Module.process_leader import ProcessLeaderLock


def test_only_one_process_lock_is_leader(tmp_path) -> None:
    path = str(tmp_path / "command.lock")
    first = ProcessLeaderLock(path)
    second = ProcessLeaderLock(path)
    try:
        assert first.is_leader is True
        assert second.is_leader is False
    finally:
        second.close()
        first.close()

    replacement = ProcessLeaderLock(path)
    try:
        assert replacement.is_leader is True
    finally:
        replacement.close()


def test_non_leader_can_take_over_after_leader_exits(tmp_path) -> None:
    path = str(tmp_path / "command.lock")
    leader = ProcessLeaderLock(path)
    follower = ProcessLeaderLock(path)
    assert follower.try_acquire() is False

    leader.close()
    try:
        assert follower.try_acquire() is True
    finally:
        follower.close()
