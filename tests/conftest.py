"""全套测试共用的隔离。进程内插件注册表不能泄漏到其他用例。"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

import agentlens.plugins as plugins


@pytest.fixture(autouse=True)
def _isolate_plugins() -> Iterator[None]:
    plugins._clear_plugins()
    yield
    plugins._clear_plugins()
