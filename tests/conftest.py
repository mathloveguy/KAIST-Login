import pytest
from kaist_login.storage import Store


class MemoryKeyring:
    def __init__(self):
        self.data = {}

    def get_password(self, service, name):
        return self.data.get((service, name))

    def set_password(self, service, name, value):
        self.data[service, name] = value

    def delete_password(self, service, name):
        del self.data[service, name]


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path, MemoryKeyring())
