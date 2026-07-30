from interfaces.http.codmes import plugin_data
from interfaces.http.shared import auth, health, me, notices
from interfaces.http.web import chat, lms, portal, search


def _paths(*modules) -> set[str]:
    return {
        route.path
        for module in modules
        for route in module.router.routes
    }


def test_http_routes_are_owned_by_explicit_client_boundaries():
    shared_paths = _paths(auth, health, me, notices)
    web_paths = _paths(chat, lms, portal, search)
    codmes_paths = _paths(plugin_data)

    assert "/health" in shared_paths
    assert "/auth/portal-login" in shared_paths
    assert "/notices" in shared_paths
    assert "/me" in shared_paths

    assert "/chat" in web_paths
    assert "/search" in web_paths
    assert "/portal/sync/start" in web_paths
    assert "/lms/sync/start" in web_paths

    assert codmes_paths == {"/codmes/data/portal"}
    assert not (shared_paths & web_paths)
    assert not (shared_paths & codmes_paths)
    assert not (web_paths & codmes_paths)
