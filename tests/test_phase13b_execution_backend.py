import pytest


def test_local_backend_maps_all_items():
    from quantbench.agent.execution_backend import LocalBackend

    backend = LocalBackend()
    results = backend.map(lambda x: x * 2, [1, 2, 3, 4], max_workers=2)

    assert backend.name == "local"
    # Completion order is nondeterministic; compare as a set.
    assert sorted(results) == [2, 4, 6, 8]


def test_local_backend_handles_empty_and_single_item():
    from quantbench.agent.execution_backend import LocalBackend

    backend = LocalBackend()
    assert backend.map(lambda x: x, [], max_workers=4) == []
    assert backend.map(lambda x: x + 1, [10], max_workers=4) == [11]


def test_remote_backend_raises_clear_not_implemented():
    from quantbench.agent.execution_backend import RemoteBackend

    backend = RemoteBackend()
    assert backend.name == "remote"
    with pytest.raises(NotImplementedError, match="remote execution backend is planned"):
        backend.map(lambda x: x, [1, 2], max_workers=4)


def test_get_execution_backend_resolves_names_and_rejects_unknown():
    from quantbench.agent.execution_backend import LocalBackend, RemoteBackend, get_execution_backend

    assert isinstance(get_execution_backend("local"), LocalBackend)
    assert isinstance(get_execution_backend("remote"), RemoteBackend)
    assert isinstance(get_execution_backend(None), LocalBackend)  # config default is local
    with pytest.raises(ValueError, match="unknown execution_backend"):
        get_execution_backend("cluster")


def test_remote_backend_fails_loudly_rather_than_running_locally():
    # The whole point of the interface reservation: switching to remote must error,
    # never silently fall back to a local run.
    from quantbench.agent.execution_backend import get_execution_backend

    calls = []
    backend = get_execution_backend("remote")
    with pytest.raises(NotImplementedError):
        backend.map(lambda x: calls.append(x), [1, 2, 3], max_workers=2)
    assert calls == []
